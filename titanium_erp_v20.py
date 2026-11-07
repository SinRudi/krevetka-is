import os
import sqlite3
from datetime import datetime, timedelta
from flask import request, session, jsonify, Response


def cleanup_and_ensure_schema(db):
    """Удаляет любые следы бургеров и создаёт таблицы П/Ф и инвентаризаций уровня iiko/Presto."""
    try:
        db.execute(
            "DELETE FROM menu WHERE lower(category) LIKE '%бургер%' OR lower(name) LIKE '%бургер%' OR lower(name) LIKE '%картофель фри%'"
        )
        db.execute("DROP TABLE IF EXISTS franchise_branches")

        ing_cols = [r[1] for r in db.execute("PRAGMA table_info(ingredients)").fetchall()]
        for col, cdef in [
            ("unit", "TEXT DEFAULT 'кг'"),
            ("min_stock", "REAL DEFAULT 1.0"),
            ("cost_price", "REAL DEFAULT 0.0"),
            ("waste_pct", "REAL DEFAULT 0.0")
        ]:
            if col not in ing_cols:
                db.execute(f"ALTER TABLE ingredients ADD COLUMN {col} {cdef}")

        o_cols = [r[1] for r in db.execute("PRAGMA table_info(orders)").fetchall()]
        for col, cdef in [
            ("cost", "REAL DEFAULT 0"),
            ("courier_fee", "INTEGER DEFAULT 0"),
            ("zone_type", "TEXT DEFAULT 'city'"),
            ("courier_name", "TEXT DEFAULT ''")
        ]:
            if col not in o_cols:
                db.execute(f"ALTER TABLE orders ADD COLUMN {col} {cdef}")

        db.executescript("""
        CREATE TABLE IF NOT EXISTS prep_acts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            prep_name TEXT,
            raw_weight REAL,
            yield_weight REAL,
            waste_pct REAL,
            cost_per_kg REAL,
            chef_name TEXT
        );
        CREATE TABLE IF NOT EXISTS inventory_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            ingredient_id INTEGER,
            ing_name TEXT,
            expected_stock REAL,
            actual_stock REAL,
            diff_qty REAL,
            diff_rub REAL,
            auditor TEXT
        );
        CREATE TABLE IF NOT EXISTS stock_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            ingredient_id INTEGER,
            ing_name TEXT,
            change_amount REAL DEFAULT 0,
            op_type TEXT,
            reason TEXT,
            cost_impact REAL DEFAULT 0,
            username TEXT,
            order_id INTEGER
        );
        """)

        # Приводим все роллы к строгому стандарту 8 кусочков
        rows = db.execute("SELECT id, name, description FROM menu").fetchall()
        for r in rows:
            n_name = (r["name"] or "").replace("10 шт", "8 шт").replace("10 кусочков", "8 кусочков")
            n_desc = (r["description"] or "").replace("10 шт", "8 шт").replace("10 кусочков", "8 кусочков")
            if n_name != (r["name"] or "") or n_desc != (r["description"] or ""):
                db.execute("UPDATE menu SET name=?, description=? WHERE id=?", (n_name, n_desc, r["id"]))

        db.commit()
    except Exception:
        pass


