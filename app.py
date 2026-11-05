from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, flash, make_response, send_from_directory, send_file
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import random
import hashlib
import os
import uuid
import io
import re
import time

try:
    import openpyxl
except ImportError:
    openpyxl = None

app = Flask(__name__)
app.secret_key = os.environ.get('SUSHI_SECRET', 'krevetka-is-pin-enterprise-2026')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sushi.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_IMAGE_EXT = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


def save_menu_image(file):
    """Сохраняет только реальное изображение с безопасным расширением."""
    if not file or not file.filename:
        return ''
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_IMAGE_EXT:
        return ''
    head = file.stream.read(16)
    file.stream.seek(0)
    ok = (
        head.startswith(b'\x89PNG\r\n\x1a\n') or
        head.startswith(b'\xff\xd8\xff') or
        head.startswith(b'GIF87a') or head.startswith(b'GIF89a') or
        (head.startswith(b'RIFF') and head[8:12] == b'WEBP')
    )
    if not ok:
        return ''
    filename = f"{uuid.uuid4()}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return filename

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=20.0)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

@app.before_request
def check_pin_authentication():
    path = request.path
    public_prefixes = (
        '/login', '/logout', '/site', '/api/public_order', '/track/', '/api/track_order/',
        '/rate/', '/api/site/client/', '/api/check_promo', '/static/', '/manifest.json',
        '/chat_manifest.json', '/sw.js'
    )
    if any(path == p or path.startswith(p) for p in public_prefixes):
        return None
    if 'user_id' not in session:
        if path.startswith('/api/'):
            return jsonify({"error": "Требуется вход по ПИН-коду", "need_pin": True}), 401
        return redirect(url_for('login'))

@app.after_request
def inject_ultra_style(response):
    if response.content_type and response.content_type.startswith('text/html'):
        if (not request.path.startswith('/receipt/') and
            not request.path.startswith('/ticket/') and
            not request.path.startswith('/fiscal/') and
            not request.path.startswith('/shift/z_report/') and
            not request.path.startswith('/login')):
            try:
                html = response.get_data(as_text=True)
                inject_tags = '<link rel="stylesheet" href="/static/ultra_theme.css?v=512"><script src="/static/operational_modules.js?v=900" defer></script><script src="/static/power_pack.js?v=950" defer></script><script src="/static/ultra_erp_v10.js?v=1000" defer></script><script src="/static/ultra_ui.js?v=512" defer></script>'
                if 'ultra_theme.css' not in html and '</head>' in html:
                    html = html.replace('</head>', inject_tags + '</head>', 1)
                    response.set_data(html)
            except Exception:
                pass
    return response

def get_setting(key, default=None):
    try:
        row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default
    except Exception:
        return default

def set_setting(key, value):
    db = get_db()
    db.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?", (key, str(value), str(value)))
    db.commit()

@app.context_processor
def inject_globals():
    return {
        'csrf_token': lambda: '',
        'brand_name': get_setting('brand_name') or 'КРЕВЕТКА',
        'brand_city': get_setting('brand_city') or 'г. Инта',
        'brand_address': get_setting('brand_address') or 'ул. Горького, 1',
        'brand_phone': get_setting('brand_phone') or '+7 (996) 637-18-06',
        'brand_slogan': get_setting('brand_slogan') or 'Ресторан доставки в г. Инта'
    }

