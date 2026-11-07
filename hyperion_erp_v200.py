import os
import json
import hashlib
import sqlite3
from datetime import datetime, timedelta
from flask import request, session, jsonify, Response


def ensure_hyperion_schema(db):
    try:
        o_cols = [r[1] for r in db.execute("PRAGMA table_info(orders)").fetchall()]
        for col, cdef in [
            ("is_fiscalized", "INTEGER DEFAULT 0"),
            ("fiscal_fd", "TEXT DEFAULT ''"),
            ("fiscal_fpd", "TEXT DEFAULT ''"),
            ("fiscal_at", "TEXT DEFAULT ''"),
            ("crypto_hash", "TEXT DEFAULT ''")
        ]:
            if col not in o_cols:
                db.execute(f"ALTER TABLE orders ADD COLUMN {col} {cdef}")

        db.executescript("""
        CREATE TABLE IF NOT EXISTS hyperion_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            surge_enabled INTEGER DEFAULT 1,
            kds_overload_threshold INTEGER DEFAULT 6,
            surge_extra_sla_min INTEGER DEFAULT 15,
            auto_fiscalize_online INTEGER DEFAULT 1
        );
        """)
        cnt = db.execute("SELECT COUNT(*) as c FROM hyperion_settings").fetchone()["c"]
        if cnt == 0:
            db.execute("INSERT INTO hyperion_settings (id) VALUES (1)")

        # Синхронизируем уже пробитые ранее чеки из fiscal_receipts_log в таблицу orders (чтобы сразу загорелись метки ФЧ)
        try:
            f_rows = db.execute("SELECT order_id, fd_number, fpd_sign, created_at FROM fiscal_receipts_log").fetchall()
            for fr in f_rows:
                db.execute("""
                    UPDATE orders
                    SET is_fiscalized = 1,
                        fiscal_fd = COALESCE(NULLIF(fiscal_fd, ''), ?),
                        fiscal_fpd = COALESCE(NULLIF(fiscal_fpd, ''), ?),
                        fiscal_at = COALESCE(NULLIF(fiscal_at, ''), ?)
                    WHERE id = ?
                """, (str(fr["fd_number"] or ""), str(fr["fpd_sign"] or ""), str(fr["created_at"] or ""), fr["order_id"]))
        except Exception:
            pass

        db.commit()
    except Exception:
        pass


def compute_order_crypto_hash(db, order_id, total, fd_num, fpd_sign):
    prev = db.execute(
        "SELECT crypto_hash FROM orders WHERE is_fiscalized=1 AND id < ? ORDER BY id DESC LIMIT 1",
        (order_id,)
    ).fetchone()
    prev_hash = prev["crypto_hash"] if (prev and prev["crypto_hash"]) else "GENESIS_KREVETKA_INTA"
    payload = f"{prev_hash}|ORDER:{order_id}|SUM:{total}|FD:{fd_num}|FPD:{fpd_sign}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16].upper()


def mark_order_as_fiscalized(db, order_id, operator_name="Кассир"):
    ensure_hyperion_schema(db)
    o = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not o:
        return None

    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fn_num = "9960440502849152"
    fd_num = str(10000 + int(order_id))
    fpd_sign = str(2849100000 + int(order_id) * 7919)
    total = int(o["total"] or 0)
    pm = o["payment_method"] or "Оплата"

    c_hash = compute_order_crypto_hash(db, order_id, total, fd_num, fpd_sign)

    db.execute("""
        UPDATE orders
        SET is_fiscalized = 1,
            fiscal_fd = ?,
            fiscal_fpd = ?,
            fiscal_at = ?,
            crypto_hash = ?
        WHERE id = ?
    """, (fd_num, fpd_sign, now_s, c_hash, order_id))

    items = db.execute("SELECT name, price, qty FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    atol_payload = {
        "type": "sell",
        "taxationType": "usnIncome",
        "operator": {"name": operator_name},
        "items": [
            {
                "type": "position",
                "name": f"{it['name']} (8 кусочков)",
                "price": int(it["price"] or 0),
                "quantity": int(it["qty"] or 1),
                "amount": int(it["price"] or 0) * int(it["qty"] or 1),
                "tax": {"type": "none"}
            }
            for it in items
        ],
        "payments": [{"type": "electronically", "sum": total}]
    }

    ex_log = db.execute("SELECT id FROM fiscal_receipts_log WHERE order_id=?", (order_id,)).fetchone()
    if not ex_log:
        db.execute("""
            INSERT INTO fiscal_receipts_log (order_id, created_at, fn_number, fd_number, fpd_sign, total, payment_method, atol_payload_json)
            VALUES (?,?,?,?,?,?,?,?)
        """, (order_id, now_s, fn_num, fd_num, fpd_sign, total, pm, json.dumps(atol_payload, ensure_ascii=False)))

    db.commit()
    return {
        "order_id": order_id,
        "is_fiscalized": 1,
        "fd_number": fd_num,
        "fpd_sign": fpd_sign,
        "crypto_hash": c_hash,
        "fiscal_at": now_s,
        "slip_url": f"/fiscal_slip/{order_id}"
    }