def register_titanium_v20(app, g):
    get_db = g["get_db"]
    get_open_shift = g["get_open_shift"]

    @app.after_request
    def inject_clean_titanium_assets(response):
        if response.content_type and response.content_type.startswith("text/html"):
            try:
                html = response.get_data(as_text=True)
                # Удаляем старые конфликтующие скрипты, которые ломали вёрстку
                for legacy in ("franchise_v15.css", "franchise_v15.js", "omega_erp_v12.js", "ultra_erp_v10.js"):
                    if legacy in html:
                        import re
                        html = re.sub(rf'<[^>]*{legacy}[^>]*>(</script>)?', '', html)

                assets = (
                    '<link rel="stylesheet" href="/static/titanium_v20.css?v=2001">'
                    '<script src="/static/titanium_v20.js?v=2001" defer></script>'
                )
                if "titanium_v20.js" not in html and "</body>" in html:
                    html = html.replace("</body>", assets + "</body>", 1)
                response.set_data(html)
            except Exception:
                pass
        return response

    @app.route("/api/titanium/full_suite")
    def api_titanium_full_suite():
        db = get_db()
        cleanup_and_ensure_schema(db)

        days = int(request.args.get("days", 7) or 7)
        today_s = datetime.now().strftime("%Y-%m-%d")
        since_s = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        opening_cash = 0
        try:
            sh = get_open_shift()
            if sh and "opening_cash" in sh.keys():
                opening_cash = int(sh["opening_cash"] or 0)
        except Exception:
            pass

        orders = db.execute(
            """
            SELECT id, created_at, status, total, cost, address, phone,
                   payment_method, delivery_type, courier_fee, zone_type
            FROM orders
            WHERE date(created_at) = ?
            ORDER BY id DESC
            """,
            (today_s,)
        ).fetchall()

        period_title = f"Текущая смена ({today_s})"
        if len(orders) == 0:
            orders = db.execute(
                """
                SELECT id, created_at, status, total, cost, address, phone,
                       payment_method, delivery_type, courier_fee, zone_type
                FROM orders
                WHERE date(created_at) >= ?
                ORDER BY id DESC
                """,
                (since_s,)
            ).fetchall()
            if len(orders) > 0:
                period_title = f"Сводка за {days} дн. (сегодня чеков пока 0)"

        cash_rev = 0
        card_rev = 0
        total_rev = 0
        total_fc = 0
        courier_pay = 0
        valid_cnt = 0
        cancelled_list = []

        zones = {
            "Город (Центр)": {"cnt": 0, "rev": 0, "fee": 0, "sla": "30 мин", "color": "#10b981"},
            "Западный район": {"cnt": 0, "rev": 0, "fee": 0, "sla": "40 мин", "color": "#eab308"},
            "Южный / Сельхоз": {"cnt": 0, "rev": 0, "fee": 0, "sla": "42 мин", "color": "#f97316"},
            "Верхняя Инта / Станция": {"cnt": 0, "rev": 0, "fee": 0, "sla": "50 мин", "color": "#ef4444"},
            "Самовывоз с точки": {"cnt": 0, "rev": 0, "fee": 0, "sla": "20 мин", "color": "#38bdf8"},
        }

        for o in orders:
            t = int(o["total"] or 0)
            if o["status"] == "cancelled":
                cancelled_list.append({
                    "id": o["id"],
                    "time": (o["created_at"] or "")[11:16],
                    "total": t,
                    "address": o["address"] or "Самовывоз"
                })
                continue

            valid_cnt += 1
            total_rev += t
            total_fc += int(round(float(o["cost"] or 0)))

            pm = (o["payment_method"] or "").lower()
            if pm in ("наличные", "cash"):
                cash_rev += t
            else:
                card_rev += t

            dtype = (o["delivery_type"] or "доставка").lower()
            addr = (o["address"] or "").lower()
            cfee = int(o["courier_fee"] or (0 if dtype == "самовывоз" else 150))

            if dtype == "самовывоз":
                z_name = "Самовывоз с точки"
                cfee = 0
            else:
                courier_pay += cfee
                if any(w in addr for w in ("верхн", "станц", "вокзал", "депо", "лазур")):
                    z_name = "Верхняя Инта / Станция"
                elif any(w in addr for w in ("южн", "сельхоз", "кирова", "чайковск", "лугов")):
                    z_name = "Южный / Сельхоз"
                elif any(w in addr for w in ("запад", "заречн", "геолог", "шахт", "тундр")):
                    z_name = "Западный район"
                else:
                    z_name = "Город (Центр)"

            zones[z_name]["cnt"] += 1
            zones[z_name]["rev"] += t
            zones[z_name]["fee"] += cfee

        hourly_pay = 0
        try:
            sr = db.execute(
                "SELECT COALESCE(SUM(hourly_pay),0) as hp, COALESCE(SUM(delivery_pay),0) as dp FROM staff_shifts WHERE date(opened_at)=?",
                (today_s,)
            ).fetchone()
            if sr:
                hourly_pay = int(sr["hp"] or 0)
                courier_pay = max(int(sr["dp"] or 0), courier_pay)
        except Exception:
            pass

        expenses_cash = 0
        try:
            er = db.execute(
                "SELECT COALESCE(SUM(amount),0) as e FROM accounting_expenses WHERE date(created_at)=?",
                (today_s,)
            ).fetchone()
            if er:
                expenses_cash = int(er["e"] or 0)
        except Exception:
            pass

        expected_drawer = opening_cash + cash_rev - courier_pay - expenses_cash
        avg_check = int(round(total_rev / valid_cnt)) if valid_cnt > 0 else 0
        net_profit = total_rev - total_fc - hourly_pay - courier_pay - expenses_cash
        fc_pct = round((total_fc / total_rev * 100.0), 1) if total_rev > 0 else 0.0

        # ABC-матрица продаж (iiko / Saby Presto стандарт)
        abc_rows = db.execute(
            """
            SELECT oi.name, SUM(oi.qty) as qty, SUM(oi.price * oi.qty) as rev
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE o.status != 'cancelled' AND date(o.created_at) >= ?
            GROUP BY oi.name
            ORDER BY rev DESC
            """,
            (since_s,)
        ).fetchall()

        sum_abc_rev = sum(int(r["rev"] or 0) for r in abc_rows) or 1
        cum = 0.0
        abc_matrix = []
        for r in abc_rows:
            rv = int(r["rev"] or 0)
            sh_pct = (rv / sum_abc_rev) * 100.0
            cum += sh_pct
            grp = "A" if (cum <= 80.0 or len(abc_matrix) == 0) else ("B" if cum <= 95.0 else "C")
            abc_matrix.append({
                "name": r["name"],
                "qty": int(r["qty"] or 0),
                "rev": rv,
                "share": round(sh_pct, 1),
                "group": grp
            })

        # Склад, авто-закуп и сличительная ведомость
        ing_rows = db.execute(
            "SELECT id, name, stock, unit, min_stock, cost_price FROM ingredients ORDER BY name"
        ).fetchall()
        ingredients = []
        procurement = []
        for ir in ing_rows:
            st = round(float(ir["stock"] or 0), 2)
            ms = round(float(ir["min_stock"] or 1.0), 2)
            cp = float(ir["cost_price"] or 0)
            u = ir["unit"] or "кг"
            ingredients.append({
                "id": ir["id"],
                "name": ir["name"],
                "stock": st,
                "min_stock": ms,
                "unit": u,
                "cost_price": cp
            })
            if st <= ms * 1.4:
                need = round(max(ms * 3.0 - st, ms), 2)
                procurement.append({
                    "name": ir["name"],
                    "stock": st,
                    "min_stock": ms,
                    "unit": u,
                    "order_qty": need,
                    "est_cost": int(round(need * cp))
                })

        preps = [dict(p) for p in db.execute("SELECT * FROM prep_acts ORDER BY id DESC LIMIT 10").fetchall()]
        audits = [dict(a) for a in db.execute("SELECT * FROM inventory_audits ORDER BY id DESC LIMIT 12").fetchall()]

        return jsonify({
            "period_title": period_title,
            "date": today_s,
            "orders_count": valid_cnt,
            "cancelled_count": len(cancelled_list),
            "cancelled_orders": cancelled_list[:10],
            "avg_check": avg_check,
            "total_revenue": total_rev,
            "cash_revenue": cash_rev,
            "card_revenue": card_rev,
            "opening_cash": opening_cash,
            "food_cost": total_fc,
            "food_cost_pct": fc_pct,
            "hourly_payroll": hourly_pay,
            "courier_payroll": courier_pay,
            "cash_expenses": expenses_cash,
            "expected_drawer_cash": expected_drawer,
            "net_profit": net_profit,
            "zones": [{"name": k, **v} for k, v in zones.items()],
            "abc_matrix": abc_matrix[:18],
            "ingredients": ingredients,
            "procurement": procurement,
            "prep_acts": preps,
            "inventory_audits": audits
        })

    # Акт проработки / заготовки П/Ф (Варка риса, Разделка лосося, Замес соусов)
    @app.route("/api/titanium/prep_act", methods=["POST"])
    def api_titanium_prep_act():
        if session.get("role") not in ("admin", "cashier", "kitchen"):
            return jsonify({"error": "Доступ запрещён"}), 403

        data = request.get_json(force=True, silent=True) or {}
        prep_name = (data.get("prep_name") or "Варка суши-риса").strip()
        raw_w = float(data.get("raw_weight", 0) or 0)
        yield_w = float(data.get("yield_weight", 0) or 0)
        raw_cost = float(data.get("raw_cost_total", 0) or 0)

        if raw_w <= 0 or yield_w <= 0:
            return jsonify({"error": "Укажите вес сырья и выход готового П/Ф > 0"}), 400

        waste_pct = round((1.0 - (yield_w / raw_w)) * 100.0, 1)
        cost_per_kg = round(raw_cost / yield_w, 2) if yield_w > 0 else 0.0
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")

        db = get_db()
        cleanup_and_ensure_schema(db)
        db.execute(
            """
            INSERT INTO prep_acts (created_at, prep_name, raw_weight, yield_weight, waste_pct, cost_per_kg, chef_name)
            VALUES (?,?,?,?,?,?,?)
            """,
            (now_s, prep_name, raw_w, yield_w, waste_pct, cost_per_kg, session.get("username", "Шеф"))
        )
        db.commit()
        return jsonify({"success": True, "waste_pct": waste_pct, "cost_per_kg": cost_per_kg})

    # Инвентаризация склада (Сличительная ведомость как в Saby Presto / iiko)
    @app.route("/api/titanium/inventory_check", methods=["POST"])
    def api_titanium_inventory_check():
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Доступ запрещён"}), 403

        data = request.get_json(force=True, silent=True) or {}
        ing_id = int(data.get("ingredient_id", 0) or 0)
        actual_val = float(data.get("actual_stock", 0) or 0)

        db = get_db()
        cleanup_and_ensure_schema(db)
        ing = db.execute("SELECT * FROM ingredients WHERE id=?", (ing_id,)).fetchone()
        if not ing:
            return jsonify({"error": "Ингредиент не найден"}), 404

        expected_val = round(float(ing["stock"] or 0), 3)
        diff_qty = round(actual_val - expected_val, 3)
        diff_rub = round(diff_qty * float(ing["cost_price"] or 0), 2)
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")

        db.execute("UPDATE ingredients SET stock=? WHERE id=?", (actual_val, ing_id))
        db.execute(
            """
            INSERT INTO inventory_audits
            (created_at, ingredient_id, ing_name, expected_stock, actual_stock, diff_qty, diff_rub, auditor)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (now_s, ing_id, ing["name"], expected_val, actual_val, diff_qty, diff_rub, session.get("username", "Директор"))
        )
        db.commit()
        return jsonify({"success": True, "diff_qty": diff_qty, "diff_rub": diff_rub})

    # Совместимость со всеми старыми вызовами Z-отчёта
    app.view_functions["api_omega_dashboard"] = api_titanium_full_suite
    app.view_functions["api_ultra_zreport_and_prep"] = api_titanium_full_suite


    # === ГЕО-ЗОНЫ Г. ИНТА И ЖИВАЯ КАРТА КУРЬЕРОВ (/api/map/*) ===
    def ensure_inta_zones_table(db):
        db.executescript("""
        CREATE TABLE IF NOT EXISTS delivery_zones_inta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            fee INTEGER DEFAULT 150,
            sla_min INTEGER DEFAULT 35,
            free_from INTEGER DEFAULT 1200,
            color TEXT DEFAULT '#10b981',
            streets_hint TEXT DEFAULT '',
            coords_json TEXT DEFAULT '[]'
        );
        """)
        cnt = db.execute("SELECT COUNT(*) as c FROM delivery_zones_inta").fetchone()["c"]
        if cnt == 0:
            import json
            presets = [
                (
                    "Центр / Город (I зона)", 150, 30, 1000, "#10b981",
                    "ул. Куратова, Горького, Мира, Полярная, Дзержинского, Бабушкина",
                    [[66.0420, 60.1460], [66.0420, 60.1860], [66.0220, 60.1860], [66.0220, 60.1460]]
                ),
                (
                    "Западный район (II зона)", 180, 38, 1300, "#eab308",
                    "ул. Воркутинская, Морозова, Заречная, Геологов, Шахтинская",
                    [[66.0450, 60.1120], [66.0430, 60.1450], [66.0230, 60.1450], [66.0230, 60.1120]]
                ),
                (
                    "Южный / Сельхоз (III зона)", 220, 42, 1500, "#f97316",
                    "ул. Кирова, Чайковского, Луговая, мкр. Южный, Сельхоз",
                    [[66.0215, 60.1350], [66.0215, 60.1880], [66.0020, 60.1880], [66.0020, 60.1350]]
                ),
                (
                    "Верхняя Инта / Станция (IV зона)", 300, 50, 2000, "#ef4444",
                    "Ж/Д Вокзал Инта-1, Депо, Лазурная, пгт. Верхняя Инта",
                    [[66.0860, 60.2300], [66.0860, 60.3050], [66.0580, 60.3050], [66.0580, 60.2300]]
                )
            ]
            for name, fee, sla, free_f, col, hint, coords in presets:
                db.execute(
                    "INSERT INTO delivery_zones_inta (name, fee, sla_min, free_from, color, streets_hint, coords_json) VALUES (?,?,?,?,?,?,?)",
                    (name, fee, sla, free_f, col, hint, json.dumps(coords))
                )
            db.commit()

    @app.route("/api/map/zones_data")
    def api_map_zones_data():
        import json
        db = get_db()
        ensure_inta_zones_table(db)
        rows = db.execute("SELECT * FROM delivery_zones_inta ORDER BY fee ASC, id ASC").fetchall()
        zones = []
        for r in rows:
            try:
                coords = json.loads(r["coords_json"] or "[]")
            except Exception:
                coords = []
            zones.append({
                "id": r["id"],
                "name": r["name"],
                "fee": r["fee"],
                "sla_min": r["sla_min"],
                "free_from": r["free_from"],
                "color": r["color"],
                "streets_hint": r["streets_hint"],
                "coords": coords
            })

        # Живые заказы на карте Инты
        active_rows = db.execute("""
            SELECT id, address, total, status
            FROM orders
            WHERE status IN ('new', 'cooking', 'ready')
            ORDER BY id DESC LIMIT 15
        """).fetchall()
        active_orders = []
        for idx, o in enumerate(active_rows):
            addr = (o["address"] or "").lower()
            if any(w in addr for w in ("верхн", "вокзал", "станц", "депо")):
                lat, lng, zname = 66.0710 + (idx * 0.0012), 60.2640 + (idx * 0.0015), "Верхняя Инта"
            elif any(w in addr for w in ("южн", "сельхоз", "кирова", "чайковск")):
                lat, lng, zname = 66.0135 + (idx * 0.001), 60.1610 + (idx * 0.0015), "Южный / Сельхоз"
            elif any(w in addr for w in ("воркут", "запад", "морозов", "зареч")):
                lat, lng, zname = 66.0345 + (idx * 0.001), 60.1290 + (idx * 0.0015), "Западный район"
            else:
                lat, lng, zname = 66.0320 + (idx * 0.0012), 60.1660 + (idx * 0.0018), "Центр / Город"

            active_orders.append({
                "id": o["id"],
                "address": o["address"] or "Самовывоз",
                "total": int(o["total"] or 0),
                "status": o["status"] or "new",
                "lat": round(lat, 5),
                "lng": round(lng, 5),
                "zone_name": zname
            })

        return jsonify({"zones": zones, "active_orders": active_orders})

    @app.route("/api/map/zones_save", methods=["POST"])
    def api_map_zones_save():
        import json
        data = request.get_json(force=True, silent=True) or {}
        name = (data.get("name") or "Новая зона").strip()
        fee = int(data.get("fee", 150) or 150)
        sla = int(data.get("sla_min", 35) or 35)
        free_from = int(data.get("free_from", 1200) or 1200)
        color = data.get("color") or "#38bdf8"
        default_poly = [[66.0390, 60.1500], [66.0390, 60.1780], [66.0260, 60.1780], [66.0260, 60.1500]]

        db = get_db()
        ensure_inta_zones_table(db)
        db.execute(
            "INSERT INTO delivery_zones_inta (name, fee, sla_min, free_from, color, streets_hint, coords_json) VALUES (?,?,?,?,?,?,?)",
            (name, fee, sla, free_from, color, "Пользовательская зона доставки г. Инта", json.dumps(default_poly))
        )
        db.commit()
        return jsonify({"success": True})

    @app.route("/api/map/zones_delete", methods=["POST"])
    def api_map_zones_delete():
        data = request.get_json(force=True, silent=True) or {}
        zid = int(data.get("id", 0) or 0)
        db = get_db()
        ensure_inta_zones_table(db)
        db.execute("DELETE FROM delivery_zones_inta WHERE id=?", (zid,))
        db.commit()
        return jsonify({"success": True})

    @app.route("/api/map/zones_reset", methods=["POST"])
    def api_map_zones_reset():
        db = get_db()
        db.execute("DROP TABLE IF EXISTS delivery_zones_inta")
        ensure_inta_zones_table(db)
        return jsonify({"success": True})
