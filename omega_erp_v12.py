import os
import sqlite3
from datetime import datetime, timedelta
from flask import request, session, jsonify


def ensure_omega_schema(db):
    """Гарантирует наличие всех колонок, чтобы Z-отчёт никогда не падал с ошибкой SQL."""
    try:
        ing_cols = [r[1] for r in db.execute("PRAGMA table_info(ingredients)").fetchall()]
        for col, cdef in [("unit", "TEXT DEFAULT 'кг'"), ("min_stock", "REAL DEFAULT 1.0"), ("cost_price", "REAL DEFAULT 0.0")]:
            if col not in ing_cols:
                db.execute(f"ALTER TABLE ingredients ADD COLUMN {col} {cdef}")

        o_cols = [r[1] for r in db.execute("PRAGMA table_info(orders)").fetchall()]
        for col, cdef in [("cost", "REAL DEFAULT 0"), ("courier_fee", "INTEGER DEFAULT 0"), ("zone_type", "TEXT DEFAULT 'city'"), ("courier_name", "TEXT DEFAULT ''")]:
            if col not in o_cols:
                db.execute(f"ALTER TABLE orders ADD COLUMN {col} {cdef}")

        db.executescript("""
        CREATE TABLE IF NOT EXISTS accounting_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            category TEXT,
            amount REAL DEFAULT 0,
            contour TEXT DEFAULT 'mgmt',
            payment_method TEXT DEFAULT 'наличные',
            pay_status TEXT DEFAULT 'paid',
            comment TEXT DEFAULT '',
            username TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS security_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            username TEXT DEFAULT '',
            ip_addr TEXT DEFAULT '',
            details TEXT DEFAULT ''
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
        db.commit()
    except Exception:
        pass


def register_omega_v12(app, g):
    get_db = g["get_db"]
    get_open_shift = g["get_open_shift"]

    # Автоматическая инжекция скрипта OMEGA v12 перед </body> на КАЖДОЙ странице
    @app.after_request
    def inject_omega_script(response):
        if response.content_type and response.content_type.startswith("text/html"):
            try:
                html = response.get_data(as_text=True)
                tag = '<script src="/static/omega_erp_v12.js?v=1205" defer></script>'
                if "omega_erp_v12.js" not in html and "</body>" in html:
                    html = html.replace("</body>", tag + "</body>", 1)
                    response.set_data(html)
            except Exception:
                pass
        return response

    @app.route("/api/omega/dashboard")
    def api_omega_dashboard():
        db = get_db()
        ensure_omega_schema(db)

        today_s = datetime.now().strftime("%Y-%m-%d")
        opening_cash = 0
        try:
            shift = get_open_shift()
            if shift and "opening_cash" in shift.keys():
                opening_cash = int(shift["opening_cash"] or 0)
        except Exception:
            opening_cash = 0

        # 1. ДАННЫЕ Z-ОТЧЁТА И ПРОДАЖ ЗА СЕГОДНЯ
        orders = db.execute(
            """
            SELECT id, created_at, status, total, cost, address, phone,
                   payment_method, delivery_type, courier_fee, zone_type, courier_name
            FROM orders
            WHERE date(created_at) = ?
            ORDER BY id DESC
            """,
            (today_s,)
        ).fetchall()

        # Если сегодня заказов ещё 0, показываем также сводку за последние 7 дней для наглядности
        period_label = f"Сегодня ({today_s})"
        if len(orders) == 0:
            since_7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            orders = db.execute(
                """
                SELECT id, created_at, status, total, cost, address, phone,
                       payment_method, delivery_type, courier_fee, zone_type, courier_name
                FROM orders
                WHERE date(created_at) >= ?
                ORDER BY id DESC
                """,
                (since_7,)
            ).fetchall()
            if len(orders) > 0:
                period_label = f"Последние 7 дней (сегодня чеков пока 0)"

        cash_rev = 0
        card_rev = 0
        total_rev = 0
        total_foodcost = 0
        courier_payouts = 0
        delivery_cnt = 0
        pickup_cnt = 0
        cancelled_orders = []
        valid_cnt = 0

        # Статистика по 4 районам Инты
        zones_map = {
            "Город (Центр)": {"cnt": 0, "rev": 0, "courier_pay": 0, "color": "#16a34a"},
            "Западный район": {"cnt": 0, "rev": 0, "courier_pay": 0, "color": "#eab308"},
            "Южный / Сельхоз": {"cnt": 0, "rev": 0, "courier_pay": 0, "color": "#f97316"},
            "Верхняя Инта / Станция": {"cnt": 0, "rev": 0, "courier_pay": 0, "color": "#dc2626"},
            "Самовывоз": {"cnt": 0, "rev": 0, "courier_pay": 0, "color": "#38bdf8"},
        }

        for o in orders:
            t = int(o["total"] or 0)
            if o["status"] == "cancelled":
                cancelled_orders.append({
                    "id": o["id"],
                    "time": (o["created_at"] or "")[11:16],
                    "total": t,
                    "address": o["address"] or "Самовывоз"
                })
                continue

            valid_cnt += 1
            total_rev += t
            total_foodcost += int(round(float(o["cost"] or 0)))

            pm = (o["payment_method"] or "").lower()
            if pm in ("наличные", "cash"):
                cash_rev += t
            else:
                card_rev += t

            dtype = (o["delivery_type"] or "доставка").lower()
            addr_low = (o["address"] or "").lower()
            cfee = int(o["courier_fee"] or (0 if dtype == "самовывоз" else 150))

            if dtype == "самовывоз":
                pickup_cnt += 1
                z_key = "Самовывоз"
                cfee = 0
            else:
                delivery_cnt += 1
                courier_payouts += cfee
                if any(w in addr_low for w in ("верхн", "станц", "вокзал", "депо", "лазур", "юсьтыдор")):
                    z_key = "Верхняя Инта / Станция"
                elif any(w in addr_low for w in ("южн", "сельхоз", "кирова", "чайковск", "совхоз", "лугов")):
                    z_key = "Южный / Сельхоз"
                elif any(w in addr_low for w in ("запад", "заречн", "геолог", "шахт", "северн", "тундр")):
                    z_key = "Западный район"
                else:
                    z_key = "Город (Центр)"

            zones_map[z_key]["cnt"] += 1
            zones_map[z_key]["rev"] += t
            zones_map[z_key]["courier_pay"] += cfee

        hourly_payroll = 0
        courier_payroll = courier_payouts
        try:
            st_row = db.execute(
                """
                SELECT COALESCE(SUM(hourly_pay), 0) as hp,
                       COALESCE(SUM(delivery_pay), 0) as dp
                FROM staff_shifts
                WHERE date(opened_at) = ?
                """,
                (today_s,)
            ).fetchone()
            if st_row:
                hourly_payroll = int(st_row["hp"] or 0)
                courier_payroll = max(int(st_row["dp"] or 0), courier_payouts)
        except Exception:
            pass

        cash_expenses = 0
        try:
            er = db.execute(
                "SELECT COALESCE(SUM(amount), 0) as e FROM accounting_expenses WHERE date(created_at)=?",
                (today_s,)
            ).fetchone()
            if er:
                cash_expenses = int(er["e"] or 0)
        except Exception:
            pass

        expected_drawer_cash = opening_cash + cash_rev - courier_payroll - cash_expenses
        avg_check = int(round(total_rev / valid_cnt)) if valid_cnt > 0 else 0
        net_profit = total_rev - total_foodcost - hourly_payroll - courier_payroll - cash_expenses

        # 2. СПИСОК АВТО-ЗАКУПА СЫРЬЯ
        procurement = []
        try:
            ing_rows = db.execute(
                "SELECT id, name, stock, unit, min_stock, cost_price FROM ingredients ORDER BY stock ASC"
            ).fetchall()
            for ir in ing_rows:
                st = round(float(ir["stock"] or 0), 2)
                ms = round(float(ir["min_stock"] or 1.0), 2)
                cp = float(ir["cost_price"] or 0)
                if st <= ms * 1.5:
                    need = round(max(ms * 3.0 - st, ms), 2)
                    procurement.append({
                        "name": ir["name"],
                        "stock": st,
                        "min_stock": ms,
                        "unit": ir["unit"] or "кг",
                        "order_qty": need,
                        "est_cost": int(round(need * cp))
                    })
        except Exception:
            pass

        # 3. АНТИ-ФРОД И БЕЗОПАСНОСТЬ СОБСТВЕННИКА
        writeoffs = []
        try:
            w_rows = db.execute(
                """
                SELECT created_at, ing_name, change_amount, reason, cost_impact, username
                FROM stock_logs
                WHERE op_type IN ('списание', 'возврат')
                ORDER BY id DESC LIMIT 12
                """
            ).fetchall()
            writeoffs = [dict(w) for w in w_rows]
        except Exception:
            pass

        sec_events = []
        try:
            s_rows = db.execute(
                "SELECT created_at, event_type, username, ip_addr, details FROM security_audit_log ORDER BY id DESC LIMIT 12"
            ).fetchall()
            sec_events = [dict(s) for s in s_rows]
        except Exception:
            pass

        zones_list = [{"name": k, **v} for k, v in zones_map.items()]

        return jsonify({
            "period_label": period_label,
            "date": today_s,
            "orders_count": valid_cnt,
            "cancelled_count": len(cancelled_orders),
            "cancelled_orders": cancelled_orders[:10],
            "delivery_count": delivery_cnt,
            "pickup_count": pickup_cnt,
            "avg_check": avg_check,
            "total_revenue": total_rev,
            "cash_revenue": cash_rev,
            "card_revenue": card_rev,
            "opening_cash": opening_cash,
            "food_cost": total_foodcost,
            "hourly_payroll": hourly_payroll,
            "courier_payroll": courier_payroll,
            "cash_expenses": cash_expenses,
            "expected_drawer_cash": expected_drawer_cash,
            "day_net_profit": net_profit,
            "zones_stats": zones_list,
            "procurement": procurement,
            "writeoffs": writeoffs,
            "security_events": sec_events
        })

    # Перенаправляем также старый маршрут /api/ultra/zreport_and_prep на безотказный обработчик
    app.view_functions["api_ultra_zreport_and_prep"] = api_omega_dashboard
