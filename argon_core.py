import os
import re
import time
import socket
import sqlite3
import subprocess
from datetime import datetime, timedelta
from flask import request, session, render_template, redirect, url_for, jsonify


def get_local_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.0.73"


def register_all(app, g):
    get_db = g["get_db"]
    get_open_shift = g["get_open_shift"]
    get_setting = g["get_setting"]
    check_and_apply_autostop = g["check_and_apply_autostop"]
    admin_only = g["admin_only"]
    is_shop_open = g.get("is_shop_open")
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Разрешаем /api/detect_zone без авторизации для клиентской витрины /site
    @app.before_request
    def allow_public_detect_zone():
        if request.path in ("/api/detect_zone",):
            return None

    def recheck_autostop_all(db):
        """Снимает авто-стоп с позиций, если сырьё вернулось на склад, и ставит при нехватке."""
        check_and_apply_autostop(db)
        rows = db.execute("""
            SELECT m.id FROM menu m
            WHERE m.stop_list = 1
              AND EXISTS (SELECT 1 FROM recipes r WHERE r.menu_id = m.id)
              AND NOT EXISTS (
                  SELECT 1 FROM recipes r
                  JOIN ingredients i ON r.ingredient_id = i.id
                  WHERE r.menu_id = m.id AND i.stock < r.amount
              )
        """).fetchall()
        for r in rows:
            db.execute("UPDATE menu SET stop_list = 0 WHERE id = ?", (r["id"],))

    def restore_order_ingredients(db, order_id, reason_label="Возврат сырья"):
        if not order_id:
            return
        logs = db.execute("""
            SELECT ingredient_id, ing_name, change_amount, cost_impact
            FROM stock_logs
            WHERE order_id=? AND op_type='продажа'
        """, (order_id,)).fetchall()
        if not logs:
            return
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
        for lg in logs:
            returned_qty = abs(float(lg["change_amount"] or 0))
            if returned_qty > 0 and lg["ingredient_id"]:
                db.execute("UPDATE ingredients SET stock = stock + ? WHERE id=?", (returned_qty, lg["ingredient_id"]))
                db.execute("""
                    INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username, order_id)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (now_s, lg["ingredient_id"], lg["ing_name"], returned_qty, "возврат", reason_label, -abs(float(lg["cost_impact"] or 0)), "system", order_id))
        db.execute("UPDATE stock_logs SET op_type='продажа_архив' WHERE order_id=? AND op_type='продажа'", (order_id,))
        recheck_autostop_all(db)

    def deduct_ingredients_and_calc_cost(db, items, order_id=None):
        total_cost = 0.0
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
        for i in items:
            m_id = i.get("id") or i.get("menu_id")
            qty = int(i.get("qty", 1))
            if not m_id:
                continue
            recipes = db.execute("""
                SELECT r.ingredient_id, r.amount, i.name, i.stock, i.cost_price
                FROM recipes r JOIN ingredients i ON r.ingredient_id = i.id
                WHERE r.menu_id=?
            """, (m_id,)).fetchall()
            if recipes:
                for r in recipes:
                    needed = float(r["amount"]) * qty
                    c_price = float(r["cost_price"] or 0)
                    item_c = needed * c_price
                    total_cost += item_c
                    db.execute("UPDATE ingredients SET stock = stock - ? WHERE id=?", (needed, r["ingredient_id"]))
                    db.execute("""
                        INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username, order_id)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (now_s, r["ingredient_id"], r["name"], -needed, "продажа", f"Заказ #{order_id or 'новый'}", item_c, "system", order_id))
        recheck_autostop_all(db)
        return round(total_cost, 2)

    g["deduct_ingredients_and_calc_cost"] = deduct_ingredients_and_calc_cost
    g["restore_order_ingredients"] = restore_order_ingredients

    def calc_courier_fee_for_order(db, address="", delivery_type="доставка", delivery_zone="", courier_user_id=None):
        if (delivery_type or "доставка").lower() == "самовывоз":
            return 0, "pickup"

        city_rate = 150
        distant_rate = 250
        if courier_user_id:
            u = db.execute("SELECT courier_city_rate, courier_distant_rate FROM users WHERE id=?", (courier_user_id,)).fetchone()
            if u:
                city_rate = int(u["courier_city_rate"] or 150)
                distant_rate = int(u["courier_distant_rate"] or 250)
        else:
            u_def = db.execute("SELECT courier_city_rate, courier_distant_rate FROM users WHERE role='courier' ORDER BY id LIMIT 1").fetchone()
            if u_def:
                city_rate = int(u_def["courier_city_rate"] or 150)
                distant_rate = int(u_def["courier_distant_rate"] or 250)

        addr_low = ((address or "") + " " + (delivery_zone or "")).lower()

        zones = db.execute("SELECT name, courier_payout, is_distant, streets_keywords FROM delivery_zones WHERE is_active=1 ORDER BY is_distant DESC, id").fetchall()
        for z in zones:
            z_name = (z["name"] or "").lower().strip()
            z_short = z_name.split("(")[0].strip()
            kw_list = [k.strip() for k in (z["streets_keywords"] or "").lower().split(",") if k.strip()]
            if (z_name and z_name in addr_low) or (z_short and len(z_short) > 3 and z_short in addr_low) or any(k in addr_low for k in kw_list):
                payout = int(z["courier_payout"] or (distant_rate if z["is_distant"] else city_rate))
                return payout, ("distant" if z["is_distant"] else "city")

        distant_keywords = ("верхн", "станц", "вокзал", "южн", "запад", "сельхоз", "шахт", "лазур", "восточ", "депо", "поселок", "посёлок", "дальн", "юсьтыдор", "кирова", "чайковск", "заречн", "геолог")
        if any(k in addr_low for k in distant_keywords):
            return distant_rate, "distant"

        return city_rate, "city"

    def resolve_order_items(db, items, allow_custom_price=False, allow_missing=False,
                            existing_order_id=None):
        """Берём название и цену из меню, а не из запроса клиента.

        allow_custom_price разрешает ручную цену только сотрудникам с правом скидки.
        allow_missing оставляет возможность редактировать старые заказы с удалёнными блюдами.
        """
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError("Некорректный состав заказа")
        resolved = []
        subtotal = 0
        for it in items:
            if not isinstance(it, dict):
                raise ValueError("Некорректная позиция")
            try:
                m_id = int(it.get("id") or it.get("menu_id") or 0)
                qty = int(it.get("qty", 1))
            except (TypeError, ValueError):
                raise ValueError("Некорректная позиция")
            if not 1 <= qty <= 99:
                raise ValueError("Некорректное количество")
            row = db.execute(
                "SELECT id, name, price, available, stop_list FROM menu WHERE id=?",
                (m_id,)).fetchone() if m_id else None
            if row is None:
                # Блюдо могло быть удалено из меню. Для редактирования старого
                # заказа берём название и цену из уже сохранённых позиций, а не
                # из запроса клиента.
                old = None
                if allow_missing and existing_order_id and m_id:
                    old = db.execute(
                        "SELECT name, price FROM order_items WHERE order_id=? AND menu_id=? LIMIT 1",
                        (existing_order_id, m_id)).fetchone()
                if old is None:
                    raise ValueError("Блюдо не найдено в меню")
                name = old["name"]
                price = int(old["price"] or 0)
            else:
                if not int(row["available"] or 0) or int(row["stop_list"] or 0):
                    raise ValueError(f"«{row['name']}» сейчас недоступно")
                name = row["name"]
                price = int(row["price"] or 0)
                if allow_custom_price and it.get("price") not in (None, ""):
                    try:
                        custom = int(it.get("price"))
                    except (TypeError, ValueError):
                        custom = price
                    if 0 <= custom <= 100000:
                        price = custom
            mods = str(it.get("mods") or "")[:200]
            resolved.append({"id": (row["id"] if row is not None else m_id), "name": name, "price": price,
                             "qty": qty, "mods": mods})
            subtotal += price * qty
        return resolved, subtotal

    def normal_delivery_fee(db, delivery_type, requested, zone_id=None):
        if (delivery_type or "доставка").lower() == "самовывоз":
            return 0
        # Если клиент передал ID района — берём тариф строго из БД.
        if zone_id not in (None, "", 0):
            try:
                zone = db.execute(
                    "SELECT fee FROM delivery_zones WHERE id=? AND is_active=1",
                    (int(zone_id),)).fetchone()
            except (TypeError, ValueError):
                zone = None
            if zone is not None:
                return int(zone["fee"] or 0)
        fees = {int(z["fee"] or 0) for z in db.execute(
            "SELECT fee FROM delivery_zones WHERE is_active=1").fetchall()}
        if not fees:
            fees = {0, 150}
        try:
            requested = int(requested or 0)
        except (TypeError, ValueError):
            requested = min(fees)
        # Разрешаем только реально существующий тариф, ближайший к выбранному.
        return min(fees, key=lambda f: abs(f - requested))

    def ensure_personal_shift_open(db, user_row):
        uid = user_row["id"]
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        today_prefix = now_dt.strftime("%Y-%m-%d")

        # Автоматически закрываем забытые смены за прошлые дни (с лимитом 12 часов), чтобы не набегали сутки
        old_open = db.execute("SELECT * FROM staff_shifts WHERE user_id=? AND status='open'", (uid,)).fetchall()
        for os_row in old_open:
            if not (os_row["opened_at"] or "").startswith(today_prefix):
                try:
                    t1 = datetime.strptime(os_row["opened_at"][:19], "%Y-%m-%d %H:%M:%S")
                    capped_close = (t1 + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    capped_close = now_str
                db.execute("UPDATE staff_shifts SET status='closed', closed_at=? WHERE id=?", (capped_close, os_row["id"]))
        db.commit()

        active = db.execute("SELECT * FROM staff_shifts WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        if not active:
            hr = 0.0 if user_row["role"] == "courier" else float(user_row["hourly_rate"] or 0)
            db.execute("""
                INSERT INTO staff_shifts (user_id, username, role, opened_at, status, hourly_rate, hours_worked, hourly_pay, orders_delivered, delivery_pay, total_pay)
                VALUES (?,?,?,?, 'open', ?, 0, 0, 0, 0, 0)
            """, (uid, user_row["username"], user_row["role"], now_str, hr))
            db.commit()
            active = db.execute("SELECT * FROM staff_shifts WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (uid,)).fetchone()

        if user_row["role"] in ("admin", "cashier") and not get_open_shift():
            db.execute("INSERT INTO shifts (opened_at, opened_by, status, opening_cash, expected_cash) VALUES (?,?, 'open', 0, 0)", (now_str, uid))
            db.commit()
        return active

    def refresh_personal_shift_Calculation(db, shift_row):
        if not shift_row:
            return None
        ss_id = shift_row["id"]
        uid = shift_row["user_id"]
        opened_at = shift_row["opened_at"]
        end_str = shift_row["closed_at"] if shift_row["status"] == "closed" and shift_row["closed_at"] else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if shift_row["manual_hours"] is not None:
            hours = round(float(shift_row["manual_hours"]), 2)
        else:
            try:
                t1 = datetime.strptime(opened_at[:19], "%Y-%m-%d %H:%M:%S")
                t2 = datetime.strptime(end_str[:19], "%Y-%m-%d %H:%M:%S")
                raw_hours = max(0.0, (t2 - t1).total_seconds() / 3600.0)
                # Защита от забытой открытой смены: максимум 14 часов авто-расчёта
                hours = round(min(raw_hours, 14.0), 2)
            except Exception:
                hours = 0.0

        user = db.execute("SELECT hourly_rate, role FROM users WHERE id=?", (uid,)).fetchone()
        role = user["role"] if user else shift_row["role"]

        if role == "courier":
            hr = 0.0
            hourly_pay = 0
            # Считаем сколько курьеров сейчас на открытой смене
            active_couriers = db.execute("SELECT COUNT(*) c FROM staff_shifts WHERE role='courier' AND status='open'").fetchone()["c"]
            if active_couriers <= 1:
                deliv_rows = db.execute("""
                    SELECT COALESCE(SUM(CASE WHEN courier_fee > 0 THEN courier_fee ELSE 150 END), 0) s, COUNT(*) c
                    FROM orders
                    WHERE status IN ('delivering', 'done')
                      AND delivery_type='доставка'
                      AND created_at >= ?
                      AND (courier_id=? OR courier_id IS NULL)
                """, (opened_at[:10], uid)).fetchone()
            else:
                deliv_rows = db.execute("""
                    SELECT COALESCE(SUM(CASE WHEN courier_fee > 0 THEN courier_fee ELSE 150 END), 0) s, COUNT(*) c
                    FROM orders
                    WHERE status IN ('delivering', 'done')
                      AND delivery_type='доставка'
                      AND created_at >= ?
                      AND courier_id=?
                """, (opened_at[:10], uid)).fetchone()
            orders_cnt = int(deliv_rows["c"] or 0)
            delivery_pay = int(deliv_rows["s"] or 0)
        else:
            hr = float(user["hourly_rate"] if user else (shift_row["hourly_rate"] or 0))
            hourly_pay = int(round(hours * hr))
            orders_cnt = 0
            delivery_pay = 0

        total_pay = hourly_pay + delivery_pay
        db.execute("""
            UPDATE staff_shifts
            SET role=?, hourly_rate=?, hours_worked=?, hourly_pay=?, orders_delivered=?, delivery_pay=?, total_pay=?
            WHERE id=?
        """, (role, hr, hours, hourly_pay, orders_cnt, delivery_pay, total_pay, ss_id))
        db.commit()
        return {
            "id": ss_id,
            "role": role,
            "opened_at": opened_at[11:16],
            "hours": hours,
            "hourly_rate": int(hr),
            "hourly_pay": hourly_pay,
            "orders_delivered": orders_cnt,
            "delivery_pay": delivery_pay,
            "total_pay": total_pay
        }

    # --- 1. БЕЗОПАСНЫЙ ВХОД ПО ПИН-КОДУ (НЕ БЛОКИРУЕТ ЛОКАЛЬНУЮ КАССУ ИЗ-ЗА 4G ТУННЕЛЯ) ---
    def argon_login():
        error = None
        fwd_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        remote_ip = request.remote_addr or "127.0.0.1"
        ua = (request.headers.get("User-Agent", "") or "")[:40]
        is_local_lan = (not fwd_ip) and (remote_ip in ("127.0.0.1", "::1") or remote_ip.startswith("192.168."))
        client_key = f"LAN_{remote_ip}_{ua}" if is_local_lan else f"EXT_{fwd_ip or remote_ip}_{ua}"
        max_attempts = 10 if is_local_lan else 5
        now_ts = time.time()

        db = get_db()
        sec_row = db.execute("SELECT * FROM pin_security_logs WHERE client_key=?", (client_key,)).fetchone()
        if sec_row and now_ts < (sec_row["locked_until"] or 0):
            wait_sec = int(sec_row["locked_until"] - now_ts)
            return render_template("login.html", error=f"Слишком много неверных попыток. Подождите {wait_sec} сек.")

        if request.method == "POST":
            pin = (request.form.get("pin_code") or request.form.get("password") or "").strip()
            if not (pin.isdigit() and 4 <= len(pin) <= 6):
                error = "ПИН-код должен состоять из 4–6 цифр"
            else:
                user = db.execute("SELECT * FROM users WHERE pin_code=? AND is_active=1", (pin,)).fetchone()
                if user:
                    db.execute("DELETE FROM pin_security_logs WHERE client_key=?", (client_key,))
                    db.commit()
                    session["user_id"] = user["id"]
                    session["username"] = user["username"]
                    session["role"] = user["role"]
                    session["can_edit_menu"] = int(user["can_edit_menu"] or 0)
                    session["can_give_discount"] = int(user["can_give_discount"] or 0)
                    session["can_view_finance"] = int(user["can_view_finance"] or 0)

                    ensure_personal_shift_open(db, user)

                    if user["role"] == "kitchen":
                        return redirect(url_for("kitchen"))
                    elif user["role"] == "courier":
                        return redirect(url_for("courier"))
                    return redirect(url_for("index"))
                else:
                    fails = (sec_row["fail_count"] + 1) if sec_row else 1
                    locked_until = (now_ts + 60) if fails >= max_attempts else 0
                    db.execute("""
                        INSERT INTO pin_security_logs (client_key, fail_count, locked_until, last_attempt)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(client_key) DO UPDATE SET
                            fail_count=?, locked_until=?, last_attempt=?
                    """, (client_key, fails, locked_until, now_ts, fails, locked_until, now_ts))
                    db.commit()
                    if fails >= max_attempts:
                        error = "Терминал заблокирован на 60 сек. после неверных попыток"
                    else:
                        error = f"Неверный ПИН-код (осталось попыток: {max_attempts - fails})"
        return render_template("login.html", error=error)

    app.view_functions["login"] = argon_login

    # --- 2. РОЛЬ И ДАННЫЕ ЛИЧНОЙ СМЕНЫ В ВЕРХНЕЙ ПАНЕЛИ ---
    def argon_api_current_role():
        db = get_db()
        uid = session.get("user_id")
        ps_data = None
        if uid:
            u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if u:
                active_ss = ensure_personal_shift_open(db, u)
                ps_data = refresh_personal_shift_Calculation(db, active_ss)
        return jsonify({
            "role": session.get("role", "admin"),
            "username": session.get("username", "Администратор"),
            "can_edit_menu": session.get("can_edit_menu", 1),
            "can_give_discount": session.get("can_give_discount", 1),
            "can_view_finance": session.get("can_view_finance", 1),
            "personal_shift": ps_data
        })

    if "api_current_role" in app.view_functions:
        app.view_functions["api_current_role"] = argon_api_current_role
    else:
        app.add_url_rule("/api/current_role", "api_current_role", argon_api_current_role)

    # --- 3. ЧЕСТНЫЙ ТАЙМЕР ГОТОВКИ НА КУХНЕ ---
    def argon_live_metrics():
        db = get_db()
        shift = get_open_shift()
        shift_rev = 0
        if shift:
            r = db.execute("SELECT COALESCE(SUM(total),0) s FROM orders WHERE shift_id=? AND status!='cancelled'", (shift["id"],)).fetchone()
            shift_rev = int(r["s"] or 0)
        active_kds = db.execute("SELECT COUNT(*) c FROM orders WHERE status IN ('new','cooking')").fetchone()["c"]

        timed_rows = db.execute("""
            SELECT cook_start_time, cook_end_time FROM orders
            WHERE cook_start_time IS NOT NULL AND cook_end_time IS NOT NULL
              AND cook_start_time != '' AND cook_end_time != ''
            ORDER BY id DESC LIMIT 30
        """).fetchall()
        durations = []
        for tr in timed_rows:
            try:
                t1 = datetime.strptime(tr["cook_start_time"][:19], "%Y-%m-%d %H:%M:%S")
                t2 = datetime.strptime(tr["cook_end_time"][:19], "%Y-%m-%d %H:%M:%S")
                sec = (t2 - t1).total_seconds()
                if 10 <= sec <= 7200:
                    durations.append(sec)
            except Exception:
                pass
        avg_cook_str = f"{int(sum(durations)/len(durations)) // 60:02d}:{int(sum(durations)/len(durations)) % 60:02d}" if durations else "00:00"
        return jsonify({"shift_revenue": shift_rev, "active_kds": active_kds, "avg_cook_time": avg_cook_str})

    if "api_erp_live_metrics" in app.view_functions:
        app.view_functions["api_erp_live_metrics"] = argon_live_metrics
    else:
        app.add_url_rule("/api/erp/live_metrics", "api_erp_live_metrics", argon_live_metrics)

    # --- 4. СОЗДАНИЕ, РЕДАКТИРОВАНИЕ И СМЕНА СТАТУСА ЗАКАЗА ---
    def argon_public_order():
        data = request.get_json(force=True, silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "Ожидается JSON"}), 400
        items = data.get("items", [])
        if not isinstance(items, list) or not items:
            return jsonify({"error": "Пустой заказ"}), 400

        if callable(is_shop_open) and not is_shop_open():
            return jsonify({"error": "Приём заказов сейчас закрыт. Попробуйте в рабочие часы."}), 409

        db = get_db()
        try:
            resolved, subtotal = resolve_order_items(db, items, allow_custom_price=False)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        promo_code = str(data.get("promo_code") or "").strip().upper()[:40]
        promo_discount = 0
        if promo_code:
            promo = db.execute(
                "SELECT * FROM promocodes WHERE code=? AND is_active=1", (promo_code,)).fetchone()
            if promo:
                if promo["discount_type"] == "percent":
                    promo_discount = (subtotal * int(promo["discount_value"] or 0)) // 100
                else:
                    promo_discount = int(promo["discount_value"] or 0)
                promo_discount = max(0, min(promo_discount, subtotal))

        delivery_type = str(data.get("delivery_type") or "доставка").strip().lower()
        if delivery_type not in ("доставка", "самовывоз"):
            delivery_type = "доставка"
        delivery_price = normal_delivery_fee(db, delivery_type, data.get("delivery_price", 0),
                                             data.get("delivery_zone_id"))
        total = max(0, subtotal - promo_discount) + delivery_price

        phone = str(data.get("phone") or "").strip()[:30]
        address = "Самовывоз" if delivery_type == "самовывоз" else str(data.get("address") or "").strip()[:300]
        comment = str(data.get("comment") or "").strip()[:500]
        if len("".join(ch for ch in phone if ch.isdigit())) < 6:
            return jsonify({"error": "Укажите корректный телефон"}), 400
        if delivery_type == "доставка" and len(address) < 5:
            return jsonify({"error": "Укажите адрес доставки"}), 400

        pay_method = str(data.get("payment_method") or "карта").strip().lower()
        if pay_method not in ("карта", "наличные", "перевод", "микс", "card", "cash"):
            pay_method = "карта"
        try:
            change_from = max(0, min(int(data.get("change_from", 0) or 0), 1000000))
        except (TypeError, ValueError):
            change_from = 0

        shift = get_open_shift()
        shift_id = shift["id"] if shift else None
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        auto_fiscal = 0 if pay_method in ("наличные", "cash") else 1
        c_fee, z_type = calc_courier_fee_for_order(
            db, address, delivery_type, data.get("delivery_zone", ""))

        cur = db.execute("""
            INSERT INTO orders (created_at, status, total, cost, address, phone, comment, shift_id,
                                payment_method, change_from, delivery_type, delivery_price, promo_code, source, payment_status, paid_at, is_fiscal, courier_fee, zone_type)
            VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?,'Сайт','paid',?,?,?,?)
        """, (now_str, "new", total, address, phone, comment, shift_id, pay_method,
              change_from, delivery_type, delivery_price, promo_code, now_str, auto_fiscal,
              c_fee, z_type))
        order_id = cur.lastrowid

        for i in resolved:
            db.execute(
                "INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                (order_id, i["id"], i["name"], i["price"], i["qty"], i["mods"]))

        total_cost = deduct_ingredients_and_calc_cost(db, resolved, order_id)
        db.execute("UPDATE orders SET cost=? WHERE id=?", (total_cost, order_id))
        if phone:
            db.execute("""
                INSERT INTO clients (phone, total_spent, orders_count, last_order_at, level, bonuses)
                VALUES (?,?,1,?,'bronze',0)
                ON CONFLICT(phone) DO UPDATE SET total_spent=total_spent+?, orders_count=orders_count+1, last_order_at=?
            """, (phone, total, now_str, total, now_str))
        db.commit()
        return jsonify({"success": True, "order_id": order_id, "total": total,
                        "courier_fee": c_fee, "zone_type": z_type})

    app.view_functions["public_order"] = argon_public_order

    def argon_create_order():
        data = request.get_json(force=True, silent=True) or {}
        items = data.get("items", [])
        if not isinstance(items, list) or not items:
            return jsonify({"error": "Пустой заказ"}), 400
        db = get_db()
        try:
            resolved, subtotal = resolve_order_items(db, items, allow_custom_price=False)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        shift = get_open_shift()
        if not shift:
            now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur_s = db.execute("INSERT INTO shifts (opened_at, opened_by, status, opening_cash, expected_cash) VALUES (?,?, 'open', 0, 0)", (now_s, session.get("user_id", 1)))
            db.commit()
            shift_id = cur_s.lastrowid
        else:
            shift_id = shift["id"]

        phone = str(data.get("phone") or "").strip()[:30]
        address = str(data.get("address") or "").strip()[:300]
        try:
            discount = max(0, int(data.get("discount", 0) or 0))
        except (TypeError, ValueError):
            discount = 0
        manual_discount = (subtotal * discount // 100) if data.get("discount_type") == "percent" else discount
        after_disc = max(0, subtotal - manual_discount)
        delivery_type = str(data.get("delivery_type") or "доставка").strip().lower()
        if delivery_type not in ("доставка", "самовывоз"):
            delivery_type = "доставка"
        requested_fee = data.get("delivery_price",
                                150 if (delivery_type == "доставка" and 0 < after_disc < 1200) else 0)
        delivery_price = normal_delivery_fee(db, delivery_type, requested_fee,
                                             data.get("delivery_zone_id"))
        total = after_disc + delivery_price

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pm_val = str(data.get("payment_method") or "карта").strip().lower()
        if pm_val not in ("карта", "наличные", "перевод", "микс", "card", "cash"):
            pm_val = "карта"
        auto_fiscal = 0 if pm_val in ("наличные", "cash") else 1
        c_fee, z_type = calc_courier_fee_for_order(db, address, delivery_type, data.get("delivery_zone", ""))

        cur = db.execute("""
            INSERT INTO orders (created_at, status, total, cost, address, phone, comment, shift_id, cashier_id, source, payment_method, delivery_type, delivery_price, scheduled_time, payment_status, paid_at, is_fiscal, courier_fee, zone_type)
            VALUES (?,?,?,0,?,?,?,?,?,'Касса',?,?,?,?, 'paid',?,?,?,?)
        """, (now_str, "new", total, address, phone, str(data.get("comment") or "")[:500],
              shift_id, session.get("user_id", 1), pm_val, delivery_type, delivery_price,
              str(data.get("scheduled_time") or "")[:40], now_str, auto_fiscal, c_fee, z_type))
        order_id = cur.lastrowid

        for i in resolved:
            db.execute(
                "INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                (order_id, i["id"], i["name"], i["price"], i["qty"], i["mods"]))

        total_cost = deduct_ingredients_and_calc_cost(db, resolved, order_id)
        db.execute("UPDATE orders SET cost=? WHERE id=?", (total_cost, order_id))
        if phone:
            db.execute("""
                INSERT INTO clients (phone, total_spent, orders_count, last_order_at, level, bonuses)
                VALUES (?,?,1,?,'bronze',0)
                ON CONFLICT(phone) DO UPDATE SET total_spent=total_spent+?, orders_count=orders_count+1, last_order_at=?
            """, (phone, total, now_str, total, now_str))
        db.commit()
        return jsonify({"success": True, "order_id": order_id, "total": total,
                        "courier_fee": c_fee, "zone_type": z_type})

    app.view_functions["create_order"] = argon_create_order

    def argon_update_order_items(order_id):
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Доступно только кассиру или администратору"}), 403
        data = request.get_json(force=True, silent=True) or {}
        new_items = data.get("items", [])
        if not new_items:
            return jsonify({"error": "В заказе должна остаться хотя бы одна позиция"}), 400
        db = get_db()
        restore_order_ingredients(db, order_id, f"Пересчёт состава заказа #{order_id}")
        try:
            resolved, new_total = resolve_order_items(
                db, new_items, allow_custom_price=False, allow_missing=True,
                existing_order_id=order_id)
        except ValueError as e:
            db.rollback()
            return jsonify({"error": str(e)}), 400
        db.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
        for i in resolved:
            db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                       (order_id, i["id"], i["name"], i["price"], i["qty"], i["mods"]))
        new_cost = deduct_ingredients_and_calc_cost(db, resolved, order_id)
        db.execute("UPDATE orders SET total=?, cost=? WHERE id=?", (new_total, new_cost, order_id))
        db.commit()
        return jsonify({"success": True, "new_total": new_total})

    app.view_functions["update_order_items"] = argon_update_order_items

    def argon_set_status(order_id):
        data = request.get_json(force=True, silent=True) or {}
        new_status = data.get("status")
        if not new_status:
            return jsonify({"error": "Статус не указан"}), 400
        db = get_db()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            old_row = db.execute("SELECT status, address, delivery_type, delivery_zone, courier_id, courier_fee FROM orders WHERE id=?", (order_id,)).fetchone()
            old_status = old_row["status"] if old_row else ""
            if new_status == "cancelled" and old_status != "cancelled":
                restore_order_ingredients(db, order_id, f"Отмена заказа #{order_id}")

            if new_status in ("delivering", "done") and old_row and (old_row["delivery_type"] or "доставка") == "доставка":
                cur_uid = session.get("user_id") if session.get("role") == "courier" else (old_row["courier_id"] or None)
                if not cur_uid:
                    first_c = db.execute("SELECT user_id FROM staff_shifts WHERE role='courier' AND status='open' ORDER BY id DESC LIMIT 1").fetchone()
                    if first_c:
                        cur_uid = first_c["user_id"]
                c_fee, z_type = calc_courier_fee_for_order(db, old_row["address"], old_row["delivery_type"], old_row["delivery_zone"], cur_uid)
                c_name = session.get("username", "Курьер") if session.get("role") == "courier" else ""
                db.execute("""
                    UPDATE orders
                    SET courier_id=COALESCE(?, courier_id),
                        courier_name=CASE WHEN ?!='' THEN ? ELSE courier_name END,
                        courier_fee=?, zone_type=?
                    WHERE id=?
                """, (cur_uid, c_name, c_name, c_fee, z_type, order_id))

            if new_status == "cooking":
                db.execute("UPDATE orders SET status=?, cook_start_time=COALESCE(cook_start_time, ?) WHERE id=?", (new_status, now_str, order_id))
            elif new_status in ("ready", "done"):
                db.execute("UPDATE orders SET status=?, cook_end_time=COALESCE(cook_end_time, ?) WHERE id=?", (new_status, now_str, order_id))
            else:
                db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))

            db.execute("INSERT INTO order_status_history (order_id, old_status, new_status, changed_at, comment) VALUES (?,?,?,?,?)",
                       (order_id, old_status, new_status, now_str, "Обновлено"))
            db.commit()
            return jsonify({"success": True, "status": new_status})
        except Exception as e:
            db.rollback()
            return jsonify({"success": False, "error": str(e)}), 500

    app.view_functions["set_status"] = argon_set_status

    # --- 5. ПАНЕЛЬ АДМИНИСТРАТОРА, РЕДАКТИРОВАНИЕ СМЕН И ЗОН КУРЬЕРОВ ---
    def argon_admin_panel():
        db = get_db()
        stats = db.execute("SELECT COUNT(*) cnt, COALESCE(SUM(total), 0) rev FROM orders WHERE status != 'cancelled'").fetchone()
        avg_check = (stats["rev"] / stats["cnt"]) if stats["cnt"] > 0 else 0
        chart_data = []
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            r = db.execute("SELECT COALESCE(SUM(total),0) rev FROM orders WHERE date(created_at)=? AND status!='cancelled'", (d,)).fetchone()
            chart_data.append({"date": d[5:], "rev": r["rev"]})

        open_ss = db.execute("SELECT * FROM staff_shifts WHERE status='open'").fetchall()
        for s_row in open_ss:
            refresh_personal_shift_Calculation(db, s_row)

        staff_shifts = db.execute("SELECT * FROM staff_shifts ORDER BY id DESC LIMIT 25").fetchall()
        active_staff_shifts = [s for s in staff_shifts if s["status"] == "open"]

        missing_recipes = db.execute("""
            SELECT name FROM menu m
            WHERE NOT EXISTS (SELECT 1 FROM recipes r WHERE r.menu_id = m.id)
        """).fetchall()

        # Доп. данные для обновлённой админки (сводка): топ позиций, последние заказы, «в работе»
        top_items = db.execute("""
            SELECT oi.name, SUM(oi.qty) AS qty, SUM(oi.qty * oi.price) AS rev
            FROM order_items oi JOIN orders o ON oi.order_id = o.id
            WHERE o.status != 'cancelled' AND date(o.created_at) >= date('now', '-30 day')
            GROUP BY oi.name ORDER BY qty DESC LIMIT 5
        """).fetchall()
        recent_orders = db.execute(
            "SELECT id, created_at, phone, total, status FROM orders ORDER BY id DESC LIMIT 8"
        ).fetchall()
        active_orders_cnt = db.execute(
            "SELECT COUNT(*) c FROM orders WHERE status IN ('new','cooking','ready','delivering')"
        ).fetchone()["c"]

        return render_template(
            "admin.html",
            stats=stats, avg_check=avg_check, chart_data=chart_data,
            chart_max=chart_data and max([d["rev"] for d in chart_data] + [1]) or 1,
            top_items=top_items,
            recent_orders=recent_orders,
            active_orders_cnt=active_orders_cnt,
            menu=db.execute("SELECT * FROM menu ORDER BY sort_weight DESC, category, name").fetchall(),
            users=db.execute("SELECT id, username, role, pin_code, hourly_rate, courier_city_rate, courier_distant_rate, can_edit_menu, can_give_discount, can_view_finance, created_at FROM users ORDER BY id").fetchall(),
            zones=db.execute("SELECT * FROM delivery_zones ORDER BY is_distant, fee").fetchall(),
            promos=db.execute("SELECT * FROM promocodes ORDER BY id DESC").fetchall(),
            staff_shifts=staff_shifts,
            active_staff_shifts=active_staff_shifts,
            missing_recipes=[m["name"] for m in missing_recipes],
            local_ip=get_local_lan_ip(),
            shop_status=get_setting("shop_status", "open")
        )

    app.view_functions["admin_panel"] = admin_only(argon_admin_panel)

    def argon_user_add():
        username = request.form.get("username", "").strip()
        pin_code = request.form.get("pin_code", "").strip()
        role = request.form.get("role", "cashier")
        hourly_rate = 0.0 if role == "courier" else float(request.form.get("hourly_rate", 250) or 0)
        courier_city_rate = int(request.form.get("courier_city_rate", 150) or 150)
        courier_distant_rate = int(request.form.get("courier_distant_rate", 250) or 250)
        can_edit_menu = 1 if (role == "admin" or request.form.get("can_edit_menu") == "1") else 0
        can_give_discount = 1 if (role == "admin" or request.form.get("can_give_discount") == "1") else 0
        can_view_finance = 1 if (role == "admin" or request.form.get("can_view_finance") == "1") else 0

        if not (pin_code.isdigit() and 4 <= len(pin_code) <= 6):
            return redirect(url_for("admin_panel", pin_err="ПИН-код должен содержать от 4 до 6 цифр"))

        db = get_db()
        if db.execute("SELECT id FROM users WHERE pin_code=?", (pin_code,)).fetchone():
            return redirect(url_for("admin_panel", pin_err="Этот ПИН-код уже занят другим сотрудником"))

        if username:
            try:
                db.execute("""
                    INSERT INTO users (username, password_hash, role, created_at, pin_code, hourly_rate, courier_city_rate, courier_distant_rate, can_edit_menu, can_give_discount, can_view_finance)
                    VALUES (?, 'pin-auth', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (username, role, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pin_code, hourly_rate, courier_city_rate, courier_distant_rate, can_edit_menu, can_give_discount, can_view_finance))
                db.commit()
                return redirect(url_for("admin_panel", pin_msg=f"Сотрудник {username} (ПИН: {pin_code}) добавлен"))
            except sqlite3.IntegrityError:
                return redirect(url_for("admin_panel", pin_err="Сотрудник с таким именем уже существует"))
        return redirect(url_for("admin_panel"))

    app.view_functions["admin_user_add"] = admin_only(argon_user_add)

    def argon_user_update(user_id):
        username = request.form.get("username", "").strip()
        pin_code = request.form.get("pin_code", "").strip()
        role = request.form.get("role", "cashier")
        hourly_rate = 0.0 if role == "courier" else float(request.form.get("hourly_rate", 250) or 0)
        courier_city_rate = int(request.form.get("courier_city_rate", 150) or 150)
        courier_distant_rate = int(request.form.get("courier_distant_rate", 250) or 250)
        can_edit_menu = 1 if (role == "admin" or request.form.get("can_edit_menu") == "1") else 0
        can_give_discount = 1 if (role == "admin" or request.form.get("can_give_discount") == "1") else 0
        can_view_finance = 1 if (role == "admin" or request.form.get("can_view_finance") == "1") else 0

        if not (pin_code.isdigit() and 4 <= len(pin_code) <= 6):
            return redirect(url_for("admin_panel", pin_err="ПИН-код должен быть от 4 до 6 цифр"))

        db = get_db()
        if db.execute("SELECT id FROM users WHERE pin_code=? AND id!=?", (pin_code, user_id)).fetchone():
            return redirect(url_for("admin_panel", pin_err="Этот ПИН-код уже назначен другому сотруднику"))

        db.execute("""
            UPDATE users
            SET username=?, pin_code=?, role=?, hourly_rate=?, courier_city_rate=?, courier_distant_rate=?,
                can_edit_menu=?, can_give_discount=?, can_view_finance=?
            WHERE id=?
        """, (username, pin_code, role, hourly_rate, courier_city_rate, courier_distant_rate,
              can_edit_menu, can_give_discount, can_view_finance, user_id))
        db.commit()
        return redirect(url_for("admin_panel", pin_msg=f"Настройки сотрудника {username} сохранены"))

    if "admin_user_update" in app.view_functions:
        app.view_functions["admin_user_update"] = admin_only(argon_user_update)
    else:
        app.add_url_rule("/admin/users/update/<int:user_id>", "admin_user_update", admin_only(argon_user_update), methods=["POST"])

    # --- 6. НОВЫЕ МАРШРУТЫ ТАБЕЛЯ СМЕН, ЗОН, ПЕЧАТИ И 4G-ТУННЕЛЯ ---
    def add_or_replace_rule(rule, endpoint, func, methods=None):
        if endpoint in app.view_functions:
            app.view_functions[endpoint] = func
        else:
            app.add_url_rule(rule, endpoint, func, methods=methods or ["GET"])

    def api_close_my_shift():
        db = get_db()
        uid = session.get("user_id")
        ss = db.execute("SELECT * FROM staff_shifts WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        if not ss:
            return jsonify({"error": "Нет открытой смены"}), 400
        calc = refresh_personal_shift_Calculation(db, ss)
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE staff_shifts SET status='closed', closed_at=? WHERE id=?", (now_s, ss["id"]))
        if calc["total_pay"] > 0:
            db.execute("""
                INSERT INTO accounting_expenses (created_at, category, amount, contour, payment_method, pay_status, comment, username)
                VALUES (?,?,?,?,?,?,?,?)
            """, (now_s[:16], "Зарплата (ФОТ)", calc["total_pay"], "mgmt", "наличные", "paid",
                  f"Смена {ss['username']} ({calc['hours']} ч, заказов: {calc['orders_delivered']})", ss["username"]))
        db.commit()
        return jsonify({"success": True, **calc})

    add_or_replace_rule("/api/staff_shift/close_my", "api_close_my_personal_shift", api_close_my_shift, ["POST"])

    def admin_close_shift(ss_id):
        db = get_db()
        ss = db.execute("SELECT * FROM staff_shifts WHERE id=?", (ss_id,)).fetchone()
        if ss and ss["status"] == "open":
            calc = refresh_personal_shift_Calculation(db, ss)
            now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute("UPDATE staff_shifts SET status='closed', closed_at=? WHERE id=?", (now_s, ss_id))
            if calc["total_pay"] > 0:
                db.execute("""
                    INSERT INTO accounting_expenses (created_at, category, amount, contour, payment_method, pay_status, comment, username)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (now_s[:16], "Зарплата (ФОТ)", calc["total_pay"], "mgmt", "наличные", "paid",
                      f"Закрытие смены: {ss['username']} ({calc['hours']} ч, дост: {calc['orders_delivered']})", session.get("username", "admin")))
            db.commit()
        return redirect(url_for("admin_panel", pin_msg="Смена закрыта и проведена в ФОТ"))

    add_or_replace_rule("/admin/staff_shift/close/<int:ss_id>", "admin_close_staff_shift", admin_only(admin_close_shift), ["POST"])

    def admin_update_shift(ss_id):
        db = get_db()
        ss = db.execute("SELECT * FROM staff_shifts WHERE id=?", (ss_id,)).fetchone()
        if ss:
            if ss["role"] == "courier":
                deliv_pay = int(float(request.form.get("delivery_pay", ss["delivery_pay"]) or 0))
                db.execute("UPDATE staff_shifts SET delivery_pay=?, total_pay=? WHERE id=?", (deliv_pay, deliv_pay, ss_id))
            else:
                m_hours = max(0.0, float(request.form.get("hours_worked", ss["hours_worked"]) or 0))
                h_pay = int(round(m_hours * float(ss["hourly_rate"] or 0)))
                db.execute("UPDATE staff_shifts SET manual_hours=?, hours_worked=?, hourly_pay=?, total_pay=? WHERE id=?",
                           (m_hours, m_hours, h_pay, h_pay, ss_id))
            db.commit()
        return redirect(url_for("admin_panel", pin_msg="Табель смены скорректирован"))

    add_or_replace_rule("/admin/staff_shift/update/<int:ss_id>", "admin_update_staff_shift", admin_only(admin_update_shift), ["POST"])

    def admin_delete_shift(ss_id):
        db = get_db()
        db.execute("DELETE FROM staff_shifts WHERE id=?", (ss_id,))
        db.commit()
        return redirect(url_for("admin_panel", pin_msg="Запись смены удалена из табеля"))

    add_or_replace_rule("/admin/staff_shift/delete/<int:ss_id>", "admin_delete_staff_shift", admin_only(admin_delete_shift), ["POST"])

    def zone_rate_add():
        name = request.form.get("name", "").strip()
        fee = float(request.form.get("fee", 0) or 0)
        courier_payout = int(request.form.get("courier_payout", 150) or 150)
        is_distant = int(request.form.get("is_distant", 0) or 0)
        if name:
            db = get_db()
            db.execute("INSERT INTO delivery_zones (name, fee, color, polygon_coords, is_active, courier_payout, is_distant) VALUES (?,?,?,?,1,?,?)",
                       (name, fee, "#ff6900" if is_distant else "#16a34a", "[]", courier_payout, is_distant))
            db.commit()
        return redirect(url_for("admin_panel", pin_msg=f"Район «{name}» (курьеру: {courier_payout} ₽) добавлен"))

    add_or_replace_rule("/admin/zone_rate/add", "admin_zone_rate_add", admin_only(zone_rate_add), ["POST"])

    def zone_rate_update(zone_id):
        name = request.form.get("name", "").strip()
        fee = float(request.form.get("fee", 0) or 0)
        courier_payout = int(request.form.get("courier_payout", 150) or 150)
        is_distant = int(request.form.get("is_distant", 0) or 0)
        db = get_db()
        db.execute("UPDATE delivery_zones SET name=?, fee=?, courier_payout=?, is_distant=? WHERE id=?",
                   (name, fee, courier_payout, is_distant, zone_id))
        db.commit()
        return redirect(url_for("admin_panel", pin_msg=f"Тариф района «{name}» сохранён"))

    add_or_replace_rule("/admin/zone_rate/update/<int:zone_id>", "admin_zone_rate_update", admin_only(zone_rate_update), ["POST"])

    def zone_rate_delete(zone_id):
        db = get_db()
        db.execute("DELETE FROM delivery_zones WHERE id=?", (zone_id,))
        db.commit()
        return redirect(url_for("admin_panel", pin_msg="Район удалён"))

    add_or_replace_rule("/admin/zone_rate/delete/<int:zone_id>", "admin_zone_rate_delete", admin_only(zone_rate_delete), ["POST"])

    def api_detect_zone():
        address = (request.args.get("address") or "").strip()
        db = get_db()
        addr_low = address.lower()
        zones = db.execute("SELECT * FROM delivery_zones WHERE is_active=1 ORDER BY is_distant DESC, id").fetchall()
        matched_zone = None
        for z in zones:
            kw_raw = (z["streets_keywords"] or "").lower()
            keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
            zname_short = (z["name"] or "").split("(")[0].strip().lower()
            if any(k in addr_low for k in keywords) or (zname_short and zname_short in addr_low):
                matched_zone = z
                break

        if not matched_zone:
            if any(w in addr_low for w in ("вокзал", "станц", "верхн", "железнодор", "депо", "лазур", "юсьтыдор")):
                return jsonify({"zone_name": "Верхняя Инта / Станция", "zone_short": "Верхняя", "client_fee": 350, "courier_fee": 350, "is_distant": True})
            elif any(w in addr_low for w in ("кирова", "чайковск", "южн", "сельхоз", "совхоз", "лугов")):
                return jsonify({"zone_name": "Южный / Сельхоз", "zone_short": "Южный", "client_fee": 200, "courier_fee": 250, "is_distant": True})
            elif any(w in addr_low for w in ("западн", "заречн", "геолог", "шахт", "северн", "тундр")):
                return jsonify({"zone_name": "Западный район", "zone_short": "Западный", "client_fee": 150, "courier_fee": 200, "is_distant": True})
            city_z = db.execute("SELECT * FROM delivery_zones WHERE is_distant=0 ORDER BY id LIMIT 1").fetchone()
            if city_z:
                matched_zone = city_z
            else:
                return jsonify({"zone_name": "Город (Центр)", "zone_short": "Город", "client_fee": 0, "courier_fee": 150, "is_distant": False})

        return jsonify({
            "zone_name": matched_zone["name"],
            "zone_short": matched_zone["name"].split()[0],
            "client_fee": int(matched_zone["fee"] or 0),
            "courier_fee": int(matched_zone["courier_payout"] or (250 if matched_zone["is_distant"] else 150)),
            "is_distant": bool(matched_zone["is_distant"])
        })

    add_or_replace_rule("/api/detect_zone", "api_detect_zone", api_detect_zone, ["GET"])

    def api_print_direct(order_id):
        db = get_db()
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            return jsonify({"error": "Заказ не найден"}), 404
        items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
        sep = "=" * 32
        lines = [
            sep,
            f"   КРЕВЕТКА IS • ЗАКАЗ #{order['id']}",
            f"   {order['created_at']}",
            sep,
        ]
        for it in items:
            lines.append(f"{it['name']} x{it['qty']} = {it['price'] * it['qty']} Р")
        lines.extend([
            "-" * 32,
            f"ИТОГО К ОПЛАТЕ: {order['total']} Р",
            f"Оплата: {order['payment_method']}",
            f"Адрес: {order['address'] or 'Самовывоз'}",
            f"Тел: {order['phone'] or '-'}",
            sep,
            "",
            "",
        ])
        raw_text = chr(10).join(lines)
        for dev_path in ("/dev/usb/lp0", "/dev/usb/lp1", "/dev/lp0"):
            if os.path.exists(dev_path):
                try:
                    with open(dev_path, "wb") as lp:
                        lp.write(raw_text.encode("cp866", errors="replace"))
                    return jsonify({"success": True, "printed_direct": True, "message": f"Отправлено на {dev_path}"})
                except Exception:
                    pass
        return jsonify({"success": True, "printed_direct": False, "message": "Печать через браузерный шлюз"})

    add_or_replace_rule("/api/print/direct/<int:order_id>", "api_print_direct", api_print_direct, ["POST"])

    def api_tunnel_status():
        db = get_db()
        url = ""
        t_log = os.path.join(base_dir, "tunnel.log")
        if os.path.exists(t_log):
            try:
                with open(t_log, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                matches = re.findall(r"(https://[a-zA-Z0-9.-]+\.lhr\.life)", txt)
                if matches:
                    url = matches[-1]
                    db.execute("INSERT INTO settings (key, value) VALUES ('public_tunnel_url', ?) ON CONFLICT(key) DO UPDATE SET value=?", (url, url))
                    db.commit()
            except Exception:
                pass
        if not url:
            url = get_setting("public_tunnel_url", "")
        return jsonify({
            "public_url": url,
            "local_url": f"http://{get_local_lan_ip()}:5000"
        })

    add_or_replace_rule("/api/tunnel/status", "api_tunnel_status", api_tunnel_status, ["GET"])

    def api_tunnel_restart():
        subprocess.run("pkill -9 -f start_4g_tunnel.py 2>/dev/null || true", shell=True)
        subprocess.run("pkill -9 -f 'nokey@localhost.run' 2>/dev/null || true", shell=True)
        t_script = os.path.join(base_dir, "start_4g_tunnel.py")
        t_log = os.path.join(base_dir, "tunnel.log")
        py_exec = os.path.join( os.path.expanduser("~"), "my-apps", "venv", "bin", "python3")
        if not os.path.exists(py_exec):
            py_exec = "python3"
        with open(t_log, "w") as tout:
            subprocess.Popen([py_exec, "-u", t_script], cwd=base_dir, stdout=tout, stderr=tout)
        return jsonify({"success": True})

    add_or_replace_rule("/api/tunnel/restart", "api_tunnel_restart", admin_only(api_tunnel_restart), ["POST"])