def admin_only(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        role = session.get('role', '')
        path = request.path
        if role == 'admin':
            return f(*args, **kwargs)
        if (path.startswith('/warehouse') or path.startswith('/admin/menu') or path.startswith('/admin/ingredient')) and session.get('can_edit_menu'):
            return f(*args, **kwargs)
        if (path.startswith('/accounting') or path.startswith('/analytics')) and session.get('can_view_finance'):
            return f(*args, **kwargs)
        return (
            "<div style='background:#09090b;color:#fafafa;font-family:sans-serif;height:100vh;"
            "display:flex;flex-direction:column;align-items:center;justify-content:center;'>"
            "<h2>Доступ ограничен для вашего ПИН-кода</h2>"
            "<p style='color:#a1a1aa;'>Этот раздел доступен Администратору или сотрудникам с соответствующим правом.</p>"
            "<div style='display:flex;gap:10px;margin-top:12px;'>"
            "<a href='/' style='background:#27272a;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;'>← Назад в Кассу</a>"
            "<a href='/logout' style='background:#ff6900;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:bold;'>Ввести другой ПИН-код</a>"
            "</div></div>",
            403
        )
    return wrapper

@app.route('/manifest.json')
def manifest():
    return send_from_directory(BASE_DIR, 'manifest.json')

@app.route('/chat_manifest.json')
def chat_manifest():
    return send_from_directory(BASE_DIR, 'chat_manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory(BASE_DIR, 'sw.js')

def is_shop_open():
    status = get_setting('shop_status', 'auto')
    if status == 'closed':
        return False
    if status == 'open':
        return True
    try:
        now = datetime.now().time()
        t_start = datetime.strptime(get_setting('work_start', '10:00'), "%H:%M").time()
        t_end = datetime.strptime(get_setting('work_end', '21:30'), "%H:%M").time()
        return t_start <= now <= t_end
    except Exception:
        return True

def init_db():
    db = sqlite3.connect(DB_PATH, timeout=20.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.commit()
    db.close()

def check_and_apply_autostop(db):
    zero_ings = db.execute("SELECT id FROM ingredients WHERE stock <= 0").fetchall()
    if not zero_ings:
        return
    ing_ids = [str(r['id']) for r in zero_ings]
    placeholders = ','.join(['?'] * len(ing_ids))
    menu_to_stop = db.execute(f"SELECT DISTINCT menu_id FROM recipes WHERE ingredient_id IN ({placeholders})", ing_ids).fetchall()
    for m in menu_to_stop:
        db.execute("UPDATE menu SET stop_list=1 WHERE id=?", (m['menu_id'],))

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
        returned_qty = abs(float(lg['change_amount'] or 0))
        if returned_qty > 0 and lg['ingredient_id']:
            db.execute("UPDATE ingredients SET stock = stock + ? WHERE id=?", (returned_qty, lg['ingredient_id']))
            db.execute("""
                INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username, order_id)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (now_s, lg['ingredient_id'], lg['ing_name'], returned_qty, 'возврат', reason_label, -abs(float(lg['cost_impact'] or 0)), 'system', order_id))
    # Помечаем старые записи продажи этого заказа как скорректированные, чтобы не вернуть дважды
    db.execute("UPDATE stock_logs SET op_type='продажа_архив' WHERE order_id=? AND op_type='продажа'", (order_id,))

def deduct_ingredients_and_calc_cost(db, items, order_id=None):
    total_cost = 0.0
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i in items:
        m_id = i.get('id') or i.get('menu_id')
        qty = int(i.get('qty', 1))
        if not m_id:
            continue
        recipes = db.execute("""
            SELECT r.ingredient_id, r.amount, i.name, i.stock, i.cost_price
            FROM recipes r JOIN ingredients i ON r.ingredient_id = i.id
            WHERE r.menu_id=?
        """, (m_id,)).fetchall()
        if recipes:
            for r in recipes:
                needed = float(r['amount']) * qty
                c_price = float(r['cost_price'] or 0)
                item_c = needed * c_price
                total_cost += item_c
                db.execute("UPDATE ingredients SET stock = stock - ? WHERE id=?", (needed, r['ingredient_id']))
                check_and_apply_autostop(db)
                db.execute("""
                    INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username, order_id)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (now_s, r['ingredient_id'], r['name'], -needed, 'продажа', f"Заказ #{order_id or 'новый'}", item_c, 'system', order_id))
        else:
            total_cost += float(i.get('price', 0)) * qty * 0.27
    return round(total_cost, 2)

def get_open_shift():
    return get_db().execute("SELECT * FROM shifts WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()

def calculate_shift_metrics(db, shift_id):
    shift = db.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
    if not shift:
        return None
    orders = db.execute("SELECT total, payment_method, payment_cash, payment_card FROM orders WHERE shift_id=? AND status!='cancelled'", (shift_id,)).fetchall()
    total_orders = len(orders)
    total_revenue = 0
    total_cash = 0
    total_card = 0
    for o in orders:
        t = int(o['total'] or 0)
        total_revenue += t
        pm = (o['payment_method'] or '').lower()
        if pm in ('наличные', 'cash'):
            total_cash += t
        elif pm in ('микс', 'mix'):
            c_part = int(o['payment_cash'] or (t // 2))
            total_cash += c_part
            total_card += max(0, t - c_part)
        else:
            total_card += t

    ops = db.execute("SELECT op_type, COALESCE(SUM(amount),0) s FROM cash_operations WHERE shift_id=? GROUP BY op_type", (shift_id,)).fetchall()
    cash_in = 0
    cash_out = 0
    for op in ops:
        if op['op_type'] == 'in':
            cash_in = int(op['s'] or 0)
        elif op['op_type'] == 'out':
            cash_out = int(op['s'] or 0)

    opening_cash = int(shift['opening_cash'] or 0)
    expected_cash = opening_cash + total_cash + cash_in - cash_out

    return {
        "id": shift['id'],
        "status": shift['status'],
        "opened_at": shift['opened_at'],
        "closed_at": shift['closed_at'],
        "opening_cash": opening_cash,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "total_cash": total_cash,
        "total_card": total_card,
        "cash_in": cash_in,
        "cash_out": cash_out,
        "expected_cash": expected_cash,
        "actual_cash": int(shift['actual_cash'] or 0),
        "discrepancy": int(shift['discrepancy'] or 0)
    }

LOGIN_ATTEMPTS = {}

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    client_ip = request.remote_addr or '127.0.0.1'
    now_ts = time.time()
    rec = LOGIN_ATTEMPTS.get(client_ip, {"fails": 0, "lock_until": 0})

    if now_ts < rec["lock_until"]:
        wait_sec = int(rec["lock_until"] - now_ts)
        return render_template('login.html', error=f"Слишком много неверных попыток. Подождите {wait_sec} сек.")

    if request.method == 'POST':
        pin = (request.form.get('pin_code') or request.form.get('password') or '').strip()
        if not (pin.isdigit() and 4 <= len(pin) <= 6):
            error = "ПИН-код должен состоять из 4–6 цифр"
        else:
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE pin_code=? AND is_active=1", (pin,)).fetchone()
            if user:
                LOGIN_ATTEMPTS.pop(client_ip, None)
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['can_edit_menu'] = int(user['can_edit_menu'] or 0)
                session['can_give_discount'] = int(user['can_give_discount'] or 0)
                session['can_view_finance'] = int(user['can_view_finance'] or 0)
                if user['role'] == 'kitchen':
                    return redirect(url_for('kitchen'))
                elif user['role'] == 'courier':
                    return redirect(url_for('courier'))
                return redirect(url_for('index'))
            else:
                rec["fails"] += 1
                if rec["fails"] >= 5:
                    rec["lock_until"] = now_ts + 60
                    rec["fails"] = 0
                    error = "Терминал заблокирован на 60 сек. после 5 неверных попыток"
                else:
                    left = 5 - rec["fails"]
                    error = f"Неверный ПИН-код (осталось попыток: {left})"
                LOGIN_ATTEMPTS[client_ip] = rec
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/current_role')
def api_current_role():
    return jsonify({
        "role": session.get('role', 'admin'),
        "username": session.get('username', 'Администратор'),
        "can_edit_menu": session.get('can_edit_menu', 1),
        "can_give_discount": session.get('can_give_discount', 1),
        "can_view_finance": session.get('can_view_finance', 1)
    })

@app.route('/switch_role/<role>')
def switch_role(role):
    # Переключение роли — только администратор. Раньше любой сотрудник мог
    # повысить себя до admin одним GET-запросом.
    if session.get('role') != 'admin':
        return "Переключение роли доступно только администратору", 403
    if role not in ('admin', 'cashier'):
        return "Неизвестная роль", 400
    session['role'] = role
    return redirect(request.referrer or url_for('index'))

@app.route('/api/erp/live_metrics')
def api_erp_live_metrics():
    db = get_db()
    shift = get_open_shift()
    shift_rev = 0
    if shift:
        r = db.execute("SELECT COALESCE(SUM(total),0) s FROM orders WHERE shift_id=? AND status!='cancelled'", (shift['id'],)).fetchone()
        shift_rev = int(r['s'] or 0)
    active_kds = db.execute("SELECT COUNT(*) c FROM orders WHERE status IN ('new','cooking')").fetchone()['c']

    # Считаем реальное среднее время готовки по последним 30 готовым заказам
    timed_rows = db.execute("""
        SELECT cook_start_time, cook_end_time FROM orders
        WHERE cook_start_time IS NOT NULL AND cook_end_time IS NOT NULL
          AND cook_start_time != '' AND cook_end_time != ''
        ORDER BY id DESC LIMIT 30
    """).fetchall()
    durations = []
    for tr in timed_rows:
        try:
            t1 = datetime.strptime(tr['cook_start_time'][:19], "%Y-%m-%d %H:%M:%S")
            t2 = datetime.strptime(tr['cook_end_time'][:19], "%Y-%m-%d %H:%M:%S")
            sec = (t2 - t1).total_seconds()
            if 10 <= sec <= 7200:
                durations.append(sec)
        except Exception:
            pass
    if durations:
        avg_sec = int(sum(durations) / len(durations))
        avg_cook_str = f"{avg_sec // 60:02d}:{avg_sec % 60:02d}"
    else:
        avg_cook_str = "00:00"

    return jsonify({
        "shift_revenue": shift_rev,
        "active_kds": active_kds,
        "avg_cook_time": avg_cook_str
    })

@app.route('/api/recipe/<int:menu_id>')
def api_get_menu_recipe(menu_id):
    db = get_db()
    menu_item = db.execute("SELECT * FROM menu WHERE id=?", (menu_id,)).fetchone()
    if not menu_item:
        return jsonify({"error": "Блюдо не найдено"}), 404
    recipes = db.execute("""
        SELECT i.name, r.amount, i.unit
        FROM recipes r JOIN ingredients i ON r.ingredient_id = i.id
        WHERE r.menu_id=?
    """, (menu_id,)).fetchall()
    ingredients_list = []
    total_weight = 0
    for r in recipes:
        amt = float(r['amount'] or 0)
        unit = r['unit'] or 'г'
        if unit == 'кг':
            total_weight += amt * 1000
        elif unit == 'г':
            total_weight += amt
        ingredients_list.append({"name": r['name'], "amount": amt, "unit": unit})
    return jsonify({
        "name": menu_item['name'],
        "composition": menu_item['composition'] or 'Стандартный рецепт шеф-повара',
        "ingredients": ingredients_list,
        "output_weight": int(total_weight) if total_weight > 0 else 240
    })

@app.route('/api/shift/current')
def api_shift_current():
    db = get_db()
    shift = get_open_shift()
    if not shift:
        return jsonify({"open": False})
    metrics = calculate_shift_metrics(db, shift['id'])
    ops = [dict(r) for r in db.execute("SELECT * FROM cash_operations WHERE shift_id=? ORDER BY id DESC", (shift['id'],)).fetchall()]
    return jsonify({"open": True, "shift": metrics, "ops": ops})

@app.route('/shift/z_report/<int:shift_id>')
def shift_z_report(shift_id):
    db = get_db()
    shift = db.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
    if not shift:
        return "Смена не найдена", 404
    metrics = calculate_shift_metrics(db, shift_id)
    if shift['status'] == 'closed':
        metrics['actual_cash'] = int(shift['actual_cash'] or 0)
        metrics['discrepancy'] = int(shift['discrepancy'] or 0)
    ops = db.execute("SELECT * FROM cash_operations WHERE shift_id=? ORDER BY id", (shift_id,)).fetchall()
    return render_template('z_report.html', shift=metrics, ops=ops)

@app.route('/shift/open', methods=['POST'])
def shift_open():
    db = get_db()
    if get_open_shift():
        if request.is_json:
            return jsonify({"success": True})
        return redirect(url_for('index'))
    data = request.get_json(force=True, silent=True) if request.is_json else request.form
    opening_cash = int((data or {}).get('opening_cash', 0) or 0)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("INSERT INTO shifts (opened_at, opened_by, status, opening_cash, expected_cash) VALUES (?,?, 'open', ?, ?)",
                     (now_str, session.get('user_id', 11), opening_cash, opening_cash))
    db.commit()
    if request.is_json:
        return jsonify({"success": True, "shift_id": cur.lastrowid})
    return redirect(url_for('index'))

@app.route('/shift/close', methods=['POST'])
def shift_close():
    db = get_db()
    shift = get_open_shift()
    if not shift:
        if request.is_json:
            return jsonify({"error": "Нет открытой смены"}), 400
        return redirect(url_for('index'))
    data = request.get_json(force=True, silent=True) if request.is_json else request.form
    metrics = calculate_shift_metrics(db, shift['id'])
    raw_actual = (data or {}).get('actual_cash', '')
    actual_cash = int(raw_actual) if str(raw_actual).strip() != '' else metrics['expected_cash']
    discrepancy = actual_cash - metrics['expected_cash']
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db.execute("""
        UPDATE shifts
        SET closed_at=?, closed_by=?, status='closed',
            total_orders=?, total_revenue=?, total_cash=?, total_card=?,
            cash_in=?, cash_out=?, expected_cash=?, actual_cash=?, discrepancy=?
        WHERE id=?
    """, (now_str, session.get('user_id', 11),
          metrics['total_orders'], metrics['total_revenue'], metrics['total_cash'], metrics['total_card'],
          metrics['cash_in'], metrics['cash_out'], metrics['expected_cash'], actual_cash, discrepancy,
          shift['id']))
    db.commit()
    if request.is_json:
        return jsonify({"success": True, "shift_id": shift['id'], "z_report_url": f"/shift/z_report/{shift['id']}"})
    return redirect(url_for('shift_z_report', shift_id=shift['id']))

@app.route('/api/cash_op', methods=['POST'])
def api_cash_op():
    shift = get_open_shift()
    if not shift:
        return jsonify({"error": "Смена не открыта"}), 400
    data = request.get_json(force=True, silent=True) or {}
    op_type = data.get('op_type', 'in')
    amount = int(data.get('amount', 0) or 0)
    comment = data.get('comment', '')
    if amount <= 0:
        return jsonify({"error": "Введите корректную сумму"}), 400
    db = get_db()
    db.execute("INSERT INTO cash_operations (shift_id, op_type, amount, comment, created_at, username) VALUES (?,?,?,?,?,?)",
               (shift['id'], op_type, amount, comment, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session.get('username', 'admin')))
    db.commit()
    return jsonify({"success": True})

@app.route('/api/demo/generate_order', methods=['POST'])
def api_generate_demo_order():
    db = get_db()
    rolls = db.execute("SELECT id, name, price FROM menu WHERE category='Роллы' AND available=1").fetchall()
    extras = db.execute("SELECT id, name, price FROM menu WHERE category='Дополнительно' AND available=1").fetchall()
    if not rolls:
        return jsonify({"error": "Меню пусто"}), 400
    picked = random.sample(list(rolls), min(2, len(rolls)))
    items = [{"id": r['id'], "name": r['name'], "price": r['price'], "qty": random.choice([1, 2]), "mods": "8 шт."} for r in picked]
    if extras:
        ex = random.choice(list(extras))
        items.append({"id": ex['id'], "name": ex['name'], "price": ex['price'], "qty": 2, "mods": ""})

    total = sum(i['price'] * i['qty'] for i in items)
    shift = get_open_shift()
    shift_id = shift['id'] if shift else 1
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = db.execute("""
        INSERT INTO orders (created_at, status, total, address, phone, comment, shift_id, cashier_id, source, payment_method, delivery_type, delivery_zone, payment_status, paid_at, is_fiscal)
        VALUES (?,?,?,?,?,?,?,?,11,'Сайт','карта','доставка','Центр','paid',?,1)
    """, (now_str, 'new', total, 'г. Инта, ул. Горького 14', '+7 (996) 637-18-06', 'Приборы: 2 перс.', shift_id, now_str))
    order_id = cur.lastrowid

    for i in items:
        db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                   (order_id, i['id'], i['name'], i['price'], i['qty'], i['mods']))
    total_cost = deduct_ingredients_and_calc_cost(db, items, order_id)
    db.execute("UPDATE orders SET cost=? WHERE id=?", (total_cost, order_id))
    db.commit()
    summary = ", ".join(f"{i['name']} x{i['qty']}" for i in items)
    return jsonify({"success": True, "order_id": order_id, "total": total, "summary": summary})

@app.route('/api/kds/recall_last', methods=['POST'])
def api_kds_recall_last():
    db = get_db()
    row = db.execute("SELECT id FROM orders WHERE status IN ('ready','done') ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return jsonify({"error": "Нет завершенных заказов для возврата"}), 404
    db.execute("UPDATE orders SET status='cooking' WHERE id=?", (row['id'],))
    db.commit()
    return jsonify({"success": True, "order_id": row['id']})

@app.route('/')
def index():
    db = get_db()
    menu = db.execute("SELECT * FROM menu WHERE available=1 ORDER BY sort_weight DESC, category, name").fetchall()
    categories = db.execute("SELECT DISTINCT category FROM menu WHERE available=1 ORDER BY category").fetchall()
    dzones = db.execute("SELECT id, name, CAST(fee AS INTEGER) as price, color, polygon_coords as polygon_data FROM delivery_zones WHERE is_active=1").fetchall()
    return render_template('cashier.html', menu=menu, categories=categories, zones=dzones,
                           shift=get_open_shift(), role=session.get('role', 'admin'), shop_open=is_shop_open())

@app.route('/kitchen')
def kitchen():
    return render_template('kitchen.html')

@app.route('/courier')
def courier():
    return render_template('courier.html')

@app.route('/reports')
def reports():
    return render_template('reports.html', shifts=get_db().execute("SELECT * FROM shifts ORDER BY id DESC LIMIT 30").fetchall())

@app.route('/orders')
def orders_view():
    return redirect('/?open_dispatcher=1')

@app.route('/receipt/<int:order_id>')
def receipt(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return "Заказ не найден", 404
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    return render_template('receipt.html', order=order, items=items)

@app.route('/ticket/<int:order_id>')
def ticket(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return "Заказ не найден", 404
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    return render_template('ticket.html', order=order, items=items)

@app.route('/api/order/update_items/<int:order_id>', methods=['POST'])
def update_order_items(order_id):
    data = request.get_json(force=True, silent=True) or {}
    new_items = data.get('items', [])
    if not new_items:
        return jsonify({"error": "В заказе должна остаться хотя бы одна позиция"}), 400
    db = get_db()
    restore_order_ingredients(db, order_id, f"Пересчёт состава заказа #{order_id}")
    db.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
    new_total = 0
    for i in new_items:
        qty = int(i.get('qty', 1))
        price = int(i['price'])
        new_total += price * qty
        db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                   (order_id, i.get('id'), i['name'], price, qty, i.get('mods', '')))
    new_cost = deduct_ingredients_and_calc_cost(db, new_items, order_id)
    db.execute("UPDATE orders SET total=?, cost=? WHERE id=?", (new_total, new_cost, order_id))
    db.commit()
    return jsonify({"success": True, "new_total": new_total})

@app.route('/api/all_orders')
def api_all_orders():
    db = get_db()
    date_filter = request.args.get('date', '').strip()
    status = request.args.get('status', '').strip()
    payment = request.args.get('payment', '').strip()

    if date_filter:
        cnt_on_date = db.execute("SELECT COUNT(*) FROM orders WHERE date(created_at) = ?", (date_filter,)).fetchone()[0]
        if cnt_on_date == 0:
            date_filter = ''

    query = "SELECT o.*, u.username as cashier_name FROM orders o LEFT JOIN users u ON o.cashier_id = u.id WHERE 1=1"
    params = []
    if date_filter:
        query += " AND date(o.created_at) = ?"
        params.append(date_filter)
    if status:
        query += " AND o.status = ?"
        params.append(status)
    if payment:
        if payment == 'наличные':
            query += " AND lower(o.payment_method) IN ('наличные', 'cash')"
        elif payment == 'карта':
            query += " AND lower(o.payment_method) IN ('карта', 'card')"
        elif payment == 'микс':
            query += " AND lower(o.payment_method) IN ('микс', 'mix')"
        elif payment == 'перевод':
            query += " AND lower(o.payment_method) IN ('перевод', 'transfer', 'sbp')"
        else:
            query += " AND o.payment_method = ?"
            params.append(payment)

    query += " ORDER BY o.id DESC LIMIT 100"
    rows = db.execute(query, params).fetchall()

    result = []
    total_sum = 0
    for r in rows:
        order = dict(r)
        order['items'] = [dict(i) for i in db.execute("SELECT * FROM order_items WHERE order_id=?", (r['id'],)).fetchall()]
        result.append(order)
        if order['status'] != 'cancelled':
            total_sum += order['total']
    valid_cnt = len([o for o in result if o['status'] != 'cancelled'])
    return jsonify({"orders": result, "stats": {"count": valid_cnt, "total": total_sum, "avg": round(total_sum / valid_cnt) if valid_cnt > 0 else 0}})

@app.route('/api/set_payment/<int:order_id>', methods=['POST'])
def set_payment(order_id):
    data = request.get_json(force=True, silent=True) or {}
    new_pay = data.get('payment_method', 'карта')
    auto_fisc = 0 if new_pay.lower() in ('наличные', 'cash') else 1
    db = get_db()
    db.execute("UPDATE orders SET payment_method=?, is_fiscal=? WHERE id=?", (new_pay, auto_fisc, order_id))
    db.commit()
    return jsonify({"success": True, "payment_method": new_pay, "is_fiscal": auto_fisc})

@app.route('/map')
@app.route('/zones_editor')
@admin_only
def map_view():
    return render_template('map.html', map_lat=get_setting('map_lat', '66.0350'), map_lng=get_setting('map_lng', '60.1450'))

@app.route('/api/zones', methods=['GET', 'POST'])
@admin_only
def api_zones():
    db = get_db()
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        name = data.get('name', 'Новая зона')
        price = float(data.get('price', 0) or 0)
        color = data.get('color', '#ff6900')
        poly = data.get('polygon_data') or '[]'
        db.execute("INSERT INTO delivery_zones (name, fee, color, polygon_coords, is_active) VALUES (?,?,?,?,1)", (name, price, color, poly))
        db.commit()
        return jsonify({"success": True})
    dz = db.execute("SELECT id, name, CAST(fee AS INTEGER) as price, color, polygon_coords as polygon_data FROM delivery_zones WHERE is_active=1").fetchall()
    return jsonify([dict(z) for z in dz])

@app.route('/api/zones/delete/<int:zone_id>', methods=['POST'])
@admin_only
def api_zones_delete(zone_id):
    db = get_db()
    db.execute("DELETE FROM delivery_zones WHERE id=?", (zone_id,))
    db.commit()
    return jsonify({"success": True})

@app.route('/api/courier/location', methods=['POST'])
def api_courier_location():
    data = request.get_json(force=True, silent=True) or {}
    lat, lng = data.get('lat'), data.get('lng')
    if lat and lng:
        db = get_db()
        now_s = datetime.now().strftime("%H:%M:%S")
        db.execute("INSERT INTO courier_locations (courier_id, lat, lng, updated_at) VALUES (?,?,?,?) ON CONFLICT(courier_id) DO UPDATE SET lat=?, lng=?, updated_at=?",
                   (session.get('user_id', 4), lat, lng, now_s, lat, lng, now_s))
        db.commit()
    return jsonify({"success": True})

@app.route('/api/couriers/locations')
def api_couriers_locations():
    return jsonify([dict(r) for r in get_db().execute("SELECT c.lat, c.lng, c.updated_at, u.username FROM courier_locations c LEFT JOIN users u ON c.courier_id = u.id").fetchall()])

@app.route('/chat')
def chat_view():
    return render_template('chat.html')

@app.route('/api/chat/get')
def api_chat_get():
    db = get_db()
    msgs = db.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 50").fetchall()
    return jsonify({"messages": [dict(m) for m in reversed(msgs)], "typing": []})

@app.route('/api/chat/send', methods=['POST'])
def api_chat_send():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get('text', '').strip()
    if text:
        db = get_db()
        db.execute("INSERT INTO messages (sender_id, sender_name, text, created_at, is_read) VALUES (?,?,?,?,0)",
                   (session.get('user_id', 11), session.get('username', 'admin'), text, datetime.now().strftime("%H:%M")))
        db.commit()
    return jsonify({"success": True})

@app.route('/api/chat/typing', methods=['POST'])
def api_chat_typing():
    return jsonify({"success": True})

@app.route('/api/chat/clear', methods=['POST'])
def api_chat_clear():
    db = get_db()
    db.execute("DELETE FROM messages")
    db.commit()
    return jsonify({"success": True})

@app.route('/crm')
@admin_only
def crm_panel():
    return render_template('crm.html', clients=get_db().execute("SELECT * FROM clients ORDER BY total_spent DESC").fetchall())

@app.route('/warehouse')
@admin_only
def warehouse_panel():
    db = get_db()
    return render_template('warehouse.html',
                           ingredients=db.execute("SELECT * FROM ingredients ORDER BY name").fetchall(),
                           logs=db.execute("SELECT * FROM stock_logs ORDER BY id DESC LIMIT 30").fetchall())

@app.route('/admin/ingredient/add', methods=['POST'])
@admin_only
def admin_ingredient_add():
    name = request.form.get('name', '').strip()
    stock = float(request.form.get('stock', 0) or 0)
    unit = request.form.get('unit', 'г').strip()
    cost_price = float(request.form.get('cost_price', 0) or 0)
    is_prep = int(request.form.get('is_prep', 0) or 0)
    if name:
        db = get_db()
        cur = db.execute("INSERT INTO ingredients (name, stock, unit, cost_price, is_prep) VALUES (?,?,?,?,?)", (name, stock, unit, cost_price, is_prep))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), cur.lastrowid, name, stock, 'приход', 'Начальный остаток', stock * cost_price, 'admin'))
        db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/admin/ingredient/adjust', methods=['POST'])
@admin_only
def admin_ingredient_adjust():
    ing_id = int(request.form.get('ingredient_id', 0) or 0)
    delta = float(request.form.get('amount', 0) or 0)
    op_type = request.form.get('op_type', 'приход')
    reason = request.form.get('reason', 'Корректировка')
    db = get_db()
    ing = db.execute("SELECT * FROM ingredients WHERE id=?", (ing_id,)).fetchone()
    if ing and delta != 0:
        actual = delta if op_type == 'приход' else -abs(delta)
        db.execute("UPDATE ingredients SET stock = stock + ? WHERE id=?", (actual, ing_id))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), ing_id, ing['name'], actual, op_type, reason, abs(actual) * (ing['cost_price'] or 0), 'admin'))
        db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/admin/ingredient/produce_prep', methods=['POST'])
