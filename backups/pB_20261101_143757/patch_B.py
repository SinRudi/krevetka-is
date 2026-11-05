#!/usr/bin/env python3
"""Patch B for sushi POS. Usage: python3 patch_B.py <project_root>"""
import os, sys

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')

def patch(rel, pairs):
    path = os.path.join(root, rel)
    with open(path, encoding='utf-8') as f:
        src = f.read()
    for old, new, label in pairs:
        n = src.count(old)
        if n != 1:
            raise SystemExit(f"FAIL {rel}: {label}: expected 1 match, got {n}")
        src = src.replace(old, new, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"OK {rel}: {len(pairs)} changes")

app = []

app.append((
"""app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_FILE = os.path.join(BASE_DIR, '.secret_key')""",
"""app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env_file(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_env_file(os.path.join(BASE_DIR, '.env'))

SECRET_FILE = os.path.join(BASE_DIR, '.secret_key')""",
"load .env"))

app.append((
"""        ('payments', 'cashier_id', 'INTEGER DEFAULT 0'),
        ('payments', 'note', "TEXT DEFAULT ''"),""",
"""        ('payments', 'cashier_id', 'INTEGER DEFAULT 0'),
        ('payments', 'note', "TEXT DEFAULT ''"),
        ('payments', 'paid_at', 'TEXT'),
        ('orders', 'used_bonus_refunded', 'INTEGER DEFAULT 0'),
        ('stock_logs', 'order_id', 'INTEGER'),""",
"B columns"))

app.append((
"""    # Устаревшая колонка users.password хранила копию хеша — очищаем.
    db.execute("UPDATE users SET password='' WHERE password IS NOT NULL AND password != ''")""",
"""    # Устаревшая колонка users.password хранила копию хеша — очищаем.
    db.execute("UPDATE users SET password='' WHERE password IS NOT NULL AND password != ''")

    # P1: фиксируем время фактической оплаты у старых платежей.
    db.execute("UPDATE payments SET paid_at=created_at WHERE paid_at IS NULL AND status IN ('paid','refunded')")

    # P1: история статусов — хотя бы точка создания для старых заказов.
    db.execute(\"\"\"INSERT INTO order_status_history (order_id, old_status, new_status, changed_at, changed_by, comment)
                  SELECT o.id, NULL, 'new', o.created_at, 0, 'backfill: до включения аудита'
                  FROM orders o
                  WHERE NOT EXISTS (SELECT 1 FROM order_status_history h WHERE h.order_id=o.id AND h.new_status='new')\"\"\")

    # P1: старые выданные заказы уже кредитовали клиента — не начисляем повторно.
    db.execute("UPDATE orders SET bonus_awarded=1 WHERE status='done' AND client_credited=1 AND bonus_awarded=0")
    db.execute("UPDATE orders SET used_bonus_refunded=0 WHERE used_bonus_refunded IS NULL")""",
"B backfills"))

app.append((
"""    CREATE TABLE IF NOT EXISTS stock_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, ingredient_id INTEGER, ing_name TEXT, change_amount REAL, op_type TEXT, reason TEXT, cost_impact REAL DEFAULT 0, username TEXT);
    CREATE TABLE IF NOT EXISTS refunds (""",
"""    CREATE TABLE IF NOT EXISTS stock_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, ingredient_id INTEGER, ing_name TEXT, change_amount REAL, op_type TEXT, reason TEXT, cost_impact REAL DEFAULT 0, username TEXT, order_id INTEGER);
    CREATE TABLE IF NOT EXISTS order_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, old_status TEXT,
        new_status TEXT NOT NULL, changed_at TEXT NOT NULL, changed_by INTEGER,
        comment TEXT DEFAULT '', FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_status_history_order ON order_status_history(order_id);
    CREATE TABLE IF NOT EXISTS refunds (""",
"fresh history table"))

app.append((
"""    if direction < 0:
        for ing_id, info in changes.items():
            if info["stock"] < info["amt"]:
                return f"Не хватает на складе: {info['name']} (нужно {round(info['amt'], 2)}, есть {round(info['stock'], 2)})", 0.0

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for ing_id, info in changes.items():
        delta = round(info["amt"] * direction, 4)
        impact = round(delta * info["cost"], 1)
        db.execute("UPDATE ingredients SET stock = ROUND(stock + ?, 4) WHERE id=?", (delta, ing_id))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                   (now_str, ing_id, info['name'], delta, 'продажа' if direction < 0 else 'возврат заказа', f"{reason_prefix} #{order_id}", impact, actor))
        total_cost += info["amt"] * info["cost"]

    return None, round(total_cost, 2)""",
"""    if direction < 0:
        for ing_id, info in changes.items():
            if info["stock"] < info["amt"]:
                return f"Не хватает на складе: {info['name']} (нужно {round(info['amt'], 2)}, есть {round(info['stock'], 2)})", 0.0, False

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for ing_id, info in changes.items():
        delta = round(info["amt"] * direction, 4)
        impact = round(delta * info["cost"], 1)
        db.execute("UPDATE ingredients SET stock = ROUND(stock + ?, 4) WHERE id=?", (delta, ing_id))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username, order_id) VALUES (?,?,?,?,?,?,?,?,?)",
                   (now_str, ing_id, info['name'], delta, 'продажа' if direction < 0 else 'возврат заказа', f"{reason_prefix} #{order_id}", impact, actor, order_id))
        total_cost += info["amt"] * info["cost"]

    return None, round(total_cost, 2), bool(changes)""",
"stock return flag"))

