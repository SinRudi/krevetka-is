import os
import sqlite3
from datetime import datetime, timedelta
from flask import request, session, jsonify


def register_power_pack(app, g):
    get_db = g["get_db"]

    @app.route("/api/crm/lookup")
    def api_crm_lookup():
        raw_phone = (request.args.get("phone") or "").strip()
        digits = "".join(ch for ch in raw_phone if ch.isdigit())
        if len(digits) < 6:
            return jsonify({"found": False})

        tail = digits[-10:] if len(digits) >= 10 else digits
        db = get_db()

        orders = db.execute(
            """
            SELECT id, created_at, total, address, delivery_type, zone_type
            FROM orders
            WHERE replace(replace(replace(replace(phone,'+',''),'-',''),' ',''),'(','')
                  LIKE ?
              AND status != 'cancelled'
            ORDER BY id DESC LIMIT 30
            """,
            (f"%{tail}%",)
        ).fetchall()

        if not orders:
            return jsonify({"found": False, " digits": tail})

        total_spent = sum(int(o["total"] or 0) for o in orders)
        orders_cnt = len(orders)
        last_addr = ""
        for o in orders:
            addr = (o["address"] or "").strip()
            if addr and addr.lower() != "самовывоз":
                last_addr = addr
                break

        fav_rows = db.execute(
            """
            SELECT oi.name, SUM(oi.qty) as cnt
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE replace(replace(replace(o.phone,'+',''),'-',''),' ','') LIKE ?
              AND o.status != 'cancelled'
            GROUP BY oi.name
            ORDER BY cnt DESC LIMIT 3
            """,
            (f"%{tail}%",)
        ).fetchall()
        fav_items = [f"{r['name']} ({r['cnt']}x)" for r in fav_rows]

        if orders_cnt >= 10 or total_spent >= 15000:
            tier = "VIP КЛИЕНТ"
            tier_color = "#ff6900"
        elif orders_cnt >= 3 or total_spent >= 3500:
            tier = "ПОСТОЯННЫЙ"
            tier_color = "#16a34a"
        else:
            tier = "НОВЫЙ КЛИЕНТ"
            tier_color = "#38bdf8"

        bonuses = int(round(total_spent * 0.05))
        return jsonify({
            "found": True,
            "orders_count": orders_cnt,
            "total_spent": total_spent,
            "bonuses": bonuses,
            "tier": tier,
            "tier_color": tier_color,
            "last_address": last_addr,
            "favorites": fav_items
        })

    @app.route("/api/courier/my_stats")
    def api_courier_my_stats():
        db = get_db()
        uid = session.get("user_id")
        today_s = datetime.now().strftime("%Y-%m-%d")

        rows = db.execute(
            """
            SELECT id, total, address, payment_method, status,
                   COALESCE(NULLIF(courier_fee, 0), 150) as c_fee,
                   COALESCE(zone_type, 'city') as z_type
            FROM orders
            WHERE delivery_type = 'доставка'
              AND status IN ('delivering', 'done')
              AND date(created_at) = ?
              AND (courier_id = ? OR courier_id IS NULL)
            """,
            (today_s, uid)
        ).fetchall()

        city_cnt = sum(1 for r in rows if r["z_type"] != "distant")
        dist_cnt = sum(1 for r in rows if r["z_type"] == "distant")
        total_fee = sum(int(r["c_fee"] or 150) for r in rows)
        cash_to_hand = sum(
            int(r["total"] or 0) for r in rows
            if (r["payment_method"] or "").lower() in ("наличные", "cash")
            and r["status"] == "done"
        )

        return jsonify({
            "orders_total": len(rows),
            "city_count": city_cnt,
            "distant_count": dist_cnt,
            "earned_today": total_fee,
            "cash_collected": cash_to_hand
        })

    @app.route("/api/erp/abc_pnl")
    def api_erp_abc_pnl():
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Доступ запрещён"}), 403

        db = get_db()
        days = int(request.args.get("days", 7) or 7)
        since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        ord_stat = db.execute(
            """
            SELECT COUNT(*) as cnt,
                   COALESCE(SUM(total), 0) as rev,
                   COALESCE(SUM(cost), 0) as food_cost,
                   COALESCE(SUM(courier_fee), 0) as courier_cost
            FROM orders
            WHERE status != 'cancelled' AND date(created_at) >= ?
            """,
            (since_date,)
        ).fetchone()

        rev = int(ord_stat["rev"] or 0)
        food_cost = int(round(float(ord_stat["food_cost"] or 0)))
        courier_cost = int(ord_stat["courier_cost"] or 0)

        staff_row = db.execute(
            """
            SELECT COALESCE(SUM(hourly_pay), 0) as h_pay,
                   COALESCE(SUM(delivery_pay), 0) as d_pay
            FROM staff_shifts
            WHERE date(opened_at) >= ?
            """,
            (since_date,)
        ).fetchone()

        payroll_hours = int(staff_row["h_pay"] or 0)
        payroll_courier = max(int(staff_row["d_pay"] or 0), courier_cost)
        total_payroll = payroll_hours + payroll_courier

        opex_row = db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as exp
            FROM accounting_expenses
            WHERE date(created_at) >= ? AND category != 'Зарплата (ФОТ)'
            """,
            (since_date,)
        ).fetchone()
        other_expenses = int(opex_row["exp"] or 0)

        net_profit = rev - food_cost - total_payroll - other_expenses
        food_cost_pct = round((food_cost / rev * 100), 1) if rev > 0 else 0.0
        fot_pct = round((total_payroll / rev * 100), 1) if rev > 0 else 0.0
        margin_pct = round((net_profit / rev * 100), 1) if rev > 0 else 0.0

        # ABC-анализ позиций меню
        items_rows = db.execute(
            """
            SELECT oi.name,
                   SUM(oi.qty) as qty_sold,
                   SUM(oi.price * oi.qty) as item_rev
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE o.status != 'cancelled' AND date(o.created_at) >= ?
            GROUP BY oi.name
            ORDER BY item_rev DESC
            """,
            (since_date,)
        ).fetchall()

        total_items_rev = sum(int(r["item_rev"] or 0) for r in items_rows) or 1
        cum_share = 0.0
        abc_list = []
        for r in items_rows:
            irev = int(r["item_rev"] or 0)
            share = (irev / total_items_rev) * 100.0
            cum_share += share
            if cum_share <= 80.0 or len(abc_list) == 0:
                grp = "A"
                verdict = "ХИТ (Лидер кассы)"
            elif cum_share <= 95.0:
                grp = "B"
                verdict = "Стабильный спрос"
            else:
                grp = "C"
                verdict = "Кандидат на замену"
            abc_list.append({
                "name": r["name"],
                "qty": int(r["qty_sold"] or 0),
                "revenue": irev,
                "share": round(share, 1),
                "group": grp,
                "verdict": verdict
            })

        low_stock = db.execute(
            """
            SELECT id, name, stock, unit, min_stock, cost_price
            FROM ingredients
            ORDER BY (stock <= min_stock) DESC, stock ASC
            LIMIT 15
            """
        ).fetchall()

        return jsonify({
            "days": days,
            "orders_count": int(ord_stat["cnt"] or 0),
            "revenue": rev,
            "food_cost": food_cost,
            "food_cost_pct": food_cost_pct,
            "payroll_hours": payroll_hours,
            "payroll_courier": payroll_courier,
            "total_payroll": total_payroll,
            "fot_pct": fot_pct,
            "other_expenses": other_expenses,
            "net_profit": net_profit,
            "margin_pct": margin_pct,
            "abc_items": abc_list[:15],
            "ingredients": [dict(ix) for ix in low_stock]
        })

    @app.route("/api/erp/quick_writeoff", methods=["POST"])
    def api_erp_quick_writeoff():
        if session.get("role") not in ("admin", "cashier", "kitchen"):
            return jsonify({"error": "Доступ запрещён"}), 403

        data = request.get_json(force=True, silent=True) or {}
        ing_id = int(data.get("ingredient_id", 0) or 0)
        qty = float(data.get("qty", 0) or 0)
        reason = (data.get("reason") or "Питание персонала").strip()

        if ing_id <= 0 or qty <= 0:
            return jsonify({"error": "Укажите сырьё и количество > 0"}), 400

        db = get_db()
        ing = db.execute("SELECT * FROM ingredients WHERE id=?", (ing_id,)).fetchone()
        if not ing:
            return jsonify({"error": "Сырьё не найдено"}), 404

        cost_imp = round(qty * float(ing["cost_price"] or 0), 2)
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")

        db.execute(
            "UPDATE ingredients SET stock = stock - ? WHERE id=?",
            (qty, ing_id)
        )
        db.execute(
            """
            INSERT INTO stock_logs
            (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (now_s, ing_id, ing["name"], -qty, "списание", reason, cost_imp, session.get("username", "admin"))
        )
        db.commit()
        return jsonify({
            "success": True,
            "ing_name": ing["name"],
            "written_off": qty,
            "cost_impact": cost_imp
        })