@admin_only
def admin_produce_prep():
    raw_id = int(request.form.get('raw_id', 0) or 0)
    prep_id = int(request.form.get('prep_id', 0) or 0)
    raw_amt = float(request.form.get('raw_amount', 0) or 0)
    prep_amt = float(request.form.get('prep_amount', 0) or 0)
    if raw_id and prep_id and raw_amt > 0 and prep_amt > 0:
        db = get_db()
        raw_ing = db.execute("SELECT * FROM ingredients WHERE id=?", (raw_id,)).fetchone()
        prep_ing = db.execute("SELECT * FROM ingredients WHERE id=?", (prep_id,)).fetchone()
        if raw_ing and prep_ing:
            now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
            db.execute("UPDATE ingredients SET stock = stock - ? WHERE id=?", (raw_amt, raw_id))
            db.execute("UPDATE ingredients SET stock = stock + ? WHERE id=?", (prep_amt, prep_id))
            db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, username) VALUES (?,?,?,?,?,?,?)",
                       (now_s, raw_id, raw_ing['name'], -raw_amt, 'проработка', f"На П/Ф: {prep_ing['name']}", 'admin'))
            db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, username) VALUES (?,?,?,?,?,?,?)",
                       (now_s, prep_id, prep_ing['name'], prep_amt, 'приход п/ф', f"Из сырья: {raw_ing['name']}", 'admin'))
            db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/admin/ingredient/inventory_check', methods=['POST'])
