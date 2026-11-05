import os
import re

app_path = os.path.expanduser("~/my-apps/sushi_pos/app.py")

with open(app_path, "r", encoding="utf-8") as f:
    code = f.read()

new_safe_route = """@app.route('/api/site_order_safe', methods=['POST'])
def api_site_order_safe():
    try:
        from datetime import datetime
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

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
        zone = str(data.get('zone') or '').strip()
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

        # Находим открытую смену, если shift_id обязателен
        shift_row = db.execute("SELECT id FROM shifts WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
        shift_id = shift_row['id'] if shift_row else 1

        insert_data = {
            'phone': phone,
            'customer_phone': phone,
            'delivery_type': del_type,
            'address': address if del_type == 'доставка' else 'Самовывоз',
            'zone': zone,
            'comment': comment,
            'total': total,
            'subtotal': total,
            'discount': 0,
            'delivery_fee': delivery_fee,
            'status': 'new',
            'payment_method': pay_method,
            'payment_status': 'unpaid',
            'pay_cash': total if pay_method == 'cash' else 0,
            'pay_card': total if pay_method in ('card', 'sbp') else 0,
            'shift_id': shift_id,
            'created_at': now_str,
            'updated_at': now_str
        }

        # Проверяем все колонки таблицы orders, включая любые NOT NULL без DEFAULT
        o_info = db.execute("PRAGMA table_info(orders)").fetchall()
        final_order_cols = {}
        for col in o_info:
            cname = col[1]
            ctype = (col[2] or '').upper()
            notnull = col[3]
            dflt = col[4]
            pk = col[5]
            if pk:
                continue
            if cname in insert_data:
                final_order_cols[cname] = insert_data[cname]
            elif notnull and dflt is None:
                if 'INT' in ctype or 'REAL' in ctype or 'NUM' in ctype:
                    final_order_cols[cname] = 0
                else:
                    final_order_cols[cname] = ''

        col_names = ", ".join(final_order_cols.keys())
        placeholders = ", ".join(["?"] * len(final_order_cols))
        vals = list(final_order_cols.values())

        cur.execute(f"INSERT INTO orders ({col_names}) VALUES ({placeholders})", vals)
        order_id = cur.lastrowid

        # Записываем позиции заказа с защитой от NOT NULL
        oi_info = db.execute("PRAGMA table_info(order_items)").fetchall()
        for it in normalized_items:
            row_map = {
                'order_id': order_id,
                'menu_id': it['id'],
                'item_id': it['id'],
                'name': it['name'],
                'qty': it['qty'],
                'quantity': it['qty'],
                'price': it['price'],
                'total': it['price'] * it['qty'],
                'cost': 0,
                'created_at': now_str
            }
            final_oi = {}
            for col in oi_info:
                cname = col[1]
                ctype = (col[2] or '').upper()
                notnull = col[3]
                dflt = col[4]
                pk = col[5]
                if pk:
                    continue
                if cname in row_map:
                    final_oi[cname] = row_map[cname]
                elif notnull and dflt is None:
                    final_oi[cname] = 0 if ('INT' in ctype or 'REAL' in ctype) else ''

            cur.execute(
                f"INSERT INTO order_items ({', '.join(final_oi.keys())}) VALUES ({', '.join(['?']*len(final_oi))})",
                list(final_oi.values())
            )

        # Пишем историю статусов, если таблица есть
        try:
            cur.execute("INSERT INTO order_status_history (order_id, status, created_at) VALUES (?, 'new', ?)", (order_id, now_str))
        except Exception:
            pass

        db.commit()
        return jsonify({'success': True, 'order_id': order_id, 'id': order_id, 'total': total})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
"""

pattern = re.compile(r"@app\.route\('/api/site_order_safe'.*?return jsonify\(\{'success': False, 'error': str\(e\)\}\), 500", re.DOTALL)
if pattern.search(code):
    code = pattern.sub(new_safe_route.strip(), code)
    print("✅ Функция api_site_order_safe обновлена (добавлено заполнение created_at и всех NOT NULL полей)!")
else:
    code += "\n" + new_safe_route
    print("✅ Функция api_site_order_safe добавлена в конец файла!")

with open(app_path, "w", encoding="utf-8") as f:
    f.write(code)