app.append((
"""def record_order_payments(db, order_id, shift_id, payment_method, total, raw_cash=0, cashier_id=0):
    db.execute("DELETE FROM payments WHERE order_id=?", (order_id,))
    pm = (payment_method or 'не указан').strip().lower()
    if pm in ('наличные', 'cash'):
        pay_cash, pay_card = total, 0
    elif pm in ('карта', 'card', 'перевод', 'не указан'):
        pay_cash, pay_card = 0, total
    elif pm in ('микс', 'сплит', 'split'):
        pay_cash = min(total, max(0, int(raw_cash or 0)))
        pay_card = max(0, total - pay_cash)
    else:
        pay_cash, pay_card = 0, total

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if pay_cash > 0:
        db.execute("INSERT INTO payments (order_id, shift_id, method, amount, status, created_at, cashier_id) VALUES (?,?,?,?,?,?,?)",
                   (order_id, shift_id, 'наличные', pay_cash, 'paid', now_str, cashier_id))
    if pay_card > 0:
        db.execute("INSERT INTO payments (order_id, shift_id, method, amount, status, created_at, cashier_id) VALUES (?,?,?,?,?,?,?)",
                   (order_id, shift_id, 'карта', pay_card, 'paid', now_str, cashier_id))
    db.execute("UPDATE orders SET payment_status='paid', paid_at=COALESCE(paid_at, ?) WHERE id=?", (now_str, order_id))
    return pay_cash, pay_card""",
"""def record_order_payments(db, order_id, shift_id, payment_method, total, raw_cash=0, cashier_id=0, paid=True):
    \"\"\"Пишет новую версию платежей, не уничтожая историю. Старые paid/pending помечаются void.\"\"\"
    pm = (payment_method or 'не указан').strip().lower()
    if pm in ('наличные', 'cash'):
        pay_cash, pay_card = total, 0
    elif pm in ('карта', 'card', 'перевод', 'не указан'):
        pay_cash, pay_card = 0, total
    elif pm in ('микс', 'сплит', 'split'):
        pay_cash = min(total, max(0, int(raw_cash or 0)))
        pay_card = max(0, total - pay_cash)
    else:
        pay_cash, pay_card = 0, total

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE payments SET status='void', note=TRIM(COALESCE(note,'') || ' | заменено ' || ?) WHERE order_id=? AND status IN ('paid','pending')",
               (now_str, order_id))
    status = 'paid' if paid else 'pending'
    paid_at = now_str if paid else None
    if pay_cash > 0:
        db.execute("INSERT INTO payments (order_id, shift_id, method, amount, status, created_at, cashier_id, paid_at, note) VALUES (?,?,?,?,?,?,?,?,?)",
                   (order_id, shift_id, 'наличные', pay_cash, status, now_str, cashier_id, paid_at, ''))
    if pay_card > 0:
        db.execute("INSERT INTO payments (order_id, shift_id, method, amount, status, created_at, cashier_id, paid_at, note) VALUES (?,?,?,?,?,?,?,?,?)",
                   (order_id, shift_id, 'карта', pay_card, status, now_str, cashier_id, paid_at, ''))
    if paid:
        db.execute("UPDATE orders SET payment_status='paid', paid_at=COALESCE(paid_at, ?) WHERE id=?", (now_str, order_id))
    else:
        db.execute("UPDATE orders SET payment_status='unpaid', paid_at=NULL WHERE id=? AND payment_status!='paid'", (order_id,))
    return pay_cash, pay_card


def mark_order_paid(db, order_id, cashier_id=0):
    \"\"\"Подтверждает оплату pending-платежей (выдача заказа / оплата при получении).\"\"\"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if cashier_id:
        cur = db.execute("UPDATE payments SET status='paid', paid_at=COALESCE(paid_at, ?), cashier_id=? WHERE order_id=? AND status='pending'",
                         (now_str, cashier_id, order_id))
    else:
        cur = db.execute("UPDATE payments SET status='paid', paid_at=COALESCE(paid_at, ?) WHERE order_id=? AND status='pending'",
                         (now_str, order_id))
    if db.execute("SELECT 1 FROM payments WHERE order_id=? AND status='paid' LIMIT 1", (order_id,)).fetchone():
        db.execute("UPDATE orders SET payment_status='paid', paid_at=COALESCE(paid_at, ?) WHERE id=?", (now_str, order_id))
    return cur.rowcount""",
"payment versioning"))