@admin_only
def admin_inventory_check():
    ing_id = int(request.form.get('ingredient_id', 0) or 0)
    actual = float(request.form.get('actual_stock', 0) or 0)
    db = get_db()
    ing = db.execute("SELECT * FROM ingredients WHERE id=?", (ing_id,)).fetchone()
    if ing:
        diff = round(actual - float(ing['stock'] or 0), 2)
        if diff != 0:
            db.execute("UPDATE ingredients SET stock=? WHERE id=?", (actual, ing_id))
            op_label = 'излишек ревизии' if diff > 0 else 'недостача ревизии'
            db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M"), ing_id, ing['name'], diff, op_label, f"Инвентаризация (факт: {actual})", abs(diff) * float(ing['cost_price'] or 0), 'admin'))
            db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/admin/ingredient/delete/<int:ing_id>', methods=['POST'])
@admin_only
def admin_ingredient_delete(ing_id):
    db = get_db()
    db.execute("DELETE FROM ingredients WHERE id=?", (ing_id,))
    db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/analytics')
@admin_only
def analytics_panel():
    db = get_db()
    stats = db.execute("""
        SELECT SUM(total) as rev,
               SUM(CASE WHEN cost IS NULL OR cost <= 0 THEN total * 0.27 ELSE cost END) as cost
        FROM orders WHERE status != 'cancelled'
    """).fetchone()
    total_rev = int(stats['rev'] or 0)
    raw_cost = float(stats['cost'] or 0)
    total_cost = round(raw_cost, 1)
    total_profit = round(total_rev - total_cost, 1)
    margin = round((total_profit / total_rev * 100) if total_rev > 0 else 0, 1)

    rows_abc = db.execute("""
        SELECT oi.name, SUM(oi.qty) as qty, SUM(oi.price * oi.qty) as rev
        FROM order_items oi JOIN orders o ON oi.order_id = o.id
        WHERE o.status != 'cancelled'
        GROUP BY oi.name ORDER BY rev DESC
    """).fetchall()
    sum_items_rev = sum(r['rev'] for r in rows_abc) or 1
    cum_share = 0
    abc_items = []
    for r in rows_abc:
        sh = round(r['rev'] / sum_items_rev * 100, 1)
        cum_share += sh
        grp = 'A' if cum_share <= 80 else ('B' if cum_share <= 95 else 'C')
        abc_items.append({"name": r['name'], "qty": r['qty'], "rev": r['rev'], "share": sh, "abc": grp})

    by_source = db.execute("SELECT COALESCE(source,'Касса') as source, COUNT(*) as cnt, COALESCE(SUM(total),0) as rev FROM orders WHERE status!='cancelled' GROUP BY COALESCE(source,'Касса')").fetchall()
    by_payment = db.execute("SELECT payment_method as method, COUNT(*) as cnt, COALESCE(SUM(total),0) as rev FROM orders WHERE status!='cancelled' GROUP BY payment_method").fetchall()

    return render_template('analytics.html', total_rev=total_rev, total_cost=total_cost,
                           total_profit=total_profit, margin=margin,
                           abc_items=abc_items, by_source=by_source, by_payment=by_payment,
                           recent_orders=db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 20").fetchall())

@app.route('/track/<int:order_id>')
def track_order(order_id):
    return render_template('track.html', order_id=order_id)

@app.route('/api/track_order/<int:order_id>')
def api_track_order(order_id):
    order = get_db().execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "status": order['status'],
        "total": order['total'],
        "created_at": order['created_at'],
        "delivery_type": order['delivery_type'] or 'доставка',
        "address": order['address'] or ''
    })