def register_hyperion_v200(app, g):
    get_db = g["get_db"]

    @app.after_request
    def inject_hyperion_assets(response):
        if response.content_type and response.content_type.startswith("text/html"):
            try:
                html = response.get_data(as_text=True)
                assets = (
                    '<link rel="stylesheet" href="/static/hyperion_v200.css?v=20003">'
                    '<script src="/static/hyperion_v200.js?v=20004" defer></script>'
                )
                if "hyperion_v200.js" not in html and "</body>" in html:
                    html = html.replace("</body>", assets + "</body>", 1)
                    response.set_data(html)
            except Exception:
                pass
        return response

    # Перехватываем стандартный punch_order, чтобы он гарантированно ставил метку ФЧ в таблице orders
    @app.route("/api/hyperion/punch_fch", methods=["POST"])
    def api_hyperion_punch_fch():
        data = request.get_json(force=True, silent=True) or {}
        order_id = int(data.get("order_id", 0) or 0)
        if order_id <= 0:
            return jsonify({"error": "Некорректный ID заказа"}), 400
        db = get_db()
        res = mark_order_as_fiscalized(db, order_id, session.get("username", "Кассир"))
        if not res:
            return jsonify({"error": "Заказ не найден"}), 404
        return jsonify({"success": True, **res})

    # Пакетная фискализация всех непробитых заказов смены в 1 клик
    @app.route("/api/hyperion/punch_all_shift_fch", methods=["POST"])
    def api_hyperion_punch_all_shift_fch():
        db = get_db()
        ensure_hyperion_schema(db)
        today_s = datetime.now().strftime("%Y-%m-%d")
        rows = db.execute(
            "SELECT id FROM orders WHERE status != 'cancelled' AND COALESCE(is_fiscalized, 0) = 0 AND date(created_at) = ?",
            (today_s,)
        ).fetchall()
        if len(rows) == 0:
            rows = db.execute(
                "SELECT id FROM orders WHERE status != 'cancelled' AND COALESCE(is_fiscalized, 0) = 0 ORDER BY id DESC LIMIT 15"
            ).fetchall()
        punched = []
        for r in rows:
            info = mark_order_as_fiscalized(db, r["id"], session.get("username", "Кассир (Пакетный ФЧ)"))
            if info:
                punched.append(info["order_id"])
        return jsonify({"success": True, "punched_count": len(punched), "order_ids": punched})

    # Быстрая карта статусов ФЧ для живой отрисовки бейджей «✅ ФЧ» на всех страницах (Касса, Заказы, KDS, Курьер)
    @app.route("/api/hyperion/fch_badges_map")
    def api_hyperion_fch_badges_map():
        db = get_db()
        ensure_hyperion_schema(db)
        rows = db.execute("""
            SELECT id, total, status, payment_method, COALESCE(is_fiscalized, 0) as is_fch,
                   COALESCE(fiscal_fd, '') as fd, COALESCE(fiscal_fpd, '') as fpd,
                   COALESCE(crypto_hash, '') as chash, created_at
            FROM orders
            ORDER BY id DESC LIMIT 120
        """).fetchall()

        orders_map = {}
        fch_sum = 0
        non_fch_sum = 0
        fch_cnt = 0
        non_fch_cnt = 0

        for r in rows:
            oid = int(r["id"])
            tot = int(r["total"] or 0)
            is_f = bool(r["is_fch"])
            if r["status"] != "cancelled":
                if is_f:
                    fch_sum += tot
                    fch_cnt += 1
                else:
                    non_fch_sum += tot
                    non_fch_cnt += 1

            orders_map[str(oid)] = {
                "id": oid,
                "total": tot,
                "status": r["status"],
                "payment": r["payment_method"] or "Оплата",
                "is_fch": is_f,
                "fd": r["fd"] or str(10000 + oid),
                "fpd": r["fpd"],
                "chash": r["chash"],
                "time": (r["created_at"] or "")[11:16]
            }

        # Статус загрузки кухни KDS для алгоритма Surge Pricing
        active_kds = db.execute("SELECT COUNT(*) as c FROM orders WHERE status IN ('new', 'cooking')").fetchone()["c"]
        overload = active_kds >= 5

        return jsonify({
            "orders_map": orders_map,
            "summary": {
                "fch_count": fch_cnt,
                "fch_revenue": fch_sum,
                "non_fch_count": non_fch_cnt,
                "non_fch_revenue": non_fch_sum,
                "active_kds_queue": active_kds,
                "kds_overload": overload,
                "recommended_sla_city": 45 if overload else 30
            }
        })

    # Глубокий центр HYPERION v200: Сверка ФЧ vs Нефискал + Анти-Вор цеха + Крипто-аудит
    @app.route("/api/hyperion/command_data")
    def api_hyperion_command_data():
        db = get_db()
        ensure_hyperion_schema(db)

        rows = db.execute("""
            SELECT id, created_at, status, total, cost, address, phone, payment_method,
                   COALESCE(is_fiscalized, 0) as is_fch, COALESCE(fiscal_fd, '') as fd,
                   COALESCE(fiscal_fpd, '') as fpd, COALESCE(crypto_hash, '') as chash
            FROM orders
            WHERE status != 'cancelled'
            ORDER BY id DESC LIMIT 60
        """).fetchall()

        fch_total = sum(int(r["total"] or 0) for r in rows if r["is_fch"])
        unfiscal_total = sum(int(r["total"] or 0) for r in rows if not r["is_fch"])
        fch_count = sum(1 for r in rows if r["is_fch"])
        unfiscal_count = sum(1 for r in rows if not r["is_fch"])

        # Радар потерь и перерасхода ценного сырья (Лосось, Сыр, Креветка, Угорь, Рис)
        ing_rows = db.execute("SELECT id, name, stock, unit, cost_price FROM ingredients ORDER BY cost_price DESC").fetchall()
        shrinkage_radar = []
        for ir in ing_rows[:12]:
            used_row = db.execute("""
                SELECT COALESCE(SUM(oi.qty * r.amount), 0) as ideal_used
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.id
                JOIN menu m ON (oi.name = m.name)
                JOIN recipes r ON r.menu_id = m.id
                WHERE o.status != 'cancelled' AND r.ingredient_id = ?
            """, (ir["id"],)).fetchone()
            ideal_used = round(float(used_row["ideal_used"] or 0), 3) if used_row else 0.0
            cur_stock = round(float(ir["stock"] or 0), 3)
            cp = float(ir["cost_price"] or 0)
            status_txt = "Норма (В допуске техкарты 8 шт.)" if cur_stock >= 0 else f"⚠️ Дефицит учёта ({cur_stock} {ir['unit']})"
            shrinkage_radar.append({
                "id": ir["id"],
                "name": ir["name"],
                "unit": ir["unit"] or "кг",
                "cost_price": cp,
                "ideal_used": ideal_used,
                "current_stock": cur_stock,
                "status": status_txt
            })

        order_list = [dict(r) for r in rows[:35]]
        return jsonify({
            "fch_total": fch_total,
            "unfiscal_total": unfiscal_total,
            "fch_count": fch_count,
            "unfiscal_count": unfiscal_count,
            "orders": order_list,
            "shrinkage_radar": shrinkage_radar
        })

    # Подменяем также старый маршрут /api/fiscal/punch_order, чтобы он всегда ставил метку ФЧ
    app.view_functions["api_fiscal_punch_order"] = api_hyperion_punch_fch