app.append((
"""def settle_client_loyalty(db, order, direction=1):
    \"\"\"Начисляет (direction=1) или откатывает (direction=-1) бонусы и LTV только при выдаче заказа (done).\"\"\"
    phone = (order['phone'] or '').strip()
    if not phone: return
    total = int(order['total'] or 0)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client = db.execute("SELECT * FROM clients WHERE phone=?", (phone,)).fetchone()
    if direction > 0:
        prev_spent = client['total_spent'] if client else 0
        new_spent = prev_spent + total
        new_level = 'gold' if new_spent >= 30000 else ('silver' if new_spent >= 10000 else 'bronze')
        rate = 0.10 if new_level == 'gold' else (0.07 if new_level == 'silver' else 0.05)
        earned = int(total * rate)
        db.execute(\"\"\"
            INSERT INTO clients (phone, total_spent, orders_count, last_order_at, level, bonuses)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(phone) DO UPDATE SET
                total_spent = total_spent + ?,
                orders_count = orders_count + 1,
                last_order_at = ?,
                level = ?,
                bonuses = bonuses + ?
        \"\"\", (phone, total, 1, now_str, new_level, earned, total, now_str, new_level, earned))
    elif direction < 0 and client:
        rate = 0.10 if client['level'] == 'gold' else (0.07 if client['level'] == 'silver' else 0.05)
        earned = int(total * rate)
        new_spent = max(0, client['total_spent'] - total)
        new_level = 'gold' if new_spent >= 30000 else ('silver' if new_spent >= 10000 else 'bronze')
        db.execute(\"\"\"
            UPDATE clients SET
                total_spent = MAX(0, total_spent - ?),
                orders_count = MAX(0, orders_count - 1),
                bonuses = MAX(0, bonuses - ?),
                level = ?
            WHERE phone=?
        \"\"\", (total, earned, new_level, phone))""",
"""def settle_client_loyalty(db, order, direction=1, earned_amount=None):
    \"\"\"Начисляет/откатывает LTV и бонусы. Возвращает фактически начисленную сумму.\"\"\"
    phone = (order['phone'] or '').strip()
    if not phone: return 0
    total = int(order['total'] or 0)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client = db.execute("SELECT * FROM clients WHERE phone=?", (phone,)).fetchone()
    if direction > 0:
        prev_spent = client['total_spent'] if client else 0
        new_spent = prev_spent + total
        new_level = 'gold' if new_spent >= 30000 else ('silver' if new_spent >= 10000 else 'bronze')
        rate = 0.10 if new_level == 'gold' else (0.07 if new_level == 'silver' else 0.05)
        earned = int(total * rate)
        db.execute(\"\"\"
            INSERT INTO clients (phone, total_spent, orders_count, last_order_at, level, bonuses)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(phone) DO UPDATE SET
                total_spent = total_spent + ?,
                orders_count = orders_count + 1,
                last_order_at = ?,
                level = ?,
                bonuses = bonuses + ?
        \"\"\", (phone, total, 1, now_str, new_level, earned, total, now_str, new_level, earned))
        return earned
    if not client: return 0
    earned = int(earned_amount if earned_amount is not None else (order['earned_bonus'] or 0))
    new_spent = max(0, client['total_spent'] - total)
    new_level = 'gold' if new_spent >= 30000 else ('silver' if new_spent >= 10000 else 'bronze')
    db.execute(\"\"\"
        UPDATE clients SET
            total_spent = MAX(0, total_spent - ?),
            orders_count = MAX(0, orders_count - 1),
            bonuses = MAX(0, bonuses - ?),
            level = ?
        WHERE phone=?
    \"\"\", (total, earned, new_level, phone))
    return earned


def log_status_change(db, order_id, old_status, new_status, changed_by=0, comment=''):
    db.execute("INSERT INTO order_status_history (order_id, old_status, new_status, changed_at, changed_by, comment) VALUES (?,?,?,?,?,?)",
               (order_id, old_status, new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), changed_by, clean_str(comment, 200)))""",
"loyalty + history"))

app.append((
"""        if order['stock_deducted']:
            adjust_stock_for_order(order_id, old_items, direction=+1, actor=session['username'], reason_prefix='Правка (возврат)')
        err, new_cost = adjust_stock_for_order(order_id, validated_items, direction=-1, actor=session['username'], reason_prefix='Правка (списание)')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400""",
"""        if order['stock_deducted']:
            adjust_stock_for_order(order_id, old_items, direction=+1, actor=session['username'], reason_prefix='Правка (возврат)')
        err, new_cost, deducted = adjust_stock_for_order(order_id, validated_items, direction=-1, actor=session['username'], reason_prefix='Правка (списание)')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400""",
"update items stock"))

app.append((
"""        pay_cash, pay_card = record_order_payments(db, order_id, order['shift_id'], order['payment_method'], new_total, order['payment_cash'], session['user_id'])

        db.execute("UPDATE orders SET total=?, cost=?, payment_cash=?, payment_card=?, stock_deducted=1 WHERE id=?",
                   (new_total, new_cost, pay_cash, pay_card, order_id))""",
"""        pay_cash, pay_card = record_order_payments(db, order_id, order['shift_id'], order['payment_method'], new_total,
                                                   order['payment_cash'], session['user_id'],
                                                   paid=(order['payment_status'] == 'paid'))

        db.execute("UPDATE orders SET total=?, cost=?, payment_cash=?, payment_card=?, stock_deducted=? WHERE id=?",
                   (new_total, new_cost, pay_cash, pay_card, 1 if deducted else 0, order_id))""",
"update items payment"))