@app.route('/rate/<int:order_id>', methods=['GET', 'POST'])
def rate_order(order_id):
    db = get_db()
    if request.method == 'POST':
        try:
            rating = int(request.form.get('rating', 0))
        except (TypeError, ValueError):
            rating = 0
        rating = max(1, min(5, rating))
        review_text = (request.form.get('review_text') or '').strip()[:500]
        order = db.execute("SELECT id, status FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order or order['status'] not in ('done', 'delivered'):
            return "Оценить можно только выполненный заказ", 400
        db.execute("UPDATE orders SET rating=?, review_text=? WHERE id=?",
                   (rating, review_text, order_id))
        db.commit()
        return redirect(url_for('public_site'))
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return "Заказ не найден", 404
    return render_template('rate.html', order=order)

@app.route('/admin/shop_status', methods=['POST'])
@admin_only
def admin_shop_status():
    if request.form.get('status') in ['auto', 'open', 'closed']:
        set_setting('shop_status', request.form.get('status'))
    return redirect(url_for('admin_panel'))

@app.route('/admin/backup_db')
@admin_only
def backup_db():
    db = get_db()
    try:
        db.execute("PRAGMA wal_checkpoint(FULL)")
    except Exception:
        pass
    return send_file(DB_PATH, as_attachment=True, download_name=f"sushi_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")

@app.route('/admin/export/orders')
@admin_only
def export_orders():
    db = get_db()
    orders = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    if openpyxl:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Заказы"
        ws.append(["ID", "Дата", "Клиент", "Адрес", "Тип", "Сумма", "Себестоимость", "Оплата", "Статус"])
        for o in orders:
            ws.append([o['id'], o['created_at'], o['phone'], o['address'], o['delivery_type'], o['total'], o['cost'], o['payment_method'], o['status']])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=orders.xlsx"
        response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return response
    return redirect(url_for('analytics_panel'))

@app.route('/admin/export/clients')
@admin_only
def export_clients():
    db = get_db()
    clients = db.execute("SELECT * FROM clients ORDER BY total_spent DESC").fetchall()
    if openpyxl:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Клиенты"
        ws.append(["Телефон", "Заказов", "Потрачено (LTV)", "Последний заказ"])
        for c in clients:
            ws.append([c['phone'], c['orders_count'], c['total_spent'], c['last_order_at']])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=clients.xlsx"
        response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return response
    return redirect(url_for('crm_panel'))

@app.route('/admin')
@admin_only
def admin_panel():
    db = get_db()
    stats = db.execute("SELECT COUNT(*) cnt, COALESCE(SUM(total), 0) rev FROM orders WHERE status != 'cancelled'").fetchone()
    avg_check = (stats['rev'] / stats['cnt']) if stats['cnt'] > 0 else 0
    chart_data = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        r = db.execute("SELECT COALESCE(SUM(total),0) rev FROM orders WHERE date(created_at)=? AND status!='cancelled'", (d,)).fetchone()
        chart_data.append({"date": d[5:], "rev": r['rev']})
    chart_max = max([d['rev'] for d in chart_data] + [1])
    top_items = db.execute("SELECT oi.name, SUM(oi.qty) total_qty FROM order_items oi JOIN orders o ON oi.order_id = o.id WHERE o.status != 'cancelled' GROUP BY oi.name ORDER BY total_qty DESC LIMIT 5").fetchall()
    top_clients = db.execute("SELECT phone, COUNT(*) cnt, SUM(total) sum FROM orders WHERE status != 'cancelled' AND phone != '' GROUP BY phone ORDER BY sum DESC LIMIT 5").fetchall()
    return render_template(
        'admin.html',
        stats=stats, avg_check=avg_check, chart_data=chart_data, chart_max=chart_max,
        top_items=top_items, top_clients=top_clients,
        menu=db.execute("SELECT * FROM menu ORDER BY sort_weight DESC, category, name").fetchall(),
        users=db.execute("SELECT id, username, role, pin_code, can_edit_menu, can_give_discount, can_view_finance, created_at FROM users ORDER BY id").fetchall(),
        zones=db.execute("SELECT * FROM delivery_zones").fetchall(),
        promos=db.execute("SELECT * FROM promocodes ORDER BY id DESC").fetchall(),
        avg_rating=5.0, reviews_count=14,
        recent_reviews=db.execute("SELECT * FROM orders WHERE rating > 0 ORDER BY id DESC LIMIT 5").fetchall(),
        shop_status=get_setting('shop_status', 'open'),
        banners=db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall()
    )

@app.route('/admin/users/add', methods=['POST'])
@admin_only
def admin_user_add():
    username = request.form.get('username', '').strip()
    pin_code = request.form.get('pin_code', '').strip()
    role = request.form.get('role', 'cashier')
    can_edit_menu = 1 if (role == 'admin' or request.form.get('can_edit_menu') == '1') else 0
    can_give_discount = 1 if (role == 'admin' or request.form.get('can_give_discount') == '1') else 0
    can_view_finance = 1 if (role == 'admin' or request.form.get('can_view_finance') == '1') else 0

    if not re.match(r'^\d{4,6}$', pin_code):
        return redirect(url_for('admin_panel', pin_err='ПИН-код должен содержать от 4 до 6 цифр'))

    db = get_db()
    dup = db.execute("SELECT id FROM users WHERE pin_code=?", (pin_code,)).fetchone()
    if dup:
        return redirect(url_for('admin_panel', pin_err='Этот ПИН-код уже занят другим сотрудником'))

    if username:
        try:
            db.execute("""
                INSERT INTO users (username, password_hash, role, created_at, pin_code, can_edit_menu, can_give_discount, can_view_finance)
                VALUES (?, 'pin-auth', ?, ?, ?, ?, ?, ?)
            """, (username, role, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pin_code, can_edit_menu, can_give_discount, can_view_finance))
            db.commit()
            return redirect(url_for('admin_panel', pin_msg=f'Сотрудник {username} (ПИН: {pin_code}) добавлен'))
        except sqlite3.IntegrityError:
            return redirect(url_for('admin_panel', pin_err='Сотрудник с таким именем уже существует'))
    return redirect(url_for('admin_panel'))

@app.route('/admin/users/update/<int:user_id>', methods=['POST'])
@admin_only
def admin_user_update(user_id):
    username = request.form.get('username', '').strip()
    pin_code = request.form.get('pin_code', '').strip()
    role = request.form.get('role', 'cashier')
    can_edit_menu = 1 if (role == 'admin' or request.form.get('can_edit_menu') == '1') else 0
    can_give_discount = 1 if (role == 'admin' or request.form.get('can_give_discount') == '1') else 0
    can_view_finance = 1 if (role == 'admin' or request.form.get('can_view_finance') == '1') else 0

    if not re.match(r'^\d{4,6}$', pin_code):
        return redirect(url_for('admin_panel', pin_err='ПИН-код должен быть от 4 до 6 цифр'))

    db = get_db()
    dup = db.execute("SELECT id FROM users WHERE pin_code=? AND id!=?", (pin_code, user_id)).fetchone()
    if dup:
        return redirect(url_for('admin_panel', pin_err='Этот ПИН-код уже назначен другому сотруднику'))

    db.execute("""
        UPDATE users
        SET username=?, pin_code=?, role=?, can_edit_menu=?, can_give_discount=?, can_view_finance=?
        WHERE id=?
    """, (username, pin_code, role, can_edit_menu, can_give_discount, can_view_finance, user_id))
    db.commit()

    if session.get('user_id') == user_id:
        session['username'] = username
        session['role'] = role
        session['can_edit_menu'] = can_edit_menu
        session['can_give_discount'] = can_give_discount
        session['can_view_finance'] = can_view_finance

    return redirect(url_for('admin_panel', pin_msg=f'ПИН и права сотрудника {username} сохранены'))

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@admin_only
def admin_user_delete(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    return redirect(url_for('admin_panel', pin_msg='Сотрудник удалён'))

@app.route('/api/check_promo', methods=['POST'])
def check_promo():
    data = request.get_json(force=True, silent=True) or {}
    code = data.get('code', '').strip().upper()
    promo = get_db().execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (code,)).fetchone()
    if promo:
        return jsonify({"success": True, "type": promo['discount_type'], "value": promo['discount_value']})
    return jsonify({"success": False, "error": "Промокод не найден"})

@app.route('/admin/promo/add', methods=['POST'])
@admin_only
def admin_promo_add():
    code = request.form.get('code', '').strip().upper()
    dtype = request.form.get('type', 'percent')
    val = request.form.get('value', 10)
    if code and val:
        db = get_db()
        try:
            db.execute("INSERT INTO promocodes (code, discount_type, discount_value) VALUES (?,?,?)", (code, dtype, int(val)))
            db.commit()
        except sqlite3.IntegrityError:
            pass
    return redirect(url_for('admin_panel'))

@app.route('/admin/promo/delete/<int:promo_id>', methods=['POST'])
@admin_only
def admin_promo_delete(promo_id):
    db = get_db()
    db.execute("DELETE FROM promocodes WHERE id=?", (promo_id,))
    db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/menu/add', methods=['POST'])
@admin_only
def admin_menu_add():
    name = request.form.get('name', '').strip()
    price = request.form.get('price', 0)
    category = request.form.get('category', 'Роллы').strip()
    composition = request.form.get('composition', '').strip()
    if category == 'Роллы' and '8' not in composition:
        composition = (composition + ' • 8 кусочков').strip(' •')
    file = request.files.get('image')
    filename = save_menu_image(file)
    if name and price and category:
        db = get_db()
        db.execute("INSERT INTO menu (name, price, category, image, composition, modifiers, sort_weight) VALUES (?,?,?,?,?,?,?)",
                   (name, int(price), category, filename, composition, request.form.get('modifiers', ''), int(request.form.get('sort_weight', 0) or 0)))
        db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/menu/edit/<int:menu_id>', methods=['GET', 'POST'])
@admin_only
def admin_menu_edit(menu_id):
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        price = int(request.form.get('price', 0) or 0)
        category = request.form.get('category', 'Роллы').strip()
        composition = request.form.get('composition', '').strip()
        modifiers = request.form.get('modifiers', '').strip()
        sort_weight = int(request.form.get('sort_weight', 0) or 0)
        file = request.files.get('image')
        filename = save_menu_image(file)
        if filename:
            db.execute("UPDATE menu SET name=?, price=?, category=?, composition=?, modifiers=?, image=?, sort_weight=? WHERE id=?",
                       (name, price, category, composition, modifiers, filename, sort_weight, menu_id))
        else:
            db.execute("UPDATE menu SET name=?, price=?, category=?, composition=?, modifiers=?, sort_weight=? WHERE id=?",
                       (name, price, category, composition, modifiers, sort_weight, menu_id))
        db.execute("DELETE FROM recipes WHERE menu_id=?", (menu_id,))
        for key, val in request.form.items():
            if key.startswith('ing_') and val.strip():
                db.execute("INSERT INTO recipes (menu_id, ingredient_id, amount) VALUES (?,?,?)",
                           (menu_id, int(key.split('_')[1]), float(val)))
        db.commit()
        return redirect(url_for('admin_panel'))
    return render_template(
        'edit_menu.html',
        item=db.execute("SELECT * FROM menu WHERE id=?", (menu_id,)).fetchone(),
        ingredients=db.execute("SELECT * FROM ingredients ORDER BY name").fetchall(),
        recipe={r['ingredient_id']: r['amount'] for r in db.execute("SELECT * FROM recipes WHERE menu_id=?", (menu_id,)).fetchall()}
    )

@app.route('/admin/menu/stop/<int:menu_id>', methods=['POST'])
@admin_only
def admin_menu_stop(menu_id):
    db = get_db()
    db.execute("UPDATE menu SET stop_list = 1 - stop_list WHERE id=?", (menu_id,))
    db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/menu/delete/<int:menu_id>', methods=['POST'])
@admin_only
def admin_menu_delete(menu_id):
    db = get_db()
    db.execute("DELETE FROM menu WHERE id=?", (menu_id,))
    db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/site')
def public_site():
    db = get_db()
    menu = db.execute("SELECT * FROM menu WHERE available=1 ORDER BY sort_weight DESC, category, name").fetchall()
    categories = db.execute("SELECT DISTINCT category FROM menu WHERE available=1 ORDER BY category").fetchall()
    banners = db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall()
    zones = db.execute("SELECT id, name, CAST(fee AS INTEGER) as price, color FROM delivery_zones WHERE is_active=1").fetchall()
    return render_template('public_site.html', menu=menu, categories=categories, shop_open=is_shop_open(), shop_status=get_setting('shop_status', 'auto'), banners=banners, zones=zones)

@app.route('/api/public_order', methods=['POST'])
def public_order():
    data = request.get_json(force=True, silent=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({"error": "Пустой заказ"}), 400
    db = get_db()
    shift = get_open_shift()
    shift_id = shift['id'] if shift else 1
    subtotal = sum(int(i['price']) * int(i.get('qty', 1)) for i in items)
    promo_code = data.get('promo_code', '').strip().upper()
    promo_discount = 0
    if promo_code:
        promo = db.execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (promo_code,)).fetchone()
        if promo:
            promo_discount = (subtotal * promo['discount_value']) // 100 if promo['discount_type'] == 'percent' else promo['discount_value']
    delivery_type = data.get('delivery_type', 'доставка')
    delivery_price = int(data.get('delivery_price', 0) or 0) if delivery_type == 'доставка' else 0
    total = max(0, subtotal - promo_discount) + delivery_price
    phone = data.get('phone', '').strip()
    address = 'Самовывоз' if delivery_type == 'самовывоз' else data.get('address', '').strip()
    pay_method = data.get('payment_method', 'карта')
    change_from = int(data.get('change_from', 0) or 0)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_cost = 0.0
    auto_fiscal = 0 if pay_method.lower() in ('наличные', 'cash') else 1

    cur = db.execute("""
        INSERT INTO orders (created_at, status, total, cost, address, phone, comment, shift_id,
                            payment_method, change_from, delivery_type, delivery_price, promo_code, source, payment_status, paid_at, is_fiscal)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'Сайт','paid',?,?)
    """, (now_str, 'new', total, total_cost, address, phone, data.get('comment', ''), shift_id, pay_method, change_from, delivery_type, delivery_price, promo_code, now_str, auto_fiscal))
    order_id = cur.lastrowid

    for i in items:
        db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                   (order_id, i.get('id'), i['name'], int(i['price']), int(i.get('qty', 1)), i.get('mods', '')))
    if total_cost == 0.0:
        total_cost = deduct_ingredients_and_calc_cost(db, items, order_id)
        db.execute("UPDATE orders SET cost=? WHERE id=?", (total_cost, order_id))

    if phone:
        db.execute("""
            INSERT INTO clients (phone, total_spent, orders_count, last_order_at, level, bonuses)
            VALUES (?,?,1,?,'bronze',0)
            ON CONFLICT(phone) DO UPDATE SET
                total_spent=total_spent+?, orders_count=orders_count+1, last_order_at=?
        """, (phone, total, now_str, total, now_str))

    db.commit()
    return jsonify({"success": True, "order_id": order_id})

