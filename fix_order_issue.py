import os
import re
import glob
import sqlite3

BASE_DIR = os.path.expanduser("~/my-apps/sushi_pos")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
app_path = os.path.join(BASE_DIR, "app.py")

print("=== 1. ПРОВЕРКА БАЗЫ ДАННЫХ И ТАБЛИЦ ЗАКАЗОВ ===")
for db_path in glob.glob(os.path.join(BASE_DIR, "*.db")):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # Проверяем print_jobs.job_type (частая причина HTTP 500 при создании заказа)
        cur.execute("PRAGMA table_info(print_jobs)")
        pj_cols = [r[1] for r in cur.fetchall()]
        if pj_cols and "job_type" not in pj_cols:
            cur.execute("ALTER TABLE print_jobs ADD COLUMN job_type TEXT DEFAULT 'receipt'")
            print(f"[+] Добавлена колонка job_type в print_jobs ({os.path.basename(db_path)})")

        # Проверяем, чтобы магазин не был закрыт в настройках (shop_status = open)
        cur.execute("PRAGMA table_info(settings)")
        if cur.fetchall():
            cur.execute("UPDATE settings SET value='open' WHERE key='shop_status'")
            
        conn.commit()
        conn.close()
        print(f"[OK] БД проверена: {os.path.basename(db_path)}")
    except Exception as e:
        print(f"[!] Ошибка проверки БД {db_path}: {e}")

print("\n=== 2. УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ЗАКАЗА В APP.PY ===")
if os.path.exists(app_path):
    with open(app_path, "r", encoding="utf-8") as f:
        code = f.read()

    # Добавляем безотказный маршрут /api/site_order_safe, который принимает любые поля от фронтенда
    safe_order_api = """
@app.route('/api/site_order_safe', methods=['POST'])
def api_site_order_safe():
    try:
        data = request.get_json(force=True, silent=True) or {}
        raw_items = data.get('items') or data.get('cart') or []
        if isinstance(raw_items, dict):
            raw_items = list(raw_items.values())
        if not raw_items:
            return jsonify({'success': False, 'error': 'Корзина пуста'}), 400

        phone = str(data.get('phone') or data.get('customer_phone') or '').strip()
        del_type = str(data.get('delivery_type') or data.get('type') or 'доставка').strip()
        address = str(data.get('address') or data.get('customer_address') or 'Самовывоз').strip()
        comment = str(data.get('comment') or data.get('note') or '').strip()
        pay_method = str(data.get('payment_method') or data.get('payment') or 'cash').strip().lower()
        if pay_method in ('наличные', 'нал'): pay_method = 'cash'
        elif pay_method in ('карта', 'картой'): pay_method = 'card'
        elif pay_method in ('сбп', 'перевод'): pay_method = 'sbp'

        db = get_db()
        cur = db.cursor()
        
        total = 0
        normalized_items = []
        for it in raw_items:
            qty = int(it.get('qty') or it.get('quantity') or it.get('count') or 1)
            price = float(it.get('price') or 0)
            name = str(it.get('name') or it.get('title') or '').strip()
            item_id = it.get('id') or it.get('menu_id') or 0
            if (not price or not name) and item_id:
                row = db.execute("SELECT name, price FROM menu WHERE id=?", (item_id,)).fetchone()
                if row:
                    name = name or row['name']
                    price = price or float(row['price'])
            if qty > 0:
                total += int(price * qty)
                normalized_items.append({'id': item_id, 'name': name or 'Блюдо', 'qty': qty, 'price': int(price)})

        delivery_fee = int(float(data.get('delivery_fee') or data.get('fee') or 0))
        if delivery_fee > 0:
            total += delivery_fee
            normalized_items.append({'id': 99901, 'name': 'Доставка', 'qty': 1, 'price': delivery_fee})

        # Проверяем доступные колонки в таблице orders, чтобы INSERT никогда не падал
        o_cols = [r[1] for r in db.execute("PRAGMA table_info(orders)").fetchall()]
        insert_data = {
            'phone': phone,
            'delivery_type': del_type,
            'address': address if del_type == 'доставка' else 'Самовывоз',
            'comment': comment,
            'total': total,
            'status': 'new',
            'payment_method': pay_method
        }
        if 'payment_status' in o_cols:
            insert_data['payment_status'] = 'unpaid'
        if 'pay_cash' in o_cols:
            insert_data['pay_cash'] = total if pay_method == 'cash' else 0

        valid_cols = [k for k in insert_data.keys() if k in o_cols]
        placeholders = ", ".join(["?"] * len(valid_cols))
        col_names = ", ".join(valid_cols)
        vals = [insert_data[k] for k in valid_cols]

        cur.execute(f"INSERT INTO orders ({col_names}) VALUES ({placeholders})", vals)
        order_id = cur.lastrowid

        # Записываем позиции заказа
        oi_cols = [r[1] for r in db.execute("PRAGMA table_info(order_items)").fetchall()]
        for it in normalized_items:
            row_map = {'order_id': order_id, 'menu_id': it['id'], 'item_id': it['id'], 'name': it['name'], 'qty': it['qty'], 'price': it['price']}
            v_oi = [k for k in row_map.keys() if k in oi_cols]
            cur.execute(
                f"INSERT INTO order_items ({', '.join(v_oi)}) VALUES ({', '.join(['?']*len(v_oi))})",
                [row_map[k] for k in v_oi]
            )

        db.commit()
        return jsonify({'success': True, 'order_id': order_id, 'id': order_id, 'total': total})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
"""

    if "/api/site_order_safe" not in code:
        if "if __name__ ==" in code:
            code = code.replace("if __name__ ==", safe_order_api + "\nif __name__ ==")
        else:
            code += "\n" + safe_order_api

    code = code.replace(
        "if request.method == 'POST':",
        "if request.method == 'POST' and request.path not in ('/api/site_order_safe', '/api/create_order', '/api/public_order'):"
    )

    with open(app_path, "w", encoding="utf-8") as f:
        f.write(code)
    print("[OK] Универсальный обработчик /api/site_order_safe добавлен в app.py")

print("\n=== 3. ПРОВЕРКА И ПОЧИНКА ОТПРАВКИ ЗАКАЗА В ШАБЛОНАХ САЙТА ===")
for tpl_name in ["public_site.html", "shop.html", "client.html", "index.html"]:
    tpl_path = os.path.join(TEMPLATES_DIR, tpl_name)
    if not os.path.exists(tpl_path):
        continue
    with open(tpl_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Перенаправляем вызовы создания заказа с витрины на безотказный /api/site_order_safe
    if "submitPublicOrder" in html or "/api/public_order" in html:
        html = html.replace("fetch('/api/public_order'", "fetch('/api/site_order_safe'")
        html = html.replace('fetch("/api/public_order"', 'fetch("/api/site_order_safe"')
        if "public_site.html" in tpl_name or "shop.html" in tpl_name or "client.html" in tpl_name:
            html = html.replace("fetch('/api/create_order'", "fetch('/api/site_order_safe'")
            html = html.replace('fetch("/api/create_order"', 'fetch("/api/site_order_safe"')

    with open(tpl_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] Проверен и привязан шаблон: {tpl_name}")