app.append((
"""@app.route('/site')
def public_site():
    db = get_db()
    return render_template('public_site.html', menu=db.execute("SELECT * FROM menu WHERE available=1 AND stop_list=0 ORDER BY sort_weight DESC, category, name").fetchall(), categories=db.execute("SELECT DISTINCT category FROM menu WHERE available=1 AND stop_list=0 ORDER BY category").fetchall(), shop_open=is_shop_open(), banners=db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall())""",
"""@app.route('/site')
def public_site():
    db = get_db()
    return render_template('public_site.html', menu=db.execute("SELECT * FROM menu WHERE available=1 AND stop_list=0 ORDER BY sort_weight DESC, category, name").fetchall(), categories=db.execute("SELECT DISTINCT category FROM menu WHERE available=1 AND stop_list=0 ORDER BY category").fetchall(), zones=db.execute("SELECT id, name, price FROM zones ORDER BY id").fetchall(), shop_open=is_shop_open(), banners=db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall())""",
"public zones"))

app.append((
"""    shift = ensure_open_shift()
    subtotal = sum(i['price'] * i['qty'] for i in items)
    promo_code = clean_str(data.get('promo_code', ''), 30).upper(); promo_discount = 0
    if promo_code:
        promo = db.execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (promo_code,)).fetchone()
        if promo: promo_discount = (subtotal * promo['discount_value']) // 100 if promo['discount_type'] == 'percent' else promo['discount_value']

    total = max(0, subtotal - promo_discount)
    pay_method = 'наличные' if data.get('payment_method') == 'наличные' else 'карта'""",
"""    shift = get_open_shift()
    if not shift:
        return jsonify({"error": "Приём заказов временно недоступен: касса не открыла смену."}), 400
    subtotal = sum(i['price'] * i['qty'] for i in items)
    promo_code = clean_str(data.get('promo_code', ''), 30).upper(); promo_discount = 0
    if promo_code:
        promo = db.execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (promo_code,)).fetchone()
        if promo: promo_discount = (subtotal * promo['discount_value']) // 100 if promo['discount_type'] == 'percent' else promo['discount_value']

    zone_name = clean_str(data.get('zone', ''), 80) if delivery_type == 'доставка' else ''
    zone = db.execute("SELECT price FROM zones WHERE name=?", (zone_name,)).fetchone() if zone_name else None
    delivery_price = int(zone['price']) if zone else 0
    total = max(0, subtotal - promo_discount) + delivery_price
    pay_method = 'наличные' if data.get('payment_method') == 'наличные' else 'карта'""",
"public shift+zone"))

app.append((
"""            INSERT INTO orders (
                created_at, status, total, cost, address, phone, comment, shift_id,
                payment_method, payment_cash, payment_card, change_from, delivery_type,
                promo_code, source, public_token, stock_deducted, bonus_awarded, idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)
        \"\"\", (now_str, 'new', total, 0, address, phone, comment, shift['id'], pay_method, 0, 0, change_from, delivery_type, promo_code, 'Сайт', pub_token, idem_key))
        order_id = cur.lastrowid

        err, total_cost = adjust_stock_for_order(order_id, items, direction=-1, actor='Сайт', reason_prefix='Заказ сайта')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400

        for i in items:
            db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                       (order_id, i['id'], i['name'], i['price'], i['qty'], i['mods']))

        pay_cash, pay_card = record_order_payments(db, order_id, shift['id'], pay_method, total, total if pay_method == 'наличные' else 0, 0)
        db.execute("UPDATE orders SET cost=?, payment_cash=?, payment_card=?, stock_deducted=1 WHERE id=?", (total_cost, pay_cash, pay_card, order_id))""",
"""            INSERT INTO orders (
                created_at, status, total, cost, address, phone, comment, shift_id,
                payment_method, payment_cash, payment_card, change_from, delivery_type, delivery_zone, delivery_price,
                promo_code, source, public_token, stock_deducted, bonus_awarded, idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)
        \"\"\", (now_str, 'new', total, 0, address, phone, comment, shift['id'], pay_method, 0, 0, change_from, delivery_type, zone_name, delivery_price, promo_code, 'Сайт', pub_token, idem_key))
        order_id = cur.lastrowid

        err, total_cost, deducted = adjust_stock_for_order(order_id, items, direction=-1, actor='Сайт', reason_prefix='Заказ сайта')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400

        for i in items:
            db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                       (order_id, i['id'], i['name'], i['price'], i['qty'], i['mods']))

        pay_cash, pay_card = record_order_payments(db, order_id, shift['id'], pay_method, total, total if pay_method == 'наличные' else 0, 0, paid=False)
        db.execute("UPDATE orders SET cost=?, payment_cash=?, payment_card=?, stock_deducted=? WHERE id=?", (total_cost, pay_cash, pay_card, 1 if deducted else 0, order_id))
        log_status_change(db, order_id, None, 'new', 0, 'Создан на сайте')""",
"public pending payment"))

app.append((
"""    send_tg_async(f"🌐 <b>НОВЫЙ ЗАКАЗ С САЙТА #{order_id}</b>\\n💰 Сумма: <b>{total} ₽</b> ({pay_method})\\n📞 Тел: {phone}\\n📍 Адрес: {address}")""",
"""    send_tg_async(f"🌐 <b>НОВЫЙ ЗАКАЗ С САЙТА #{order_id}</b>\\n💰 Сумма: <b>{total} ₽</b> ({pay_method}, доставка {delivery_price} ₽)\\n📞 Тел: {phone}\\n📍 Адрес: {address}")""",
"public tg"))