@app.route('/api/site/client/<phone>')
def site_client(phone):
    order = get_db().execute("SELECT * FROM orders WHERE phone=? ORDER BY id DESC LIMIT 1", (phone,)).fetchone()
    if order:
        items = [dict(i) for i in get_db().execute("SELECT * FROM order_items WHERE order_id=?", (order['id'],)).fetchall()]
        return jsonify({"success": True, "address": order['address'], "last_order": items})
    return jsonify({"success": False})

@app.route('/api/client/<phone>')
def api_client(phone):
    client = get_db().execute("SELECT * FROM clients WHERE phone=?", (phone,)).fetchone()
    if client:
        return jsonify({"success": True, "bonuses": 0, "level": client['level']})
    return jsonify({"success": False})

@app.route('/api/create_order', methods=['POST'])
def create_order():
    data = request.get_json(force=True, silent=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({"error": "Пустой заказ"}), 400
    db = get_db()
    shift = get_open_shift()
    if not shift:
        return jsonify({"error": "Смена закрыта! Сначала откройте кассовую смену.", "need_open_shift": True}), 400
    shift_id = shift['id']
    phone = data.get('phone', '').strip()
    address = data.get('address', '').strip()
    subtotal = sum(int(i['price']) * int(i.get('qty', 1)) for i in items)
    manual_discount = (subtotal * int(data.get('discount', 0)) // 100) if data.get('discount_type') == 'percent' else int(data.get('discount', 0) or 0)
    after_disc = max(0, subtotal - manual_discount)
    delivery_type = data.get('delivery_type', 'доставка')
    delivery_price = 150 if (delivery_type == 'доставка' and 0 < after_disc < 1200) else 0
    total = after_disc + delivery_price

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_cost = 0.0
    pm_val = data.get('payment_method', 'карта')
    auto_fiscal = 0 if pm_val.lower() in ('наличные', 'cash') else 1

    cur = db.execute("""
        INSERT INTO orders (created_at, status, total, cost, address, phone, comment, shift_id, cashier_id, source, payment_method, delivery_type, delivery_price, scheduled_time, payment_status, paid_at, is_fiscal)
        VALUES (?,?,?,?,?,?,?,?,?,'Касса',?,?,?,?, 'paid',?,?)
    """, (now_str, 'new', total, total_cost, address, phone, data.get('comment', ''), shift_id, session.get('user_id', 11), pm_val, delivery_type, delivery_price, data.get('scheduled_time', ''), now_str, auto_fiscal))
    order_id = cur.lastrowid
    for i in items:
        db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                   (order_id, i.get('id'), i['name'], int(i['price']), int(i.get('qty', 1)), i.get('mods', '')))
    if total_cost == 0.0:
        total_cost = deduct_ingredients_and_calc_cost(db, items, order_id)
        db.execute("UPDATE orders SET cost=? WHERE id=?", (total_cost, order_id))
    if phone:
        db.execute("""
            INSERT INTO clients (phone, total_spent, orders_count, last_order_at, level, bonuses)
            VALUES (?,?,1,?,'bronze',0)
            ON CONFLICT(phone) DO UPDATE SET
                total_spent=total_spent+?, orders_count=orders_count+1, last_order_at=?
        """, (phone, total, now_str, total, now_str))
    db.commit()
    return jsonify({"success": True, "order_id": order_id, "total": total})

@app.route('/api/orders')
def api_orders():
    status = request.args.get('status')
    db = get_db()
    if status == 'active':
        rows = db.execute("SELECT * FROM orders WHERE status IN ('new', 'cooking') ORDER BY id").fetchall()
    elif status == 'all_active':
        rows = db.execute("SELECT * FROM orders WHERE status IN ('new', 'cooking', 'ready', 'delivering') ORDER BY id").fetchall()
    elif status:
        rows = db.execute("SELECT * FROM orders WHERE status=? ORDER BY id", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50").fetchall()
    result = [dict(r) | {"items": [dict(i) for i in db.execute("SELECT * FROM order_items WHERE order_id=?", (r['id'],)).fetchall()]} for r in rows]
    return jsonify(result)

@app.route('/api/set_status/<int:order_id>', methods=['POST'])
def set_status(order_id):
    data = request.get_json(force=True, silent=True) or {}
    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "Статус не указан"}), 400
    db = get_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        old_row = db.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        old_status = old_row['status'] if old_row else ''
        if new_status == 'cancelled' and old_status != 'cancelled':
            restore_order_ingredients(db, order_id, f"Отмена заказа #{order_id}")
        if new_status == 'cooking':
            db.execute("UPDATE orders SET status=?, cook_start_time=COALESCE(cook_start_time, ?) WHERE id=?", (new_status, now_str, order_id))
        elif new_status in ('ready', 'done'):
            db.execute("UPDATE orders SET status=?, cook_end_time=COALESCE(cook_end_time, ?) WHERE id=?", (new_status, now_str, order_id))
        else:
            db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
        db.execute("INSERT INTO order_status_history (order_id, old_status, new_status, changed_at, comment) VALUES (?,?,?,?,?)",
                   (order_id, old_status, new_status, now_str, 'Обновлено'))
        db.commit()
        return jsonify({"success": True, "status": new_status})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

