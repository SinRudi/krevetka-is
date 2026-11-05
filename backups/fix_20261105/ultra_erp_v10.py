import os
import sqlite3
from datetime import datetime
from flask import request, session, jsonify


def register_ultra_v10(app, g):
    get_db = g["get_db"]
    get_open_shift = g["get_open_shift"]

    @app.route("/api/ultra/kds_batch")
    def api_ultra_kds_batch():
        db = get_db()
        active_orders = db.execute(
            """
            SELECT id, status, created_at, delivery_type, address
            FROM orders
            WHERE status IN ('new', 'cooking')
            ORDER BY id ASC
            """
        ).fetchall()

        batch_rows = db.execute(
            """
            SELECT oi.name, SUM(oi.qty) as total_qty, COUNT(DISTINCT o.id) as orders_cnt
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE o.status IN ('new', 'cooking')
            GROUP BY oi.name
            ORDER BY total_qty DESC, oi.name ASC
            """
        ).fetchall()

        batches = []
        total_portions = 0
        for r in batch_rows:
            q = int(r["total_qty"] or 0)
            total_portions += q
            batches.append({
                "name": r["name"],
                "qty": q,
                "orders_cnt": int(r["orders_cnt"] or 1)
            })

        # Расчёт времени отдачи (SLA) в зависимости от очереди на кухне
        active_cnt = len(active_orders)
        base_cook_min = 15 + (active_cnt * 6)
        sla_zones = {
            "city_min": base_cook_min + 15,
            "west_south_min": base_cook_min + 25,
            "upper_inta_min": base_cook_min + 35
        }

        latest_new = db.execute(
            """
            SELECT o.id, o.delivery_type, o.address,
                   GROUP_CONCAT(oi.name || ' ' || oi.qty || ' шт', ', ') as items_summary
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.id
            WHERE o.status = 'new'
            GROUP BY o.id
            ORDER BY o.id DESC LIMIT 1
            """
        ).fetchone()

        newest_order = None
        if latest_new:
            newest_order = {
                "id": latest_new["id"],
                "delivery_type": latest_new["delivery_type"] or "доставка",
                "items_summary": latest_new["items_summary"] or ""
            }

        return jsonify({
            "active_orders_count": active_cnt,
            "total_portions": total_portions,
            "batches": batches,
            "sla": sla_zones,
            "newest_order": newest_order
        })

    @app.route("/api/ultra/zreport_and_prep")
    def api_ultra_zreport_and_prep():
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Доступ запрещён"}), 403

        db = get_db()
        today_s = datetime.now().strftime("%Y-%m-%d")
        shift = get_open_shift()
        opening_cash = int(shift["opening_cash"] or 0) if shift else 0

        orders = db.execute(
            """
            SELECT total, cost, payment_method, delivery_type, courier_fee
            FROM orders
            WHERE status != 'cancelled' AND date(created_at) = ?
            """,
            (today_s,)
        ).fetchall()

        cancelled_cnt = db.execute(
            "SELECT COUNT(*) as c FROM orders WHERE status='cancelled' AND date(created_at)=?",
            (today_s,)
        ).fetchone()["c"]

        cash_rev = 0
        card_rev = 0
        total_rev = 0
        total_foodcost = 0
        courier_payouts = 0
        delivery_cnt = 0
        pickup_cnt = 0

        for o in orders:
            t = int(o["total"] or 0)
            total_rev += t
            total_foodcost += int(round(float(o["cost"] or 0)))
            pm = (o["payment_method"] or "").lower()
            if pm in ("наличные", "cash"):
                cash_rev += t
            else:
                card_rev += t

            if (o["delivery_type"] or "доставка").lower() == "самовывоз":
                pickup_cnt += 1
            else:
                delivery_cnt += 1
                courier_payouts += int(o["courier_fee"] or 150)

        staff_row = db.execute(
            """
            SELECT COALESCE(SUM(hourly_pay), 0) as h_pay,
                   COALESCE(SUM(delivery_pay), 0) as d_pay
            FROM staff_shifts
            WHERE date(opened_at) = ?
            """,
            (today_s,)
        ).fetchone()

        hourly_payroll = int(staff_row["h_pay"] or 0)
        courier_payroll = max(int(staff_row["d_pay"] or 0), courier_payouts)

        exp_row = db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as exp
            FROM accounting_expenses
            WHERE date(created_at) = ? AND payment_method = 'наличные'
            """,
            (today_s,)
        ).fetchone()
        cash_expenses = int(exp_row["exp"] or 0)

        expected_drawer_cash = opening_cash + cash_rev - courier_payroll - cash_expenses
        orders_cnt = len(orders)
        avg_check = int(round(total_rev / orders_cnt)) if orders_cnt > 0 else 0
        day_net_profit = total_rev - total_foodcost - hourly_payroll - courier_payroll - cash_expenses

        # Формируем список авто-закупа и утренних заготовок
        ing_rows = db.execute(
            """
            SELECT id, name, stock, unit, min_stock, cost_price
            FROM ingredients
            ORDER BY (stock <= min_stock) DESC, name ASC
            """
        ).fetchall()

        procurement = []
        for ir in ing_rows:
            st = round(float(ir["stock"] or 0), 2)
            ms = round(float(ir["min_stock"] or 1), 2)
            cp = float(ir["cost_price"] or 0)
            if st <= ms * 1.3:
                need_qty = round(max(ms * 2.5 - st, ms), 2)
                procurement.append({
                    "name": ir["name"],
                    "stock": st,
                    "min_stock": ms,
                    "unit": ir["unit"] or "кг",
                    "order_qty": need_qty,
                    "est_cost": int(round(need_qty * cp))
                })

        return jsonify({
            "date": today_s,
            "orders_count": orders_cnt,
            "cancelled_count": int(cancelled_cnt or 0),
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
            "day_net_profit": day_net_profit,
            "procurement": procurement
        })

    @app.route("/api/ultra/recipes_matrix")
    def api_ultra_recipes_matrix():
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Доступ запрещён"}), 403

        db = get_db()
        menu_rows = db.execute(
            "SELECT id, name, category, price, stop_list FROM menu ORDER BY category, name"
        ).fetchall()
        ing_rows = db.execute(
            "SELECT id, name, unit, cost_price, stock FROM ingredients ORDER BY name"
        ).fetchall()

        items_out = []
        for m in menu_rows:
            recs = db.execute(
                """
                SELECT r.id as rec_id, r.ingredient_id, r.amount,
                       i.name as ing_name, i.unit, i.cost_price
                FROM recipes r
                JOIN ingredients i ON r.ingredient_id = i.id
                WHERE r.menu_id = ?
                """,
                (m["id"],)
            ).fetchall()

            cost_val = 0.0
            comp_list = []
            for rc in recs:
                amt = float(rc["amount"] or 0)
                cp = float(rc["cost_price"] or 0)
                line_cost = round(amt * cp, 2)
                cost_val += line_cost
                comp_list.append({
                    "rec_id": rc["rec_id"],
                    "ing_name": rc["ing_name"],
                    "amount": amt,
                    "unit": rc["unit"] or "кг",
                    "line_cost": line_cost
                })

            price_val = int(m["price"] or 0)
            fc_pct = round((cost_val / price_val * 100), 1) if price_val > 0 else 0.0
            rec_price = int(round(cost_val / 0.28 / 10.0) * 10) if cost_val > 0 else price_val

            items_out.append({
                "id": m["id"],
                "name": m["name"],
                "category": m["category"],
                "price": price_val,
                "cost": round(cost_val, 1),
                "fc_pct": fc_pct,
                "recommended_price": rec_price,
                "recipe": comp_list
            })

        return jsonify({
            "menu_items": items_out,
            "ingredients": [dict(i) for i in ing_rows]
        })

    @app.route("/api/ultra/recipe_save", methods=["POST"])
    def api_ultra_recipe_save():
        if session.get("role") != "admin":
            return jsonify({"error": "Только администратор может менять техкарты"}), 403

        data = request.get_json(force=True, silent=True) or {}
        menu_id = int(data.get("menu_id", 0) or 0)
        ing_id = int(data.get("ingredient_id", 0) or 0)
        amount = float(data.get("amount", 0) or 0)

        if menu_id <= 0 or ing_id <= 0:
            return jsonify({"error": "Выберите блюдо и ингредиент"}), 400

        db = get_db()
        existing = db.execute(
            "SELECT id FROM recipes WHERE menu_id=? AND ingredient_id=?",
            (menu_id, ing_id)
        ).fetchone()

        if amount <= 0:
            if existing:
                db.execute("DELETE FROM recipes WHERE id=?", (existing["id"],))
        else:
            if existing:
                db.execute("UPDATE recipes SET amount=? WHERE id=?", (amount, existing["id"]))
            else:
                db.execute(
                    "INSERT INTO recipes (menu_id, ingredient_id, amount) VALUES (?,?,?)",
                    (menu_id, ing_id, amount)
                )
        db.commit()
        return jsonify({"success": True})

    @app.route("/api/ultra/standardize_8pcs", methods=["POST"])
    def api_ultra_standardize_8pcs():
        if session.get("role") != "admin":
            return jsonify({"error": "Доступ только для администратора"}), 403

        db = get_db()
        rows = db.execute("SELECT id, name, description FROM menu").fetchall()
        updated = 0
        for r in rows:
            new_name = (r["name"] or "").replace("10 шт", "8 шт").replace("10 кусочков", "8 кусочков")
            new_desc = (r["description"] or "").replace("10 шт", "8 шт").replace("10 кусочков", "8 кусочков")
            if new_name != (r["name"] or "") or new_desc != (r["description"] or ""):
                db.execute(
                    "UPDATE menu SET name=?, description=? WHERE id=?",
                    (new_name, new_desc, r["id"])
                )
                updated += 1
        db.commit()
        return jsonify({"success": True, "updated_count": updated})