app.append((
"""    delivery_price = parse_zone_price(zone_str, delivery_type, client_level)
    total = max(0, subtotal - manual_discount - promo_discount) + delivery_price""",
"""    delivery_price = parse_zone_price(zone_str, delivery_type, client_level)
    if delivery_type == 'доставка' and delivery_price == 0 and zone_str:
        zone_row = db.execute("SELECT price FROM zones WHERE name=?", (zone_str,)).fetchone()
        if zone_row: delivery_price = int(zone_row['price'])
    total = max(0, subtotal - manual_discount - promo_discount) + delivery_price""",
"cashier zone lookup"))

app.append((
"""        err, total_cost = adjust_stock_for_order(order_id, items, direction=-1, actor=session['username'], reason_prefix='Касса')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400""",
"""        err, total_cost, deducted = adjust_stock_for_order(order_id, items, direction=-1, actor=session['username'], reason_prefix='Касса')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400""",
"cashier stock"))

app.append((
"""        pay_cash, pay_card = record_order_payments(db, order_id, shift['id'], payment_method, total, data.get('pay_cash', 0), session['user_id'])
        db.execute("UPDATE orders SET cost=?, payment_cash=?, payment_card=?, stock_deducted=1 WHERE id=?", (total_cost, pay_cash, pay_card, order_id))
        enqueue_print_job(db, order_id, 'receipt')""",
"""        pay_cash, pay_card = record_order_payments(db, order_id, shift['id'], payment_method, total, data.get('pay_cash', 0), session['user_id'])
        db.execute("UPDATE orders SET cost=?, payment_cash=?, payment_card=?, stock_deducted=? WHERE id=?", (total_cost, pay_cash, pay_card, 1 if deducted else 0, order_id))
        log_status_change(db, order_id, None, 'new', session['user_id'], 'Создан на кассе')
        enqueue_print_job(db, order_id, 'receipt')""",
"cashier payment flag"))

app.append((
"""    row = db.execute("SELECT COUNT(*) cnt, COALESCE(SUM(payment_cash),0) cash_on_hand FROM orders WHERE date(created_at)=? AND courier_name=? AND status IN ('delivering', 'done')", (today, name)).fetchone()""",
"""    row = db.execute("SELECT COUNT(*) cnt, COALESCE(SUM(payment_cash),0) cash_on_hand FROM orders WHERE date(created_at)=? AND courier_name=? AND status='done' AND payment_status='paid'", (today, name)).fetchone()""",
"courier paid cash"))

app.append((
"""@app.route('/api/customer_lookup')
def api_customer_lookup():
    phone = request.args.get('phone', '').strip()
    if len(phone) < 5:
        return jsonify({'found': False})
    db = get_db()
    rows = db.execute(
        "SELECT address, comment, total, created_at FROM orders WHERE phone LIKE ? ORDER BY id DESC LIMIT 20",
        (f"%{phone}%",)
    ).fetchall()""",
"""@app.route('/api/customer_lookup')
@login_required('admin', 'cashier')
def api_customer_lookup():
    digits = re.sub(r'\\D', '', request.args.get('phone', ''))
    if len(digits) < 10:
        return jsonify({'found': False})
    phone = digits[-10:]
    db = get_db()
    rows = db.execute(
        "SELECT address, comment, total, created_at FROM orders "
        "WHERE substr(replace(replace(replace(replace(replace(phone,' ',''),'-',''),'(',''),')',''),'+',''), -10) = ? "
        "ORDER BY id DESC LIMIT 20",
        (phone,)
    ).fetchall()""",
"customer lookup pii"))

app.append((
"""    logs = db.execute("SELECT * FROM stock_logs ORDER BY id DESC LIMIT 60").fetchall()
    total_stock_value = sum(max(0, i['stock']) * i['cost_price'] for i in ings)
    return render_template('warehouse.html', ingredients=ings, preps=preps, raw_ings=raw_ings, logs=logs, total_stock_value=round(total_stock_value, 1))""",
"""    logs = db.execute("SELECT * FROM stock_logs ORDER BY id DESC LIMIT 60").fetchall()
    total_stock_value = sum(max(0, i['stock']) * i['cost_price'] for i in ings)
    menu_items = db.execute(\"\"\"SELECT m.id, m.name, m.category, m.price,
        (SELECT COUNT(*) FROM recipes r WHERE r.menu_id=m.id) recipe_count,
        (SELECT COALESCE(SUM(r.amount * ing.cost_price),0) FROM recipes r JOIN ingredients ing ON ing.id=r.ingredient_id WHERE r.menu_id=m.id) cost
        FROM menu m ORDER BY m.category, m.name\"\"\").fetchall()
    missing_recipes = [m for m in menu_items if (m['recipe_count'] or 0) == 0]
    return render_template('warehouse.html', ingredients=ings, preps=preps, raw_ings=raw_ings, logs=logs,
                           total_stock_value=round(total_stock_value, 1), menu_items=menu_items, missing_recipes=missing_recipes)""",
"warehouse coverage"))