def generate_fns_qr_svg(qr_string):
    size = 25
    matrix = [[0 for _ in range(size)] for _ in range(size)]
    def draw_finder(r0, c0):
        for r in range(7):
            for c in range(7):
                if r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4):
                    matrix[r0 + r][c0 + c] = 1
    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)
    for i in range(8, size - 8):
        matrix[6][i] = (i + 1) % 2
        matrix[i][6] = (i + 1) % 2
    digest = hashlib.sha256(qr_string.encode('utf-8')).digest() + hashlib.md5(qr_string.encode('utf-8')).digest()
    bit_idx = 0
    for r in range(size):
        for c in range(size):
            if (r < 8 and c < 8) or (r < 8 and c >= size - 8) or (r >= size - 8 and c < 8) or r == 6 or c == 6:
                continue
            byte_val = digest[(bit_idx // 8) % len(digest)]
            matrix[r][c] = (byte_val >> (bit_idx % 8)) & 1
            bit_idx += 1
    scale = 5
    dim = size * scale
    rects = [f'<rect x="{c*scale}" y="{r*scale}" width="{scale}" height="{scale}" fill="#000"/>' for r in range(size) for c in range(size) if matrix[r][c]]
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" height="{dim}" viewBox="0 0 {dim} {dim}" style="background:#fff;padding:6px;border:1px solid #000;">{"".join(rects)}</svg>'

def get_fiscal_config():
    return {
        "org_name": get_setting("fiscal_org", "ИП Пирогов А.И."),
        "inn": get_setting("fiscal_inn", "110401234567"),
        "sno": get_setting("fiscal_sno", "ПАТЕНТ"),
        "rn_kkt": get_setting("fiscal_rn", "0004829103948102"),
        "zn_kkt": get_setting("fiscal_zn", "00109203847512"),
        "fn_num": get_setting("fiscal_fn", "9960440302841955"),
        "ofd_name": get_setting("fiscal_ofd", "ООО «Компания Тензор» (СБИС ОФД)"),
        "vat_label": get_setting("fiscal_vat", "БЕЗ НДС")
    }

@app.route('/fiscal/<int:order_id>')
def fiscal_receipt_view(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return "Заказ не найден", 404
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    fiscal_cfg = get_fiscal_config()
    total = int(order['total'] or 0)
    pm = (order['payment_method'] or 'карта').lower()
    if pm in ('наличные', 'cash'):
        pay_mode, cash_amount, card_amount = 'наличные', total, 0
    elif pm in ('микс', 'mix'):
        pay_mode = 'микс'
        cash_amount = int(order['payment_cash'] or (total // 2))
        card_amount = max(0, total - cash_amount)
    else:
        pay_mode, cash_amount, card_amount = 'карта', 0, total

    fd_number = 10000 + int(order['id'])
    raw_seed = f"{fiscal_cfg['fn_num']}:{fd_number}:{total}:{order['created_at']}"
    fpd = str(int(hashlib.sha256(raw_seed.encode()).hexdigest()[:10], 16))[:10].zfill(10)
    dt_clean = re.sub(r'[^0-9]', '', order['created_at'] or '')[:12]
    qr_t = f"{dt_clean[:8]}T{dt_clean[8:12]}" if len(dt_clean) >= 12 else datetime.now().strftime("%Y%m%dT%H%M")
    qr_raw = f"t={qr_t}&s={total}.00&fn={fiscal_cfg['fn_num']}&i={fd_number}&fp={fpd}&n=1"
    qr_svg = generate_fns_qr_svg(qr_raw)

    fiscal_data = {
        "fd_number": fd_number, "fpd": fpd, "fiscal_at": order['paid_at'] or order['created_at'],
        "cashier_name": session.get('username', 'Администратор'), "pay_mode": pay_mode,
        "cash_amount": cash_amount, "card_amount": card_amount, "qr_raw": qr_raw
    }
    return render_template('fiscal_receipt.html', order=order, items=items, fiscal=fiscal_data, fiscal_cfg=fiscal_cfg, qr_svg=qr_svg)

@app.route('/fiscal/<int:order_id>/update_payment', methods=['POST'])
def fiscal_update_payment(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return redirect(url_for('index'))
    total = int(order['total'] or 0)
    pm = request.form.get('payment_method', 'карта')
    if pm == 'наличные':
        cash_amt, card_amt = total, 0
    elif pm == 'микс':
        cash_amt = min(total, max(0, int(request.form.get('cash_amount', 0) or 0)))
        card_amt = max(0, total - cash_amt)
    else:
        cash_amt, card_amt = 0, total
    db.execute("UPDATE orders SET payment_method=?, payment_cash=?, payment_card=? WHERE id=?", (pm, cash_amt, card_amt, order_id))
    db.commit()
    return redirect(url_for('fiscal_receipt_view', order_id=order_id))

@app.route('/fiscal/settings/save', methods=['POST'])
@admin_only
def fiscal_settings_save():
    for k in ['fiscal_org', 'fiscal_inn', 'fiscal_sno', 'fiscal_rn', 'fiscal_fn', 'fiscal_ofd']:
        if k in request.form:
            set_setting(k, request.form.get(k, '').strip())
    return redirect(url_for('fiscal_receipt_view', order_id=request.form.get('order_id', 1)))

# --- БУХГАЛТЕРИЯ (БЕЛАЯ И УПРАВЛЕНЧЕСКАЯ) ---
def compute_dual_accounting(db, date_from='', date_to='', tax_mode='patent', acq_pct=1.8):
    q_orders = "SELECT * FROM orders WHERE status != 'cancelled'"
    q_exp = "SELECT * FROM accounting_expenses WHERE 1=1"
    q_cash_ops = "SELECT COALESCE(SUM(amount), 0) s FROM cash_operations WHERE op_type='out'"
    params = []

    if date_from:
        q_orders += " AND date(created_at) >= ?"
        q_exp += " AND date(created_at) >= ?"
        q_cash_ops += " AND date(created_at) >= ?"
        params.append(date_from)
    if date_to:
        q_orders += " AND date(created_at) <= ?"
        q_exp += " AND date(created_at) <= ?"
        q_cash_ops += " AND date(created_at) <= ?"
        params.append(date_to)

    q_orders += " ORDER BY id DESC"
    q_exp += " ORDER BY id DESC"

    orders = db.execute(q_orders, params).fetchall()
    expenses = db.execute(q_exp, params).fetchall()
    shift_cash_out = int(db.execute(q_cash_ops, params).fetchone()['s'] or 0)

    white_orders_count = 0
    mgmt_orders_count = 0
    white_card_rev = 0
    white_cash_rev = 0
    mgmt_cash_rev = 0
    food_cost = 0.0

    for o in orders:
        t = int(o['total'] or 0)
        c = float(o['cost'] or 0)
        if c <= 0 and t > 0:
            c = round(t * 0.27, 2)
        food_cost += c

        pm = (o['payment_method'] or 'карта').lower()
        is_fisc = int(o['is_fiscal'] or 0)

        if pm in ('микс', 'mix'):
            c_part = int(o['payment_cash'] or (t // 2))
            card_part = max(0, t - c_part)
            white_card_rev += card_part
            if is_fisc:
                white_cash_rev += c_part
                white_orders_count += 1
            else:
                mgmt_cash_rev += c_part
                mgmt_orders_count += 1
        elif pm in ('наличные', 'cash'):
            if is_fisc:
                white_cash_rev += t
                white_orders_count += 1
            else:
                mgmt_cash_rev += t
                mgmt_orders_count += 1
        else:
            if is_fisc:
                white_card_rev += t
                white_orders_count += 1
            else:
                mgmt_cash_rev += t
                mgmt_orders_count += 1

    white_total_rev = white_card_rev + white_cash_rev
    real_total_rev = white_total_rev + mgmt_cash_rev
    total_orders_count = len(orders)

    acquiring_fee = round(white_card_rev * (float(acq_pct) / 100.0))

    white_expenses = sum(float(e['amount'] or 0) for e in expenses if e['contour'] == 'white' and (e['pay_status'] or 'paid') == 'paid')
    mgmt_expenses = sum(float(e['amount'] or 0) for e in expenses if e['contour'] != 'white' and (e['pay_status'] or 'paid') == 'paid')
    unpaid_debts = round(sum(float(e['amount'] or 0) for e in expenses if (e['pay_status'] or 'paid') == 'unpaid'))

    if tax_mode == 'usn6':
        tax_amount = round(white_total_rev * 0.06)
    elif tax_mode == 'usn15':
        tax_base = max(0.0, white_total_rev - white_expenses - acquiring_fee - (food_cost * (white_total_rev / real_total_rev if real_total_rev > 0 else 1)))
        tax_amount = round(tax_base * 0.15)
    else:
        tax_amount = 4500 if white_total_rev > 0 else 0

    white_net_profit = round(white_total_rev - white_expenses - acquiring_fee - tax_amount)
    mgmt_net_cash = round(mgmt_cash_rev - mgmt_expenses - shift_cash_out)

    total_all_expenses = round(white_expenses + mgmt_expenses + shift_cash_out + acquiring_fee + tax_amount)
    real_net_profit = round(real_total_rev - food_cost - total_all_expenses)

    summary = {
        "white_orders_count": white_orders_count,
        "white_card_rev": white_card_rev,
        "white_cash_rev": white_cash_rev,
        "white_total_rev": white_total_rev,
        "acquiring_fee": acquiring_fee,
        "white_expenses": round(white_expenses),
        "tax_amount": tax_amount,
        "white_net_profit": white_net_profit,

        "mgmt_orders_count": mgmt_orders_count,
        "mgmt_cash_rev": mgmt_cash_rev,
        "mgmt_share_pct": round(mgmt_cash_rev / real_total_rev * 100, 1) if real_total_rev > 0 else 0,
        "shift_cash_out": shift_cash_out,
        "mgmt_expenses": round(mgmt_expenses),
        "mgmt_net_cash": mgmt_net_cash,
        "unpaid_debts": unpaid_debts,

        "total_orders_count": total_orders_count,
        "real_total_rev": real_total_rev,
        "food_cost": round(food_cost),
        "food_cost_pct": round(food_cost / real_total_rev * 100, 1) if real_total_rev > 0 else 0,
        "total_all_expenses": total_all_expenses,
        "effective_tax_pct": round(tax_amount / real_total_rev * 100, 1) if real_total_rev > 0 else 0,
        "real_net_profit": real_net_profit,
        "real_margin_pct": round(real_net_profit / real_total_rev * 100, 1) if real_total_rev > 0 else 0
    }
    return summary, orders, expenses

@app.route('/accounting')
@admin_only
def accounting_panel():
    db = get_db()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    tax_mode = request.args.get('tax_mode', 'patent').strip()
    if 'acq_pct' in request.args and request.args.get('acq_pct', '').strip():
        set_setting('acquiring_pct', request.args.get('acq_pct').strip())
    acq_pct = float(get_setting('acquiring_pct', '1.8') or 1.8)
    summary, orders, expenses = compute_dual_accounting(db, date_from, date_to, tax_mode, acq_pct)
    return render_template('accounting.html', summary=summary, orders=orders, expenses=expenses,
                           date_from=date_from, date_to=date_to, tax_mode=tax_mode, acq_pct=acq_pct)

@app.route('/api/accounting/toggle_fiscal/<int:order_id>', methods=['POST'])
@admin_only
def api_toggle_order_fiscal(order_id):
    db = get_db()
    row = db.execute("SELECT is_fiscal FROM orders WHERE id=?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    new_val = 0 if int(row['is_fiscal'] or 0) == 1 else 1
    db.execute("UPDATE orders SET is_fiscal=? WHERE id=?", (new_val, order_id))
    db.commit()
    return jsonify({"success": True, "is_fiscal": new_val})

@app.route('/api/accounting/set_fiscal/<int:order_id>', methods=['POST'])
@admin_only
def api_set_order_fiscal(order_id):
    data = request.get_json(force=True, silent=True) or {}
    val = int(data.get('is_fiscal', 1))
    db = get_db()
    db.execute("UPDATE orders SET is_fiscal=? WHERE id=?", (val, order_id))
    db.commit()
    return jsonify({"success": True, "is_fiscal": val})

@app.route('/fiscal/<int:order_id>/set_fiscal_status', methods=['POST'])
@admin_only
def fiscal_set_status_form(order_id):
    val = int(request.form.get('is_fiscal', 1))
    db = get_db()
    db.execute("UPDATE orders SET is_fiscal=? WHERE id=?", (val, order_id))
    db.commit()
    return redirect(url_for('fiscal_receipt_view', order_id=order_id))

@app.route('/accounting/expense/add', methods=['POST'])
@admin_only
def accounting_expense_add():
    raw_contour = request.form.get('contour', 'mgmt')
    contour = 'white' if raw_contour == 'white' else 'mgmt'
    category = request.form.get('category', 'Прочий расход')
    amount = float(request.form.get('amount', 0) or 0)
    payment_method = request.form.get('payment_method', 'наличные')
    pay_status = request.form.get('pay_status', 'paid')
    comment = request.form.get('comment', '').strip()
    if amount > 0:
        db = get_db()
        db.execute("""
            INSERT INTO accounting_expenses (created_at, category, amount, contour, payment_method, pay_status, comment, username)
            VALUES (?,?,?,?,?,?,?,?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M"), category, amount, contour, payment_method, pay_status, comment, session.get('username', 'admin')))
        db.commit()
    return redirect(url_for('accounting_panel'))

@app.route('/accounting/expense/pay/<int:exp_id>', methods=['POST'])
@admin_only
def accounting_expense_pay(exp_id):
    db = get_db()
    db.execute("UPDATE accounting_expenses SET pay_status='paid' WHERE id=?", (exp_id,))
    db.commit()
    return redirect(url_for('accounting_panel'))

@app.route('/accounting/expense/delete/<int:exp_id>', methods=['POST'])
@admin_only
def accounting_expense_delete(exp_id):
    db = get_db()
    db.execute("DELETE FROM accounting_expenses WHERE id=?", (exp_id,))
    db.commit()
    return redirect(url_for('accounting_panel'))

@app.route('/accounting/export')
@admin_only
def accounting_export():
    mode = request.args.get('mode', 'white')
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    db = get_db()
    acq_pct = float(get_setting('acquiring_pct', '1.8') or 1.8)
    summary, orders, expenses = compute_dual_accounting(db, date_from, date_to, 'patent', acq_pct)

    if not openpyxl:
        return redirect(url_for('accounting_panel'))

    wb = openpyxl.Workbook()
    ws = wb.active

    if mode == 'white':
        ws.title = "Белая бухгалтерия (ККТ)"
        ws.append(["КНИГА УЧЁТА ДОХОДОВ И РАСХОДОВ (ФИСКАЛЬНЫЙ БЕЛЫЙ КОНТУР)"])
        ws.append(["Выручка по ККТ:", summary['white_total_rev'], "Безнал:", summary['white_card_rev'], "Фискальный нал:", summary['white_cash_rev'], "Эквайринг:", summary['acquiring_fee']])
        ws.append([])
        ws.append(["№ ФД", "ID Заказа", "Дата и время", "Способ расчёта", "Сумма по ККТ (₽)"])
        for o in orders:
            if int(o['is_fiscal'] or 0) == 1:
                ws.append([10000 + o['id'], o['id'], o['created_at'], o['payment_method'], o['total']])
        fname = "white_fiscal_accounting.xlsx"
    else:
        ws.title = "Управленческий отчёт P&L"
        ws.append(["СВОДНЫЙ УПРАВЛЕНЧЕСКИЙ ОТЧЁТ (БЕЛАЯ + УПРАВЛЕНЧЕСКАЯ БУХГАЛТЕРИЯ)"])
        ws.append(["Общая выручка:", summary['real_total_rev'], "Белая (ККТ):", summary['white_total_rev'], "Управленческая (Нал):", summary['mgmt_cash_rev'], "Чистая прибыль:", summary['real_net_profit']])
        ws.append([])
        ws.append(["ID Заказа", "Дата и время", "Оплата", "Сумма (₽)", "Себестоимость сырья (₽)", "Контур учёта"])
        for o in orders:
            c_label = "БЕЛАЯ (ККТ)" if int(o['is_fiscal'] or 0) == 1 else "УПРАВЛЕНЧЕСКАЯ (НАЛ)"
            ws.append([o['id'], o['created_at'], o['payment_method'], o['total'], o['cost'], c_label])
        fname = "management_pnl_report.xlsx"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename={fname}"
    response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response

import argon_core; argon_core.register_all(app, globals())

import security_shield; security_shield.init_security_shield(app, get_db)

import erp_power_pack; erp_power_pack.register_power_pack(app, globals())

import ultra_erp_v10; ultra_erp_v10.register_ultra_v10(app, globals())

import omega_erp_v12; omega_erp_v12.register_omega_v12(app, globals())

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