app.append((
"""    top_clients = db.execute("SELECT phone, COUNT(*) cnt, SUM(total) sum FROM orders WHERE date(created_at) = ? AND status != 'cancelled' AND phone != '' GROUP BY phone ORDER BY sum DESC LIMIT 5", (today,)).fetchall()
    return render_template('admin.html', stats=stats, avg_check=avg_check, chart_data=chart_data, top_items=top_items, top_clients=top_clients,""",
"""    top_clients = db.execute("SELECT phone, COUNT(*) cnt, SUM(total) sum FROM orders WHERE date(created_at) = ? AND status != 'cancelled' AND phone != '' GROUP BY phone ORDER BY sum DESC LIMIT 5", (today,)).fetchall()
    missing_recipes_count = db.execute("SELECT COUNT(*) FROM menu m WHERE NOT EXISTS (SELECT 1 FROM recipes r WHERE r.menu_id=m.id)").fetchone()[0]
    return render_template('admin.html', stats=stats, avg_check=avg_check, chart_data=chart_data, top_items=top_items, top_clients=top_clients, missing_recipes_count=missing_recipes_count,""",
"admin coverage count"))

app.append((
"""        if new_status == 'cancelled':
            if order['stock_deducted']:
                items = [dict(r) for r in db.execute("SELECT menu_id as id, qty FROM order_items WHERE order_id=?", (order_id,)).fetchall()]
                adjust_stock_for_order(order_id, items, direction=+1, actor=session['username'], reason_prefix='Отмена заказа')
            if order['bonus_awarded']:
                settle_client_loyalty(db, order, direction=-1)
            if (order['used_bonus'] or 0) > 0 and order['phone']:
                db.execute("UPDATE clients SET bonuses = bonuses + ? WHERE phone=?", (order['used_bonus'], order['phone']))
            reason = clean_str(data.get('reason', 'Отменен сотрудником'), 120)
            paid_rows = db.execute("SELECT method, amount FROM payments WHERE order_id=? AND status='paid'", (order_id,)).fetchall()
            for p in paid_rows:
                db.execute("INSERT INTO refunds (order_id, shift_id, method, amount, reason, created_at, user_id) VALUES (?,?,?,?,?,?,?)",
                           (order_id, order['shift_id'], p['method'], p['amount'], reason, now_str, session.get('user_id')))
            if paid_rows:
                db.execute("UPDATE orders SET payment_status='refunded' WHERE id=?", (order_id,))
            db.execute("UPDATE payments SET status='refunded' WHERE order_id=? AND status='paid'", (order_id,))
            db.execute("UPDATE orders SET status='cancelled', stock_deducted=0, bonus_awarded=0, cancel_reason=? WHERE id=?",
                       (reason, order_id))

        elif new_status == 'done':
            if not order['bonus_awarded']:
                settle_client_loyalty(db, order, direction=+1)
            db.execute("UPDATE orders SET status='done', bonus_awarded=1 WHERE id=?", (order_id,))""",
"""        if new_status == 'cancelled':
            if order['stock_deducted']:
                items = [dict(r) for r in db.execute("SELECT menu_id as id, qty FROM order_items WHERE order_id=?", (order_id,)).fetchall()]
                adjust_stock_for_order(order_id, items, direction=+1, actor=session['username'], reason_prefix='Отмена заказа')
            reason = clean_str(data.get('reason', 'Отменен сотрудником'), 120)
            if order['bonus_awarded']:
                earned = int(order['earned_bonus'] or 0)
                if order['client_credited']:
                    settle_client_loyalty(db, order, direction=-1, earned_amount=earned)
                if earned > 0:
                    db.execute("UPDATE orders SET bonus_awarded=0, earned_bonus=0, client_credited=0, loyalty_applied=0, bonus_refunded=COALESCE(bonus_refunded,0)+? WHERE id=?", (earned, order_id))
                else:
                    db.execute("UPDATE orders SET client_credited=0, loyalty_applied=0 WHERE id=?", (order_id,))
            if (order['used_bonus'] or 0) > 0 and not (order['used_bonus_refunded'] or 0):
                db.execute("UPDATE clients SET bonuses = bonuses + ? WHERE phone=?", (order['used_bonus'], order['phone']))
                db.execute("UPDATE orders SET used_bonus_refunded=1 WHERE id=?", (order_id,))
            paid_rows = db.execute("SELECT method, amount FROM payments WHERE order_id=? AND status='paid'", (order_id,)).fetchall()
            pending_rows = db.execute("SELECT 1 FROM payments WHERE order_id=? AND status='pending' LIMIT 1", (order_id,)).fetchone()
            for p in paid_rows:
                db.execute("INSERT INTO refunds (order_id, shift_id, method, amount, reason, created_at, user_id) VALUES (?,?,?,?,?,?,?)",
                           (order_id, order['shift_id'], p['method'], p['amount'], reason, now_str, session.get('user_id')))
            if paid_rows:
                db.execute("UPDATE orders SET payment_status='refunded' WHERE id=?", (order_id,))
            elif pending_rows:
                db.execute("UPDATE orders SET payment_status='cancelled' WHERE id=?", (order_id,))
            db.execute("UPDATE payments SET status='refunded' WHERE order_id=? AND status='paid'", (order_id,))
            db.execute("UPDATE payments SET status='cancelled' WHERE order_id=? AND status='pending'", (order_id,))
            db.execute("UPDATE orders SET status='cancelled', stock_deducted=0, cancel_reason=? WHERE id=?", (reason, order_id))

        elif new_status == 'done':
            mark_order_paid(db, order_id, session.get('user_id', 0))
            if not order['bonus_awarded']:
                earned = settle_client_loyalty(db, order, direction=+1)
                db.execute("UPDATE orders SET status='done', bonus_awarded=1, earned_bonus=?, client_credited=?, loyalty_applied=? WHERE id=?",
                           (earned, 1 if order['phone'] else 0, 1 if order['phone'] else 0, order_id))
            else:
                db.execute("UPDATE orders SET status='done' WHERE id=?", (order_id,))""",
"status machine B"))

app.append((
"""        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.context_processor""",
"""        log_status_change(db, order_id, cur_status, new_status, session.get('user_id', 0), data.get('reason', ''))
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.context_processor""",
"log transition"))

patch('app.py', app)

# ---------------------------------------------------------------- templates
tpl = []
tpl.append((
"""            <div class="form-field">
                <label>Способ получения</label>
                <select id="del-type" onchange="toggleDelType()">
                    <option value="доставка">Доставка курьером</option>
                    <option value="самовывоз">Самовывоз из ресторана</option>
                </select>
            </div>
            <div class="form-field" id="addr-field">""",
"""            <div class="form-field">
                <label>Способ получения</label>
                <select id="del-type" onchange="toggleDelType()">
                    <option value="доставка">Доставка курьером</option>
                    <option value="самовывоз">Самовывоз из ресторана</option>
                </select>
            </div>
            <div class="form-field" id="zone-field">
                <label>Зона доставки</label>
                <select id="client-zone" onchange="updateCartUI()">
                    {% for z in zones %}<option value="{{ z.name }}" data-price="{{ z.price }}">{{ z.name }}{% if z.price %} (+{{ z.price }} ₽){% endif %}</option>{% endfor %}
                    {% if not zones %}<option value="">Уточнит оператор</option>{% endif %}
                </select>
            </div>
            <div class="form-field" id="addr-field">""",
"public zone field"))

tpl.append((
"""            <div class="form-field">
                <label>Комментарий</label>
                <input type="text" id="client-comment" placeholder="Домофон, сдача с 5000 ₽...">
            </div>""",
"""            <div class="form-field">
                <label>Оплата при получении</label>
                <select id="client-payment">
                    <option value="наличные">Наличными курьеру</option>
                    <option value="карта">Картой при получении</option>
                </select>
            </div>
            <div class="form-field">
                <label>Комментарий</label>
                <input type="text" id="client-comment" placeholder="Домофон, сдача с 5000 ₽...">
            </div>""",
"public payment field"))

tpl.append((
"""    <div class="sheet-footer">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;font-size:16px">""",
"""    <div class="sheet-footer">
        <div id="delivery-line" style="display:none;justify-content:space-between;margin-bottom:8px;font-size:14px;color:var(--text-muted)">
            <span>Доставка:</span><span id="delivery-sum">0 ₽</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;font-size:16px">""",
"public delivery line"))

tpl.append((
"""    document.getElementById('cart-count').innerText = totalQty;
    document.getElementById('floating-items-txt').innerText = totalQty + (totalQty === 1 ? ' товар' : ' товаров');
    document.getElementById('floating-sum').innerText = totalSum + ' ₽';
    document.getElementById('sheet-total').innerText = totalSum + ' ₽';
    document.getElementById('floating-bar').style.display = 'flex';""",
"""    const delivery = getDeliveryPrice();
    document.getElementById('cart-count').innerText = totalQty;
    document.getElementById('floating-items-txt').innerText = totalQty + (totalQty === 1 ? ' товар' : ' товаров');
    document.getElementById('floating-sum').innerText = (totalSum + delivery) + ' ₽';
    document.getElementById('sheet-total').innerText = (totalSum + delivery) + ' ₽';
    const dl = document.getElementById('delivery-line');
    if (dl) {
        dl.style.display = (delivery > 0 && document.getElementById('del-type').value === 'доставка') ? 'flex' : 'none';
        document.getElementById('delivery-sum').innerText = delivery + ' ₽';
    }
    document.getElementById('floating-bar').style.display = 'flex';""",
"public total js"))

tpl.append((
"""function toggleDelType() {
    let type = document.getElementById('del-type').value;
    document.getElementById('addr-field').style.display = (type === 'самовывоз') ? 'none' : 'block';
}""",
"""function getDeliveryPrice() {
    if (document.getElementById('del-type').value !== 'доставка') return 0;
    const z = document.getElementById('client-zone');
    if (!z || z.selectedIndex < 0) return 0;
    return parseInt(z.options[z.selectedIndex].dataset.price || '0') || 0;
}

function toggleDelType() {
    let type = document.getElementById('del-type').value;
    document.getElementById('addr-field').style.display = (type === 'самовывоз') ? 'none' : 'block';
    const zf = document.getElementById('zone-field');
    if (zf) zf.style.display = (type === 'самовывоз') ? 'none' : 'block';
    updateCartUI();
}""",
"public toggle js"))

tpl.append((
"""    let itemsArr = Object.values(cart).map(i => ({id: i.id, qty: i.qty}));

    fetch('/api/public_order', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({phone, delivery_type: delType, address, comment, items: itemsArr})
    })""",
"""    let itemsArr = Object.values(cart).map(i => ({id: i.id, qty: i.qty}));
    let zone = document.getElementById('client-zone')?.value || '';
    let payment = document.getElementById('client-payment')?.value || 'карта';

    fetch('/api/public_order', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({phone, delivery_type: delType, address, comment, items: itemsArr, zone, payment_method: payment})
    })""",
"public submit js"))

tpl.append((
"""    <button class="tab-btn" id="btn-tab-logs" onclick="showTab('tab-logs', this)">📜 4. Журнал операций</button>""",
"""    <button class="tab-btn" id="btn-tab-logs" onclick="showTab('tab-logs', this)">📜 4. Журнал операций</button>
    <button class="tab-btn" id="btn-tab-recipes" onclick="showTab('tab-recipes', this)">🍱 5. Техкарты блюд</button>""",
"warehouse tab btn"))

tpl.append((
"""<!-- ВКЛАДКА 4: ЖУРНАЛ ДВИЖЕНИЙ -->
<div id="tab-logs" class="panel">""",
"""<!-- ВКЛАДКА 5: ТЕХКАРТЫ БЛЮД -->
<div id="tab-recipes" class="panel">
    <div class="stat-card" style="padding:18px;margin-bottom:20px;border:1px solid #10b981 !important">
        <h3 style="margin:0 0 8px;color:#10b981">🍱 Техкарты блюд и себестоимость</h3>
        <p style="color:var(--text-muted);font-size:14px;margin:0 0 12px">
            С техкартой: <b>{{ menu_items|length - missing_recipes|length }}</b> из <b>{{ menu_items|length }}</b>.
            Без техкарты: <b style="color:#ef4444">{{ missing_recipes|length }}</b>.
            Пока у блюда нет техкарты, склад по нему не списывается, а себестоимость заказа равна 0.
        </p>
        <table>
            <tr><th>Блюдо</th><th>Категория</th><th>Цена</th><th>Ингредиентов</th><th>Себестоимость</th><th>Статус</th><th></th></tr>
            {% for m in menu_items %}
            <tr>
                <td><b>{{ m.name }}</b></td>
                <td>{{ m.category }}</td>
                <td>{{ m.price }} ₽</td>
                <td>{{ m.recipe_count }}</td>
                <td>{{ m.cost|round(1) }} ₽</td>
                <td>{% if m.recipe_count %}<span style="color:#10b981">✅ есть</span>{% else %}<span style="color:#ef4444">❌ нет</span>{% endif %}</td>
                <td><a class="btn" href="/admin/menu/edit/{{ m.id }}">Открыть ТТК</a></td>
            </tr>
            {% endfor %}
        </table>
    </div>
</div>

<!-- ВКЛАДКА 4: ЖУРНАЛ ДВИЖЕНИЙ -->
<div id="tab-logs" class="panel">""",
"warehouse recipes panel"))

tpl.append((
"""<div class="status-box">
    <h2 style="margin:0; color:var(--accent); flex:1;">📅 Режим работы</h2>
    <form method="post" action="/admin/shop_status" style="display:flex; gap:10px;">
        <button type="submit" name="status" value="auto" class="btn {% if shop_status == 'auto' %}btn-edit{% else %}btn-danger{% endif %}">🕒 Авто (10:00 - 21:30)</button>
        <button type="submit" name="status" value="open" class="btn {% if shop_status == 'open' %}btn-edit{% else %}btn-danger{% endif %}">🟢 Открыто (Принудительно)</button>
        <button type="submit" name="status" value="closed" class="btn {% if shop_status == 'closed' %}btn-danger{% else %}btn-edit{% endif %}" style="background:#ff453a; color:#fff;">🔴 Закрыто (Выходной)</button>
    </form>
</div>""",
"""<div class="status-box">
    <h2 style="margin:0; color:var(--accent); flex:1;">📅 Режим работы</h2>
    <form method="post" action="/admin/shop_status" style="display:flex; gap:10px;">
        <button type="submit" name="status" value="auto" class="btn {% if shop_status == 'auto' %}btn-edit{% else %}btn-danger{% endif %}">🕒 Авто (10:00 - 21:30)</button>
        <button type="submit" name="status" value="open" class="btn {% if shop_status == 'open' %}btn-edit{% else %}btn-danger{% endif %}">🟢 Открыто (Принудительно)</button>
        <button type="submit" name="status" value="closed" class="btn {% if shop_status == 'closed' %}btn-danger{% else %}btn-edit{% endif %}" style="background:#ff453a; color:#fff;">🔴 Закрыто (Выходной)</button>
    </form>
</div>

{% if missing_recipes_count and missing_recipes_count > 0 %}
<div class="status-box" style="border-color:#ff9f0a">
    <h2 style="margin:0; color:#ff9f0a; flex:1;">🍱 Блюд без техкарты: {{ missing_recipes_count }}</h2>
    <a href="/warehouse" class="btn" style="background:#ff9f0a;color:#000">Заполнить техкарты →</a>
</div>
{% endif %}""",
"admin recipes warning"))

for rel, pairs in (
    ('templates/public_site.html', [tpl[0], tpl[1], tpl[2], tpl[3], tpl[4], tpl[5]]),
    ('templates/warehouse.html', [tpl[6], tpl[7]]),
    ('templates/admin.html', [tpl[8]]),
):
    patch(rel, pairs)

print("PATCH B APPLIED OK")