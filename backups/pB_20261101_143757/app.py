from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, flash, make_response, send_from_directory, send_file, abort
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, re, uuid, io, openpyxl, time, secrets, hashlib, hmac, html, tempfile, urllib.request, urllib.parse, threading

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_FILE = os.path.join(BASE_DIR, '.secret_key')
if not os.path.exists(SECRET_FILE):
    with open(SECRET_FILE, 'w', encoding='utf-8') as _f:
        _f.write(secrets.token_hex(32))
    os.chmod(SECRET_FILE, 0o600)

with open(SECRET_FILE, 'r', encoding='utf-8') as _f:
    app.secret_key = os.environ.get('SUSHI_SECRET') or _f.read().strip()

app.config['SESSION_COOKIE_NAME'] = 'sushi_sid_clean'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SUSHI_HTTPS', '0') == '1',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=14)
)

DB_PATH = os.path.join(BASE_DIR, 'sushi.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

typing_users = {}
rate_limits = {}

DEFAULT_BRAND = {
    'brand_name': 'КРЕВЕТКА',
    'brand_slogan': 'Свежие морепродукты, пицца и роллы с доставкой',
    'brand_city': 'г. Инта',
    'brand_address': 'ул. Горького, 1',
    'brand_phone': '+7 (999) 000-00-00',
    'map_lat': '66.0350',
    'map_lng': '60.1450',
    'work_start': '10:00',
    'work_end': '21:30',
    'tg_token': '',
    'tg_chat_id': ''
}

def clean_str(val, max_len=300):
    if val is None: return ''
    s = str(val).strip()[:max_len]
    return html.escape(s, quote=True)

def check_rate_limit(key, max_hits, window_sec):
    now = time.time()
    hits = [t for t in rate_limits.get(key, []) if now - t < window_sec]
    if len(hits) >= max_hits:
        rate_limits[key] = hits
        return False
    hits.append(now)
    rate_limits[key] = hits
    return True

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None: db.close()


@app.after_request
def set_security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return resp

@app.route('/manifest.json')
def manifest(): return send_from_directory(BASE_DIR, 'manifest.json')
@app.route('/chat_manifest.json')
def chat_manifest(): return send_from_directory(BASE_DIR, 'chat_manifest.json')
@app.route('/sw.js')
def service_worker(): return send_from_directory(BASE_DIR, 'sw.js')

def get_setting(key):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row['value'] if row else None

def set_setting(key, value):
    db = get_db()
    db.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?", (key, value, value))
    db.commit()

def get_brand_settings():
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    stored = {r['key']: r['value'] for r in rows}
    res = DEFAULT_BRAND.copy()
    for k in res:
        if k in stored and stored[k] is not None and stored[k] != '':
            res[k] = stored[k]
    return res

@app.context_processor
def inject_brand():
    try: return dict(brand=get_brand_settings())
    except Exception: return dict(brand=DEFAULT_BRAND)

def send_tg_async(text):
    return


def is_shop_open():
    status = get_setting('shop_status') or 'auto'
    if status == 'closed': return False
    if status == 'open': return True
    b = get_brand_settings()
    try:
        t_start = datetime.strptime(b['work_start'], "%H:%M").time()
        t_end = datetime.strptime(b['work_end'], "%H:%M").time()
        now = datetime.now().time()
        return t_start <= now <= t_end
    except Exception:
        return True

def _ensure_column(db, table, column, decl):
    cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def apply_migrations(db):
    """Идемпотентные миграции: лечат и старые БД, и свежую установку."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    columns = (
        ('print_jobs', 'job_type', "TEXT NOT NULL DEFAULT 'receipt'"),
        ('print_jobs', 'payload', "TEXT NOT NULL DEFAULT '{}'"),
        ('users', 'is_active', 'INTEGER NOT NULL DEFAULT 1'),
        ('users', 'password_version', 'INTEGER NOT NULL DEFAULT 1'),
        ('users', 'password', "TEXT DEFAULT ''"),
        ('users', 'must_change_password', 'INTEGER NOT NULL DEFAULT 0'),
        ('shifts', 'total_cash', 'INTEGER DEFAULT 0'),
        ('shifts', 'total_card', 'INTEGER DEFAULT 0'),
        ('shifts', 'cash_ops', 'INTEGER DEFAULT 0'),
        ('shifts', 'opening_cash', 'INTEGER DEFAULT 0'),
        ('shifts', 'cash_in', 'INTEGER DEFAULT 0'),
        ('shifts', 'cash_out', 'INTEGER DEFAULT 0'),
        ('shifts', 'expected_cash', 'INTEGER DEFAULT 0'),
        ('shifts', 'actual_cash', 'INTEGER DEFAULT 0'),
        ('shifts', 'discrepancy', 'INTEGER DEFAULT 0'),
        ('orders', 'cashier_id', 'INTEGER DEFAULT 0'),
        ('orders', 'source', "TEXT DEFAULT 'Касса'"),
        ('orders', 'payment_cash', 'INTEGER DEFAULT 0'),
        ('orders', 'payment_card', 'INTEGER DEFAULT 0'),
        ('orders', 'change_from', 'INTEGER DEFAULT 0'),
        ('orders', 'delivery_price', 'INTEGER DEFAULT 0'),
        ('orders', 'used_bonus', 'INTEGER DEFAULT 0'),
        ('orders', 'client_credited', 'INTEGER DEFAULT 0'),
        ('orders', 'earned_bonus', 'INTEGER DEFAULT 0'),
        ('orders', 'bonus_refunded', 'INTEGER DEFAULT 0'),
        ('orders', 'public_token', "TEXT DEFAULT ''"),
        ('orders', 'idempotency_key', "TEXT DEFAULT ''"),
        ('orders', 'payment_status', "TEXT DEFAULT 'unpaid'"),
        ('orders', 'paid_at', 'TEXT'),
        ('orders', 'loyalty_applied', 'INTEGER DEFAULT 0'),
        ('orders', 'stock_deducted', 'INTEGER DEFAULT 0'),
        ('orders', 'bonus_awarded', 'INTEGER DEFAULT 0'),
        ('payments', 'cashier_id', 'INTEGER DEFAULT 0'),
        ('payments', 'note', "TEXT DEFAULT ''"),
    )
    for table, column, decl in columns:
        _ensure_column(db, table, column, decl)

    db.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (3, ?)", (now,))
    db.execute("PRAGMA user_version = 3")

    # Устаревшая колонка users.password хранила копию хеша — очищаем.
    db.execute("UPDATE users SET password='' WHERE password IS NOT NULL AND password != ''")

    # Если действует пароль, равный логину, требуем смену при следующем входе.
    for uid, username, pwhash, must_change in db.execute(
            "SELECT id, username, password_hash, must_change_password FROM users").fetchall():
        try:
            is_default = bool(pwhash) and check_password_hash(pwhash, username)
        except Exception:
            is_default = False
        if is_default and not must_change:
            db.execute("UPDATE users SET must_change_password=1, password_version=password_version+1 WHERE id=?", (uid,))


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS banners (id INTEGER PRIMARY KEY AUTOINCREMENT, image TEXT NOT NULL, title TEXT);
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER, sender_name TEXT, text TEXT, created_at TEXT, is_read INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS courier_locations (courier_id INTEGER PRIMARY KEY, lat REAL, lng REAL, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS menu (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price INTEGER NOT NULL CHECK(price >= 0),
        category TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1, stop_list INTEGER DEFAULT 0,
        image TEXT DEFAULT '', composition TEXT DEFAULT '', modifiers TEXT DEFAULT '', sort_weight INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
        total INTEGER NOT NULL CHECK(total >= 0), cost REAL DEFAULT 0, address TEXT, phone TEXT, comment TEXT, shift_id INTEGER,
        cashier_id INTEGER DEFAULT 0, source TEXT DEFAULT 'Касса',
        payment_method TEXT DEFAULT 'не указан', payment_cash INTEGER DEFAULT 0, payment_card INTEGER DEFAULT 0, change_from INTEGER DEFAULT 0,
        delivery_type TEXT DEFAULT 'доставка', scheduled_time TEXT,
        cancel_reason TEXT DEFAULT '', courier_name TEXT DEFAULT '', discount INTEGER DEFAULT 0,
        discount_type TEXT DEFAULT 'rub', delivery_zone TEXT DEFAULT '', delivery_price INTEGER DEFAULT 0,
        used_bonus INTEGER DEFAULT 0, cook_start_time TEXT, cook_end_time TEXT, promo_code TEXT DEFAULT '',
        rating INTEGER DEFAULT 0, review_text TEXT DEFAULT '',
        public_token TEXT DEFAULT '', stock_deducted INTEGER DEFAULT 0, bonus_awarded INTEGER DEFAULT 0, idempotency_key TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, menu_id INTEGER,
        name TEXT NOT NULL, price INTEGER NOT NULL, qty INTEGER NOT NULL DEFAULT 1 CHECK(qty > 0), modifiers TEXT DEFAULT '',
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, shift_id INTEGER,
        method TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount >= 0), status TEXT NOT NULL DEFAULT 'paid',
        created_at TEXT NOT NULL, cashier_id INTEGER DEFAULT 0,
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS print_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, job_type TEXT NOT NULL DEFAULT 'receipt',
        station TEXT NOT NULL DEFAULT 'all', status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER DEFAULT 0, last_error TEXT DEFAULT '', created_at TEXT NOT NULL, printed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'cashier', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, opened_at TEXT NOT NULL, closed_at TEXT,
        opened_by INTEGER, closed_by INTEGER, total_orders INTEGER DEFAULT 0,
        total_revenue INTEGER DEFAULT 0, status TEXT NOT NULL DEFAULT 'open', total_cash INTEGER DEFAULT 0, total_card INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS cash_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, shift_id INTEGER, op_type TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0), comment TEXT, created_at TEXT, username TEXT
    );
    CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE NOT NULL, name TEXT, bonuses INTEGER DEFAULT 0, total_spent INTEGER DEFAULT 0, orders_count INTEGER DEFAULT 0, last_order_at TEXT, level TEXT DEFAULT 'bronze');
    CREATE TABLE IF NOT EXISTS zones (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price INTEGER NOT NULL, polygon_data TEXT DEFAULT '', lat REAL DEFAULT 66.035, lng REAL DEFAULT 60.145, radius REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS promocodes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, discount_type TEXT NOT NULL DEFAULT 'percent', discount_value INTEGER NOT NULL, is_active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, stock REAL DEFAULT 0, unit TEXT NOT NULL, cost_price REAL DEFAULT 0, is_prep INTEGER DEFAULT 0, waste_pct REAL DEFAULT 0, prep_yield REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS recipes (menu_id INTEGER, ingredient_id INTEGER, amount REAL NOT NULL, PRIMARY KEY (menu_id, ingredient_id), FOREIGN KEY(menu_id) REFERENCES menu(id) ON DELETE CASCADE, FOREIGN KEY(ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS prep_recipes (prep_id INTEGER, raw_id INTEGER, amount REAL NOT NULL, PRIMARY KEY (prep_id, raw_id), FOREIGN KEY(prep_id) REFERENCES ingredients(id) ON DELETE CASCADE, FOREIGN KEY(raw_id) REFERENCES ingredients(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS stock_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, ingredient_id INTEGER, ing_name TEXT, change_amount REAL, op_type TEXT, reason TEXT, cost_impact REAL DEFAULT 0, username TEXT);
    CREATE TABLE IF NOT EXISTS refunds (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, shift_id INTEGER,
        method TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount >= 0), reason TEXT DEFAULT '',
        created_at TEXT NOT NULL, user_id INTEGER,
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ing_unique_name ON ingredients(lower(trim(name)));
    """)
    if db.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        db.execute("INSERT INTO settings (key, value) VALUES ('shop_status', 'auto')")
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pwd = secrets.token_urlsafe(6)
        db.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)", ("admin", generate_password_hash(pwd), "admin", now))
        print(f"🔐 Создан администратор admin с паролем: {pwd}")
    apply_migrations(db)
    db.commit()
    db.close()

def get_csrf_token():
    if not token:
        token = secrets.token_urlsafe(32)
    return token


@app.before_request
def csrf_protect():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if not expected or not supplied or not hmac.compare_digest(str(supplied), str(expected)):
            msg = 'Токен не требуется отсутствует или неверен. Обновите страницу и повторите.'
            if request.path.startswith('/api/'):
                return jsonify({"error": msg}), 400
            abort(400, description=msg)


@app.before_request
def validate_session():
    if request.endpoint == 'static' or 'user_id' not in session:
        return
    user = get_db().execute("SELECT password_hash, is_active FROM users WHERE id=?", (session['user_id'],)).fetchone()
    expected = (user['password_hash'] or '')[:16] if user else ''
    if not user or not user['is_active'] or session.get('pwd_sig') != expected:
        session.clear()
        return redirect(url_for('login'))


def login_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session: return redirect(url_for('login'))
            if roles and session.get('role') not in roles: return "Доступ запрещён", 403
            if session.get('must_change_password') and request.endpoint not in ('change_password', 'logout', 'static'):
                if request.path.startswith('/api/'):
                    return jsonify({"error": "Требуется смена пароля", "redirect": "/change_password"}), 403
                return redirect(url_for('change_password'))
            return f(*args, **kwargs)
        return wrapper
    return decorator

def parse_mods_extra_price(mods_str, menu_mods_str):
    if not mods_str or not menu_mods_str: return 0
    allowed = {}
    for part in menu_mods_str.split(','):
        if ':' in part:
            k, v = part.split(':', 1)
            try: allowed[k.strip().lower()] = max(0, int(v.strip()))
            except ValueError: pass
    extra = 0
    for chosen in mods_str.split(','):
        c_name = chosen.split('(')[0].replace('+', '').strip().lower()
        if c_name in allowed: extra += allowed[c_name]
    return extra

def validate_and_prepare_items(raw_items, allow_stop_list=False):
    if not isinstance(raw_items, list) or len(raw_items) == 0:
        return None, "Корзина пуста"
    if len(raw_items) > 25:
        return None, "Слишком много позиций в одном заказе (макс. 25)"
    db = get_db()
    validated = []
    for i in raw_items:
        menu_id = i.get('id')
        try: qty = int(i.get('qty', 1))
        except Exception: return None, "Некорректное количество"
        if qty < 1 or qty > 30:
            return None, "Количество одной позиции должно быть от 1 до 30"
        row = db.execute("SELECT id, name, price, available, stop_list, modifiers FROM menu WHERE id=?", (menu_id,)).fetchone()
        if not row or not row['available']:
            return None, f"Блюдо недоступно"
        if row['stop_list'] and not allow_stop_list:
            return None, f"Блюдо '{row['name']}' в стоп-листе"
        mods = clean_str(i.get('mods', ''), 120)
        extra = parse_mods_extra_price(mods, row['modifiers'] or '')
        validated.append({
            "id": row['id'], "name": row['name'],
            "price": int(row['price']) + extra, "qty": qty, "mods": mods
        })
    return validated, None

def adjust_stock_for_order(order_id, items, direction=-1, actor='Система', reason_prefix='Заказ'):
    """direction=-1 списывает со склада, direction=+1 возвращает на склад. Пишет stock_logs."""
    db = get_db()
    total_cost = 0.0
    changes = {}
    for i in items:
        qty = int(i.get('qty', 1))
        menu_id = i.get('id') or i.get('menu_id')
        if not menu_id: continue
        recipes = db.execute("""
            SELECT r.ingredient_id, r.amount, ing.name, ing.stock, ing.cost_price, COALESCE(ing.waste_pct, 0) as waste_pct
            FROM recipes r JOIN ingredients ing ON r.ingredient_id = ing.id 
            WHERE r.menu_id=?
        """, (menu_id,)).fetchall()
        for r in recipes:
            ing_id = r['ingredient_id']
            waste = min(95.0, max(0.0, float(r['waste_pct'] or 0)))
            factor = 1.0 / (1.0 - waste / 100.0) if waste > 0 else 1.0
            brutto = r['amount'] * qty * factor
            if ing_id not in changes:
                changes[ing_id] = {"amt": 0.0, "name": r['name'], "stock": r['stock'], "cost": r['cost_price']}
            changes[ing_id]["amt"] += brutto

    if direction < 0:
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

    return None, round(total_cost, 2)

def record_order_payments(db, order_id, shift_id, payment_method, total, raw_cash=0, cashier_id=0):
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
    return pay_cash, pay_card

def settle_client_loyalty(db, order, direction=1):
    """Начисляет (direction=1) или откатывает (direction=-1) бонусы и LTV только при выдаче заказа (done)."""
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
        db.execute("""
            INSERT INTO clients (phone, total_spent, orders_count, last_order_at, level, bonuses)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(phone) DO UPDATE SET
                total_spent = total_spent + ?,
                orders_count = orders_count + 1,
                last_order_at = ?,
                level = ?,
                bonuses = bonuses + ?
        """, (phone, total, 1, now_str, new_level, earned, total, now_str, new_level, earned))
    elif direction < 0 and client:
        rate = 0.10 if client['level'] == 'gold' else (0.07 if client['level'] == 'silver' else 0.05)
        earned = int(total * rate)
        new_spent = max(0, client['total_spent'] - total)
        new_level = 'gold' if new_spent >= 30000 else ('silver' if new_spent >= 10000 else 'bronze')
        db.execute("""
            UPDATE clients SET
                total_spent = MAX(0, total_spent - ?),
                orders_count = MAX(0, orders_count - 1),
                bonuses = MAX(0, bonuses - ?),
                level = ?
            WHERE phone=?
        """, (total, earned, new_level, phone))

def enqueue_print_job(db, order_id, job_type='receipt'):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = {r[1] for r in db.execute("PRAGMA table_info(print_jobs)")}
    if 'job_type' in cols:
        db.execute("INSERT INTO print_jobs (order_id, job_type, station, payload, status, attempts, created_at) VALUES (?,?,?,?,?,?,?)",
                   (order_id, job_type, 'all', '{}', 'pending', 0, now_str))
    else:
        db.execute("INSERT INTO print_jobs (order_id, station, payload, status, attempts, created_at) VALUES (?,?,?,?,?,?)",
                   (order_id, 'all', '{}', 'pending', 0, now_str))

def parse_zone_price(zone_str, delivery_type, client_level='bronze'):
    if delivery_type != 'доставка' or not zone_str or client_level == 'gold': return 0
    match = re.search(r'\((\d+)₽\)', zone_str)
    return int(match.group(1)) if match else 0

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = request.remote_addr or 'local'
        if not check_rate_limit(f"login_{ip}", 8, 300):
            flash('Слишком много попыток входа. Подождите 5 минут.')
            return render_template('login.html'), 429
        user = get_db().execute("SELECT * FROM users WHERE username=?", (request.form.get('username', '').strip(),)).fetchone()
        if user and check_password_hash((user['password_hash'] if 'password_hash' in user.keys() and user['password_hash'] else user['password']), request.form.get('password', '')):
            session.clear()
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['pwd_sig'] = (user['password_hash'] if 'password_hash' in user.keys() and user['password_hash'] else user['password'])[:16]
            session['must_change_password'] = bool(user['must_change_password'])
            if session['must_change_password']:
                flash('Пароль по умолчанию больше не действует — задайте новый.')
                return redirect(url_for('change_password'))
            return redirect(url_for('index'))
        flash('Неверный логин или пароль')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))


@app.route('/change_password', methods=['GET', 'POST'])
@login_required()
def change_password():
    if request.method == 'POST':
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
        if not user or not check_password_hash(user['password_hash'], old):
            flash('Текущий пароль неверен')
            return render_template('change_password.html'), 400
        if len(new) < 10:
            flash('Новый пароль должен быть не короче 10 символов')
            return render_template('change_password.html'), 400
        if new != confirm:
            flash('Пароли не совпадают')
            return render_template('change_password.html'), 400
        if new == old or new.strip().lower() == (user['username'] or '').lower():
            flash('Новый пароль не должен совпадать с текущим паролем или логином')
            return render_template('change_password.html'), 400
        new_hash = generate_password_hash(new)
        db.execute("UPDATE users SET password_hash=?, password='', password_version=password_version+1, must_change_password=0 WHERE id=?",
                   (new_hash, user['id']))
        db.commit()
        session['pwd_sig'] = new_hash[:16]
        session['must_change_password'] = False
        flash('Пароль обновлён')
        return redirect(url_for('index'))
    return render_template('change_password.html')

def get_open_shift():
    return get_db().execute("SELECT * FROM shifts WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()

def ensure_open_shift():
    sh = get_open_shift()
    if sh: return sh
    db = get_db()
    cur = db.execute("INSERT INTO shifts (opened_at, opened_by, status) VALUES (?,?,?)",
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0, 'open'))
    db.commit()
    return db.execute("SELECT * FROM shifts WHERE id=?", (cur.lastrowid,)).fetchone()

@app.route('/shift/open', methods=['POST'])
@login_required('admin', 'cashier')
def shift_open():
    if not get_open_shift():
        db = get_db()
        cur = db.execute("INSERT INTO shifts (opened_at, opened_by, status) VALUES (?,?,?)",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session['user_id'], 'open'))
        float_in = int(request.form.get('float_in', 0) or 0)
        if float_in > 0:
            db.execute("INSERT INTO cash_operations (shift_id, op_type, amount, comment, created_at, username) VALUES (?,?,?,?,?,?)",
                       (cur.lastrowid, 'float_in', float_in, 'Размен при открытии', datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session['username']))
        db.commit()
    return redirect(url_for('index'))

@app.route('/shift/close', methods=['POST'])
@login_required('admin', 'cashier')
def shift_close():
    shift = get_open_shift()
    if not shift: return redirect(url_for('index'))
    db = get_db()
    active_cnt = db.execute("SELECT COUNT(*) FROM orders WHERE shift_id=? AND status IN ('new','cooking','ready','delivering')", (shift['id'],)).fetchone()[0]
    if active_cnt > 0:
        return f"<script>alert('Нельзя закрыть смену: ещё есть незавершённые заказы ({active_cnt} шт.)!');window.location='/';</script>", 400

    cnt = db.execute("SELECT COUNT(*) FROM orders WHERE shift_id=? AND status!='cancelled'", (shift['id'],)).fetchone()[0]
    rev = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE shift_id=? AND status='paid'", (shift['id'],)).fetchone()[0]
    sales_cash = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE shift_id=? AND status='paid' AND method IN ('наличные','cash')", (shift['id'],)).fetchone()[0]
    card = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE shift_id=? AND status='paid' AND method IN ('карта','card')", (shift['id'],)).fetchone()[0]
    float_in = db.execute("SELECT COALESCE(SUM(amount),0) FROM cash_operations WHERE shift_id=? AND op_type='float_in'", (shift['id'],)).fetchone()[0]
    collection = db.execute("SELECT COALESCE(SUM(amount),0) FROM cash_operations WHERE shift_id=? AND op_type='collection'", (shift['id'],)).fetchone()[0]
    expected_cash = sales_cash + float_in - collection
    raw_actual = (request.form.get('actual_cash') or '').strip()
    try:
        actual_cash = int(raw_actual) if raw_actual else expected_cash
    except ValueError:
        actual_cash = expected_cash
    discrepancy = actual_cash - expected_cash
    cash_ops = float_in - collection

    db.execute("UPDATE shifts SET closed_at=?, closed_by=?, status='closed', total_orders=?, total_revenue=?, "
               "total_cash=?, total_card=?, cash_ops=?, opening_cash=?, cash_in=?, cash_out=?, "
               "expected_cash=?, actual_cash=?, discrepancy=? WHERE id=?",
               (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session['user_id'], cnt, rev,
                sales_cash, card, cash_ops, float_in, float_in, collection,
                expected_cash, actual_cash, discrepancy, shift['id']))
    db.commit()
    send_tg_async(f"📊 <b>СМЕНА #{shift['id']} ЗАКРЫТА (Z-Отчет)</b>\n📦 Заказов: {cnt}\n💰 Выручка: <b>{rev} ₽</b>\n💵 Наличные: {sales_cash} ₽\n💳 Безнал: {card} ₽\n🧾 Ожидаемо в кассе: {expected_cash} ₽\n✅ Факт: {actual_cash} ₽\n📉 Расхождение: {discrepancy} ₽")
    return redirect(url_for('reports'))

@app.route('/api/cash_op', methods=['POST'])
@login_required('admin', 'cashier')
def cash_op():
    data = request.json or {}
    op_type = data.get('op_type')
    if op_type not in ('float_in', 'collection'):
        return jsonify({"error": "Неверный тип операции"}), 400
    amount = int(data.get('amount', 0) or 0)
    comment = clean_str(data.get('comment', ''), 150)
    shift = get_open_shift()
    if not shift or amount <= 0:
        return jsonify({"error": "Смена не открыта или сумма <= 0"}), 400
    db = get_db()
    db.execute("INSERT INTO cash_operations (shift_id, op_type, amount, comment, created_at, username) VALUES (?,?,?,?,?,?)",
               (shift['id'], op_type, amount, comment, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session['username']))
    db.commit()
    return jsonify({"success": True})

@app.route('/api/cash_balance')
@login_required('admin', 'cashier')
def api_cash_balance():
    shift = get_open_shift()
    if not shift: return jsonify({"open": False, "drawer_cash": 0})
    db = get_db()
    sales_cash = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE shift_id=? AND status='paid' AND method IN ('наличные','cash')", (shift['id'],)).fetchone()[0]
    float_in = db.execute("SELECT COALESCE(SUM(amount),0) FROM cash_operations WHERE shift_id=? AND op_type='float_in'", (shift['id'],)).fetchone()[0]
    collection = db.execute("SELECT COALESCE(SUM(amount),0) FROM cash_operations WHERE shift_id=? AND op_type='collection'", (shift['id'],)).fetchone()[0]
    return jsonify({"open": True, "sales_cash": sales_cash, "float_in": float_in, "collection": collection, "drawer_cash": float_in + sales_cash - collection})

@app.route('/')
@login_required()
def index():
    if session['role'] == 'kitchen': return redirect(url_for('kitchen'))
    if session['role'] == 'courier': return redirect(url_for('courier'))
    db = get_db()
    shift = get_open_shift()
    expected_cash = 0
    if shift:
        sales_cash = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE shift_id=? AND status='paid' AND method IN ('наличные','cash')", (shift['id'],)).fetchone()[0]
        float_in = db.execute("SELECT COALESCE(SUM(amount),0) FROM cash_operations WHERE shift_id=? AND op_type='float_in'", (shift['id'],)).fetchone()[0]
        collection = db.execute("SELECT COALESCE(SUM(amount),0) FROM cash_operations WHERE shift_id=? AND op_type='collection'", (shift['id'],)).fetchone()[0]
        expected_cash = sales_cash + float_in - collection
    return render_template('cashier.html', menu=db.execute("SELECT * FROM menu WHERE available=1 ORDER BY sort_weight DESC, category, name").fetchall(), categories=db.execute("SELECT DISTINCT category FROM menu WHERE available=1 ORDER BY category").fetchall(), zones=db.execute("SELECT * FROM zones").fetchall(), shift=shift, expected_cash=expected_cash, role=session['role'], shop_open=is_shop_open())

@app.route('/kitchen')
@login_required('admin', 'kitchen')
def kitchen(): return render_template('kitchen.html')

@app.route('/courier')
@login_required('admin', 'courier')
def courier(): return render_template('courier.html')

@app.route('/reports')
@login_required('admin', 'cashier')
def reports(): return render_template('reports.html', shifts=get_db().execute("SELECT * FROM shifts ORDER BY id DESC LIMIT 30").fetchall())

@app.route('/orders')
@login_required('admin', 'cashier')
def orders_view():
    db = get_db()
    return render_template('orders.html', users=db.execute("SELECT id, username FROM users").fetchall(), menu=db.execute("SELECT * FROM menu WHERE available=1 ORDER BY category, name").fetchall())

@app.route('/receipt/<int:order_id>')
@login_required()
def receipt(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order: return "Заказ не найден", 404
    return render_template('receipt.html', order=order, items=db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall(), host_url=request.host_url)

@app.route('/ticket/<int:order_id>')
@login_required()
def ticket(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order: return "Заказ не найден", 404
    return render_template('ticket.html', order=order, items=db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall())

@app.route('/api/order/update_items/<int:order_id>', methods=['POST'])
@login_required('admin', 'cashier')
def update_order_items(order_id):
    data = request.json or {}
    raw_items = data.get('items', [])
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or order['status'] in ('done', 'cancelled'):
        return jsonify({"error": "Нельзя редактировать закрытый или отменённый заказ"}), 400
    shift = get_open_shift()
    if not shift or order['shift_id'] != shift['id']:
        return jsonify({"error": "Нельзя редактировать заказ из закрытой смены"}), 400

    validated_items, val_err = validate_and_prepare_items(raw_items, allow_stop_list=True)
    if val_err: return jsonify({"error": val_err}), 400

    old_items = [dict(r) for r in db.execute("SELECT menu_id as id, qty FROM order_items WHERE order_id=?", (order_id,)).fetchall()]
    try:
        if order['stock_deducted']:
            adjust_stock_for_order(order_id, old_items, direction=+1, actor=session['username'], reason_prefix='Правка (возврат)')
        err, new_cost = adjust_stock_for_order(order_id, validated_items, direction=-1, actor=session['username'], reason_prefix='Правка (списание)')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400

        db.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
        subtotal = 0
        for i in validated_items:
            subtotal += i['price'] * i['qty']
            db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                       (order_id, i['id'], i['name'], i['price'], i['qty'], i['mods']))

        manual_discount = (subtotal * order['discount'] // 100) if order['discount_type'] == 'percent' else order['discount']
        promo_discount = 0
        if order['promo_code']:
            promo = db.execute("SELECT * FROM promocodes WHERE code=?", (order['promo_code'],)).fetchone()
            if promo:
                promo_discount = (subtotal * promo['discount_value']) // 100 if promo['discount_type'] == 'percent' else promo['discount_value']

        ord_dict = dict(order)
        delivery_price = ord_dict.get('delivery_price') or 0
        used_bonus = ord_dict.get('used_bonus') or 0
        new_total = max(0, subtotal - manual_discount - promo_discount - used_bonus) + delivery_price
        pay_cash, pay_card = record_order_payments(db, order_id, order['shift_id'], order['payment_method'], new_total, order['payment_cash'], session['user_id'])

        db.execute("UPDATE orders SET total=?, cost=?, payment_cash=?, payment_card=?, stock_deducted=1 WHERE id=?",
                   (new_total, new_cost, pay_cash, pay_card, order_id))
        db.commit()
        return jsonify({"success": True, "new_total": new_total})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/all_orders')
@login_required('admin', 'cashier')
def api_all_orders():
    db = get_db()
    date_filter = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
    cashier_id = request.args.get('cashier_id'); source = request.args.get('source'); status = request.args.get('status')
    query = "SELECT o.*, u.username as cashier_name FROM orders o LEFT JOIN users u ON o.cashier_id = u.id WHERE 1=1"
    params = []
    if date_filter: query += " AND date(o.created_at) = ?"; params.append(date_filter)
    if cashier_id: query += " AND o.cashier_id = ?"; params.append(cashier_id)
    if source: query += " AND o.source = ?"; params.append(source)
    if status: query += " AND o.status = ?"; params.append(status)
    query += " ORDER BY o.id DESC"
    rows = db.execute(query, params).fetchall()
    result = []; total_sum = 0
    for r in rows:
        order = dict(r)
        order['items'] = [dict(i) for i in db.execute("SELECT * FROM order_items WHERE order_id=?", (r['id'],)).fetchall()]
        result.append(order)
        if order['status'] != 'cancelled': total_sum += order['total']
    valid_count = len([o for o in result if o['status'] != 'cancelled'])
    return jsonify({"orders": result, "stats": {"count": valid_count, "total": total_sum, "avg": round(total_sum / valid_count) if valid_count > 0 else 0}})

@app.route('/map')
@login_required('admin', 'cashier')
def map_view(): return render_template('map.html')

@app.route('/api/zones', methods=['GET', 'POST'])
def api_zones():
    db = get_db()
    if request.method == 'POST':
        if session.get('role') != 'admin': return jsonify({"error": "Forbidden"}), 403
        data = request.json or {}
        db.execute("INSERT INTO zones (name, price, polygon_data) VALUES (?,?,?)", (clean_str(data.get('name'), 80), max(0, int(data.get('price', 0))), data.get('polygon_data', '')))
        db.commit()
        return jsonify({"success": True})
    return jsonify([dict(z) for z in db.execute("SELECT id, name, price, polygon_data FROM zones").fetchall()])

@app.route('/api/zones/delete/<int:zone_id>', methods=['POST'])
@login_required('admin')
def api_zones_delete(zone_id):
    db = get_db(); db.execute("DELETE FROM zones WHERE id=?", (zone_id,)); db.commit(); return jsonify({"success": True})

@app.route('/api/courier/location', methods=['POST'])
@login_required('courier', 'admin')
def api_courier_location():
    data = request.json or {}; lat, lng = data.get('lat'), data.get('lng')
    if lat and lng:
        db = get_db(); now_time = datetime.now().strftime("%H:%M:%S")
        db.execute("INSERT INTO courier_locations (courier_id, lat, lng, updated_at) VALUES (?,?,?,?) ON CONFLICT(courier_id) DO UPDATE SET lat=?, lng=?, updated_at=?", (session['user_id'], float(lat), float(lng), now_time, float(lat), float(lng), now_time))
        db.commit()
    return jsonify({"success": True})

@app.route('/api/couriers/locations')
@login_required('admin', 'cashier')
def api_couriers_locations():
    return jsonify([dict(r) for r in get_db().execute("SELECT c.lat, c.lng, c.updated_at, u.username FROM courier_locations c JOIN users u ON c.courier_id = u.id").fetchall()])

@app.route('/api/delivery_route')
@login_required('admin', 'courier', 'cashier')
def api_delivery_route():
    db = get_db()
    orders = db.execute("SELECT id, address, total, phone FROM orders WHERE status IN ('ready', 'delivering') AND address != 'Самовывоз'").fetchall()
    return jsonify([{"id": o['id'], "address": o['address'], "phone": o['phone'], "total": o['total'], "lat": 66.0350 + (o['id'] % 10) * 0.004, "lng": 60.1450 + (o['id'] % 7) * 0.006} for o in orders])

@app.route('/chat')
@login_required()
def chat_view(): return render_template('chat.html')

@app.route('/api/chat/get')
@login_required()
def api_chat_get():
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM messages WHERE is_read=0 AND sender_id != ?", (session['user_id'],)).fetchone()[0] > 0:
        db.execute("UPDATE messages SET is_read=1 WHERE is_read=0 AND sender_id != ?", (session['user_id'],)); db.commit()
    msgs = db.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 50").fetchall()
    now = time.time(); currently_typing = [u for u, t in typing_users.items() if now - t < 3 and u != session['username']]
    return jsonify({"messages": [dict(m) for m in reversed(msgs)], "typing": currently_typing})

@app.route('/api/chat/send', methods=['POST'])
@login_required()
def api_chat_send():
    data = request.json or {}; text = clean_str(data.get('text', ''), 500)
    if text:
        db = get_db(); db.execute("INSERT INTO messages (sender_id, sender_name, text, created_at, is_read) VALUES (?,?,?,?,0)", (session['user_id'], session['username'], text, datetime.now().strftime("%H:%M"))); db.commit()
        typing_users.pop(session['username'], None)
    return jsonify({"success": True})

@app.route('/api/chat/typing', methods=['POST'])
@login_required()
def api_chat_typing():
    typing_users[session['username']] = time.time(); return jsonify({"success": True})

@app.route('/api/chat/clear', methods=['POST'])
@login_required('admin')
def api_chat_clear():
    db = get_db(); db.execute("DELETE FROM messages"); db.commit(); return jsonify({"success": True})

@app.route('/crm')
@login_required('admin')
def crm_panel(): return render_template('crm.html', clients=get_db().execute("SELECT * FROM clients ORDER BY total_spent DESC").fetchall())

def recalc_prep_cost(db, prep_id):
    prep = db.execute("SELECT * FROM ingredients WHERE id=?", (prep_id,)).fetchone()
    if not prep: return
    rows = db.execute("""
        SELECT pr.amount, ing.cost_price, COALESCE(ing.waste_pct, 0) as waste_pct
        FROM prep_recipes pr JOIN ingredients ing ON pr.raw_id = ing.id
        WHERE pr.prep_id=?
    """, (prep_id,)).fetchall()
    if not rows: return
    batch_cost = 0.0; raw_sum = 0.0
    for r in rows:
        w = min(95.0, max(0.0, float(r['waste_pct'] or 0)))
        factor = 1.0 / (1.0 - w / 100.0) if w > 0 else 1.0
        batch_cost += (r['amount'] * factor) * r['cost_price']
        raw_sum += r['amount']
    yield_amt = float(prep['prep_yield'] or 0)
    if yield_amt <= 0: yield_amt = raw_sum if raw_sum > 0 else 1.0
    unit_cost = round(batch_cost / yield_amt, 4)
    db.execute("UPDATE ingredients SET cost_price=?, prep_yield=? WHERE id=?", (unit_cost, yield_amt, prep_id))

@app.route('/warehouse')
@login_required('admin')
def warehouse_panel():
    db = get_db()
    ings = db.execute("SELECT * FROM ingredients ORDER BY is_prep DESC, name").fetchall()
    preps = [dict(i) for i in ings if i['is_prep']]
    raw_ings = [dict(i) for i in ings if not i['is_prep']]
    for p in preps:
        p['recipe'] = [dict(r) for r in db.execute("""
            SELECT pr.raw_id, pr.amount, ing.name, ing.unit, ing.cost_price, COALESCE(ing.waste_pct, 0) as waste_pct
            FROM prep_recipes pr JOIN ingredients ing ON pr.raw_id = ing.id
            WHERE pr.prep_id=?
        """, (p['id'],)).fetchall()]
        p['raw_weight'] = round(sum(r['amount'] for r in p['recipe']), 3)
    logs = db.execute("SELECT * FROM stock_logs ORDER BY id DESC LIMIT 60").fetchall()
    total_stock_value = sum(max(0, i['stock']) * i['cost_price'] for i in ings)
    return render_template('warehouse.html', ingredients=ings, preps=preps, raw_ings=raw_ings, logs=logs, total_stock_value=round(total_stock_value, 1))

@app.route('/admin/ingredient/add', methods=['POST'])
@login_required('admin')
def admin_ingredient_add():
    name = clean_str(request.form.get('name'), 80)
    unit = clean_str(request.form.get('unit'), 20)
    if name and unit:
        db = get_db()
        stock = max(0.0, float(request.form.get('stock') or 0))
        cost = max(0.0, float(request.form.get('cost_price') or 0))
        waste = min(95.0, max(0.0, float(request.form.get('waste_pct') or 0)))
        is_prep = 1 if request.form.get('is_prep') else 0
        default_yield = (1.0 if unit.lower() in ('кг','kg','л','l','шт') else 1000.0) if is_prep else 0.0
        existing = db.execute("SELECT id FROM ingredients WHERE lower(trim(name))=lower(trim(?))", (name,)).fetchone()
        if existing:
            db.execute("UPDATE ingredients SET stock=ROUND(stock+?,4), cost_price=?, waste_pct=? WHERE id=?", (stock, cost, waste, existing['id']))
            ing_id = existing['id']
        else:
            cur = db.execute("INSERT INTO ingredients (name, stock, unit, cost_price, is_prep, waste_pct, prep_yield) VALUES (?,?,?,?,?,?,?)",
                             (name, stock, unit, cost, is_prep, waste, default_yield))
            ing_id = cur.lastrowid
        if stock > 0:
            db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M"), ing_id, name, stock, 'приход', 'Начальный остаток', round(stock * cost, 1), session['username']))
        db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/admin/ingredient/update/<int:ing_id>', methods=['POST'])
@login_required('admin')
def admin_ingredient_update(ing_id):
    db = get_db()
    ing = db.execute("SELECT * FROM ingredients WHERE id=?", (ing_id,)).fetchone()
    if not ing: return redirect(url_for('warehouse_panel'))
    action = request.form.get('action')
    val = max(0.0, float(request.form.get('val') or 0))
    cost = max(0.0, float(request.form.get('cost_price', ing['cost_price']) or 0))
    waste = min(95.0, max(0.0, float(request.form.get('waste_pct', ing['waste_pct'] or 0) or 0)))
    reason = clean_str(request.form.get('reason', ''), 120)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    if action == 'settings':
        db.execute("UPDATE ingredients SET cost_price=?, waste_pct=? WHERE id=?", (cost, waste, ing_id))
    elif action == 'add' and val > 0:
        db.execute("UPDATE ingredients SET stock = ROUND(stock + ?, 4), cost_price = ?, waste_pct = ? WHERE id=?", (val, cost, waste, ing_id))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                   (now_str, ing_id, ing['name'], val, 'приход', reason or 'Поставка товара', round(val * cost, 1), session['username']))
    elif action == 'writeoff' and val > 0:
        if ing['stock'] < val:
            return f"<script>alert('Нельзя списать {val} {ing["unit"]}: на складе всего {ing["stock"]} {ing["unit"]}!');window.location='/warehouse';</script>", 400
        diff = -abs(val)
        db.execute("UPDATE ingredients SET stock = ROUND(stock + ?, 4) WHERE id=?", (diff, ing_id))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                   (now_str, ing_id, ing['name'], diff, 'списание', reason or 'Списание (Стафф/Порча)', round(diff * cost, 1), session['username']))
    for p in db.execute("SELECT DISTINCT prep_id FROM prep_recipes WHERE raw_id=?", (ing_id,)).fetchall():
        recalc_prep_cost(db, p['prep_id'])
    db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/admin/prep/save/<int:prep_id>', methods=['POST'])
@login_required('admin')
def admin_prep_save(prep_id):
    db = get_db()
    prep_yield = max(0.001, float(request.form.get('prep_yield') or 1))
    db.execute("UPDATE ingredients SET prep_yield=? WHERE id=?", (prep_yield, prep_id))
    db.execute("DELETE FROM prep_recipes WHERE prep_id=?", (prep_id,))
    for k, v in request.form.items():
        if k.startswith('raw_') and v.strip():
            amt = float(v)
            if amt > 0:
                raw_id = int(k.split('_')[1])
                db.execute("INSERT INTO prep_recipes (prep_id, raw_id, amount) VALUES (?,?,?)", (prep_id, raw_id, amt))
    recalc_prep_cost(db, prep_id)
    db.commit()
    return redirect(url_for('warehouse_panel') + '#tab-preps')

@app.route('/admin/prep/produce/<int:prep_id>', methods=['POST'])
@login_required('admin')
def admin_prep_produce(prep_id):
    db = get_db()
    prep = db.execute("SELECT * FROM ingredients WHERE id=?", (prep_id,)).fetchone()
    if not prep: return redirect(url_for('warehouse_panel'))
    batches = max(0.01, float(request.form.get('batches') or 1.0))
    recipe = db.execute("""
        SELECT pr.raw_id, pr.amount, ing.name, ing.stock, ing.unit, ing.cost_price, COALESCE(ing.waste_pct, 0) as waste_pct
        FROM prep_recipes pr JOIN ingredients ing ON pr.raw_id = ing.id
        WHERE pr.prep_id=?
    """, (prep_id,)).fetchall()
    if not recipe:
        return "<script>alert('Сначала заполните ТТК заготовки!');window.location='/warehouse#tab-preps';</script>", 400

    # Проверка наличия сырья перед приготовлением П/Ф (запрет отрицательных остатков)
    to_spend = []
    for r in recipe:
        w = min(95.0, max(0.0, float(r['waste_pct'] or 0)))
        factor = 1.0 / (1.0 - w / 100.0) if w > 0 else 1.0
        spend_brutto = round(r['amount'] * batches * factor, 4)
        if r['stock'] < spend_brutto:
            return f"<script>alert('Не хватает сырья для П/Ф: {r["name"]} (нужно {spend_brutto} {r["unit"]}, на складе {r["stock"]} {r["unit"]})');window.location='/warehouse#tab-preps';</script>", 400
        to_spend.append((r, spend_brutto))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for r, spend_brutto in to_spend:
        db.execute("UPDATE ingredients SET stock = ROUND(stock - ?, 4) WHERE id=?", (spend_brutto, r['raw_id']))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                   (now_str, r['raw_id'], r['name'], -spend_brutto, 'в заготовку', f"На П/Ф: {prep['name']} (x{batches})", -round(spend_brutto * r['cost_price'], 1), session['username']))
    recalc_prep_cost(db, prep_id)
    prep = db.execute("SELECT * FROM ingredients WHERE id=?", (prep_id,)).fetchone()
    out_weight = round(float(prep['prep_yield'] or 1) * batches, 4)
    db.execute("UPDATE ingredients SET stock = ROUND(stock + ?, 4) WHERE id=?", (out_weight, prep_id))
    db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
               (now_str, prep_id, prep['name'], out_weight, 'варка П/Ф', f"Приготовлено партий: {batches}", round(out_weight * prep['cost_price'], 1), session['username']))
    db.commit()
    return redirect(url_for('warehouse_panel') + '#tab-preps')

@app.route('/admin/warehouse/butcher', methods=['POST'])
@login_required('admin')
def admin_warehouse_butcher():
    db = get_db()
    raw_id = int(request.form.get('raw_id') or 0)
    raw_weight = max(0.0, float(request.form.get('raw_weight') or 0))
    raw_ing = db.execute("SELECT * FROM ingredients WHERE id=?", (raw_id,)).fetchone()
    if not raw_ing or raw_weight <= 0 or raw_ing['stock'] < raw_weight:
        return "<script>alert('Недостаточно сырья на складе для разделки!');window.location='/warehouse';</script>", 400
    out1_id = int(request.form.get('out1_id') or 0); out1_w = max(0.0, float(request.form.get('out1_weight') or 0))
    out2_id = int(request.form.get('out2_id') or 0); out2_w = max(0.0, float(request.form.get('out2_weight') or 0))
    total_usable = out1_w + out2_w
    if total_usable <= 0 or total_usable > raw_weight:
        return "<script>alert('Выход филе не может быть 0 или превышать вес тушки!');window.location='/warehouse';</script>", 400

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_batch_cost = raw_weight * float(raw_ing['cost_price'] or 0)
    actual_waste_pct = round(max(0.0, (raw_weight - total_usable) / raw_weight * 100.0), 1)
    db.execute("UPDATE ingredients SET stock = ROUND(stock - ?, 4), waste_pct = ? WHERE id=?", (raw_weight, actual_waste_pct, raw_id))
    db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
               (now_str, raw_id, raw_ing['name'], -raw_weight, 'разделка', f"Разделка (отход {actual_waste_pct}%)", -round(total_batch_cost, 1), session['username']))
    eff_cost_per_unit = round(total_batch_cost / total_usable, 4)
    for oid, ow in [(out1_id, out1_w), (out2_id, out2_w)]:
        if oid > 0 and ow > 0:
            oing = db.execute("SELECT * FROM ingredients WHERE id=?", (oid,)).fetchone()
            if oing:
                db.execute("UPDATE ingredients SET stock = ROUND(stock + ?, 4), cost_price = ? WHERE id=?", (ow, eff_cost_per_unit, oid))
                db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                           (now_str, oid, oing['name'], ow, 'выход разделки', f"Из {raw_ing['name']} ({raw_weight})", round(ow * eff_cost_per_unit, 1), session['username']))
    db.commit()
    return redirect(url_for('warehouse_panel'))

@app.route('/admin/warehouse/inventory', methods=['POST'])
@login_required('admin')
def admin_warehouse_inventory():
    db = get_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    decompose = request.form.get('decompose_preps') == '1'
    ings = {i['id']: dict(i) for i in db.execute("SELECT * FROM ingredients").fetchall()}
    extra_raw = {}
    if decompose:
        for pid, p in ings.items():
            if p['is_prep']:
                val_str = request.form.get(f"fact_{pid}", "").strip()
                if val_str != "":
                    try:
                        fact_prep = max(0.0, float(val_str))
                        yield_amt = float(p['prep_yield'] or 1)
                        if fact_prep > 0 and yield_amt > 0:
                            ratio = fact_prep / yield_amt
                            for r in db.execute("SELECT raw_id, amount FROM prep_recipes WHERE prep_id=?", (pid,)).fetchall():
                                raw_ing = ings.get(r['raw_id'])
                                w = min(95.0, max(0.0, float(raw_ing['waste_pct'] or 0))) if raw_ing else 0
                                factor = 1.0 / (1.0 - w / 100.0) if w > 0 else 1.0
                                extra_raw[r['raw_id']] = extra_raw.get(r['raw_id'], 0.0) + (r['amount'] * ratio * factor)
                    except Exception: pass

    for ing_id, ing in ings.items():
        if decompose and ing['is_prep']: continue
        field_val = request.form.get(f"fact_{ing_id}", "").strip()
        if field_val != "":
            try:
                fact = max(0.0, float(field_val)) + extra_raw.get(ing_id, 0.0)
                diff = round(fact - ing['stock'], 4)
                if abs(diff) > 0.0001:
                    note = f"Было: {round(ing['stock'],3)}, Факт: {round(fact,3)}"
                    if ing_id in extra_raw: note += f" (вкл. +{round(extra_raw[ing_id],2)} из П/Ф)"
                    db.execute("UPDATE ingredients SET stock = ? WHERE id=?", (round(fact, 4), ing_id))
                    db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username) VALUES (?,?,?,?,?,?,?,?)",
                               (now_str, ing_id, ing['name'], diff, 'ревизия', note, round(diff * ing['cost_price'], 1), session['username']))
            except Exception: pass
    db.commit()
    return redirect(url_for('warehouse_panel') + '#tab-logs')

@app.route('/admin/ingredient/delete/<int:ing_id>', methods=['POST'])
@login_required('admin')
def admin_ingredient_delete(ing_id):
    db = get_db(); db.execute("DELETE FROM ingredients WHERE id=?", (ing_id,)); db.commit(); return redirect(url_for('warehouse_panel'))

@app.route('/analytics')
@login_required('admin')
def analytics_panel():
    db = get_db()
    stats = db.execute("SELECT COALESCE(SUM(total),0) as rev, COALESCE(SUM(cost),0) as cost FROM orders WHERE status != 'cancelled'").fetchone()
    total_rev = stats['rev'] or 0; total_cost = stats['cost'] or 0; total_profit = total_rev - total_cost
    return render_template('analytics.html', total_rev=total_rev, total_cost=total_cost, total_profit=total_profit, margin=round((total_profit / total_rev * 100) if total_rev > 0 else 0, 1), recent_orders=db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 15").fetchall())

@app.route('/autopilot')
@login_required('admin')
def autopilot_panel():
    db = get_db()
    menu_rows = db.execute("SELECT * FROM menu WHERE available=1 ORDER BY category, name").fetchall()
    sales_rows = db.execute("SELECT oi.name, SUM(oi.qty) as sold_qty FROM order_items oi JOIN orders o ON oi.order_id = o.id WHERE o.status != 'cancelled' GROUP BY oi.name").fetchall()
    sales_map = {r['name']: (r['sold_qty'] or 0) for r in sales_rows}
    avg_qty = (sum(sales_map.values()) / len(menu_rows)) if menu_rows else 1
    menu_matrix = []
    for m in menu_rows:
        recs = db.execute("SELECT r.amount, ing.cost_price, COALESCE(ing.waste_pct, 0) as waste_pct FROM recipes r JOIN ingredients ing ON r.ingredient_id = ing.id WHERE r.menu_id=?", (m['id'],)).fetchall()
        weight = sum(r['amount'] for r in recs)
        cost = sum(r['amount'] * (1.0 / (1.0 - min(95.0, max(0.0, float(r['waste_pct'] or 0))) / 100.0) if r['waste_pct'] else 1.0) * r['cost_price'] for r in recs)
        margin_rub = m['price'] - cost
        fc_pct = round((cost / m['price'] * 100), 1) if m['price'] > 0 else 0
        sold = sales_map.get(m['name'], 0)
        is_roll = 'ролл' in (m['category'] or '').lower() or 'ролл' in m['name'].lower()
        piece_weight = round(weight / 8.0, 1) if (is_roll and weight > 0) else 0
        if sold >= avg_qty and fc_pct <= 33: quadrant, q_color, advice = "⭐ Звезда", "#10b981", "Держать в топе витрины"
        elif sold >= avg_qty and fc_pct > 33: quadrant, q_color, advice = "🐄 Дойная корова", "#3b82f6", "Поднять цену на +30..50 ₽"
        elif sold < avg_qty and fc_pct <= 33: quadrant, q_color, advice = "🧩 Загадка", "#f59e0b", "Добавить в сеты / допродажу"
        else: quadrant, q_color, advice = "🐕 Кандидат на замену", "#ef4444", "Проверить ТТК"
        menu_matrix.append({'id': m['id'], 'name': m['name'], 'category': m['category'], 'price': m['price'], 'cost': round(cost, 1), 'margin': round(margin_rub, 1), 'fc_pct': fc_pct, 'weight': round(weight), 'piece_weight': piece_weight, 'sold': sold, 'quadrant': quadrant, 'q_color': q_color, 'advice': advice})

    weekday = datetime.now().weekday()
    day_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница 🔥', 'Суббота 🔥', 'Воскресенье']
    day_mult = 1.45 if weekday in (4, 5) else (1.2 if weekday == 6 else 1.0)
    ings = db.execute("SELECT * FROM ingredients ORDER BY is_prep DESC, name").fetchall()
    prep_plan = []; purchase_list = []
    for ing in ings:
        used_row = db.execute("SELECT SUM(oi.qty * r.amount) as total_used, COUNT(DISTINCT date(o.created_at)) as active_days FROM order_items oi JOIN orders o ON oi.order_id = o.id JOIN recipes r ON r.menu_id = oi.menu_id WHERE r.ingredient_id = ? AND o.status != 'cancelled'", (ing['id'],)).fetchone()
        days_cnt = max(1, used_row['active_days'] or 1)
        avg_daily = (used_row['total_used'] or 0) / days_cnt
        if avg_daily <= 0: avg_daily = float(ing['prep_yield'] or 1) * 0.5 if ing['is_prep'] else 5.0
        rec_today = round(avg_daily * day_mult, 2)
        deficit = round(max(0.0, rec_today - ing['stock']), 2)
        prep_plan.append({'id': ing['id'], 'name': ing['name'], 'unit': ing['unit'], 'is_prep': ing['is_prep'], 'stock': round(ing['stock'], 2), 'recommended': rec_today, 'to_make': deficit})
        if deficit > 0 and not ing['is_prep']:
            purchase_list.append(f"• {ing['name']}: заказать {round(deficit * 2, 2)} {ing['unit']} (остаток: {round(ing['stock'], 2)} {ing['unit']})")
    return render_template('autopilot.html', menu_matrix=menu_matrix, prep_plan=prep_plan, purchase_text="\n".join(purchase_list) if purchase_list else "Все сырье в достатке!", today_name=day_names[weekday], day_mult=day_mult)

@app.route('/board')
def public_board(): return render_template('board.html')

@app.route('/api/kitchen_load')
def api_kitchen_load():
    db = get_db()
    active_cnt = db.execute("SELECT COUNT(*) FROM orders WHERE status IN ('new', 'cooking')").fetchone()[0]
    ready_orders = [dict(r) for r in db.execute("SELECT id, delivery_type FROM orders WHERE status='ready' ORDER BY id DESC LIMIT 12").fetchall()]
    cooking_orders = [dict(r) for r in db.execute("SELECT id, delivery_type FROM orders WHERE status IN ('new', 'cooking') ORDER BY id DESC LIMIT 12").fetchall()]
    if active_cnt <= 3: level, est_min, color = "🟢 Кухня свободна", 35, "#10b981"
    elif active_cnt <= 7: level, est_min, color = "🟡 Средняя загрузка", 55, "#f59e0b"
    else: level, est_min, color = "🔴 ПИК / ЗАПАРА", 75, "#ef4444"
    return jsonify({"active_count": active_cnt, "level": level, "est_minutes": est_min, "color": color, "ready": ready_orders, "cooking": cooking_orders})

# ЗАЩИЩЕННЫЙ ТРЕКИНГ И ОТЗЫВЫ ПО PUBLIC_TOKEN (Пункт 2)
def find_order_by_ref(ref):
    db = get_db()
    row = db.execute("SELECT * FROM orders WHERE public_token=?", (str(ref),)).fetchone()
    if not row and str(ref).isdigit() and 'user_id' in session:
        row = db.execute("SELECT * FROM orders WHERE id=?", (int(ref),)).fetchone()
    return row

@app.route('/track/<ref>')
def track_order(ref):
    order = find_order_by_ref(ref)
    if not order: abort(404)
    return render_template('track.html', order_id=order['public_token'] or order['id'])

@app.route('/api/track_order/<ref>')
def api_track_order(ref):
    order = find_order_by_ref(ref)
    if not order: return jsonify({"error": "Not found"}), 404
    return jsonify({"status": order['status'], "total": order['total'], "created_at": order['created_at']})

@app.route('/rate/<ref>', methods=['GET', 'POST'])
def rate_order(ref):
    db = get_db(); order = find_order_by_ref(ref)
    if not order: abort(404)
    if request.method == 'POST':
        if order['rating'] > 0: return "<h1 style='text-align:center;color:#ff9f0a;font-family:sans-serif;margin-top:50px'>Вы уже оставили отзыв!</h1>"
        rating_val = min(5, max(1, int(request.form.get('rating', 5))))
        db.execute("UPDATE orders SET rating=?, review_text=? WHERE id=?", (rating_val, clean_str(request.form.get('review_text', ''), 400), order['id'])); db.commit()
        return "<h1 style='text-align:center;color:#30d158;font-family:sans-serif;margin-top:50px'>Спасибо за отзыв!</h1>"
    return render_template('rate.html', order=order)

@app.route('/admin/brand_settings', methods=['POST'])
@login_required('admin')
def admin_brand_settings():
    for k in DEFAULT_BRAND.keys():
        set_setting(k, clean_str(request.form.get(k, ''), 200))
    return redirect(url_for('admin_panel'))

@app.route('/admin/shop_status', methods=['POST'])
@login_required('admin')
def admin_shop_status():
    if request.form.get('status') in ['auto', 'open', 'closed']: set_setting('shop_status', request.form.get('status'))
    return redirect(url_for('admin_panel'))

@app.route('/admin/banner/add', methods=['POST'])
@login_required('admin')
def admin_banner_add():
    file = request.files.get('image')
    if file and file.filename and allowed_file(file.filename):
        filename = 'banner_' + str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower(); file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        db = get_db(); db.execute("INSERT INTO banners (image, title) VALUES (?,?)", (filename, clean_str(request.form.get('title', ''), 100))); db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/banner/delete/<int:b_id>', methods=['POST'])
@login_required('admin')
def admin_banner_delete(b_id):
    db = get_db(); db.execute("DELETE FROM banners WHERE id=?", (b_id,)); db.commit(); return redirect(url_for('admin_panel'))

# БЕЗОПАСНЫЙ WAL-БЭКАП ЧЕРЕЗ SQLITE BACKUP API (Пункт 6)
@app.route('/admin/backup_db')
@login_required('admin')
def backup_db():
    tmp = tempfile.NamedTemporaryFile(prefix='sushi_bkp_', suffix='.db', delete=False)
    tmp.close()
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(tmp.name)
    with dst:
        src.backup(dst)
    dst.close(); src.close()
    return send_file(tmp.name, as_attachment=True, download_name=f"sushi_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")

@app.route('/admin')
@login_required('admin')
def admin_panel():
    db = get_db(); today = datetime.now().strftime("%Y-%m-%d")
    stats = db.execute("SELECT COUNT(*) cnt, COALESCE(SUM(total), 0) rev FROM orders WHERE date(created_at) = ? AND status != 'cancelled'", (today,)).fetchone()
    avg_check = (stats['rev'] / stats['cnt']) if stats['cnt'] > 0 else 0
    rating_row = db.execute("SELECT AVG(rating) as avg_r, COUNT(rating) as count_r FROM orders WHERE rating > 0").fetchone()
    avg_rating = round(rating_row['avg_r'], 1) if rating_row['avg_r'] else 0; reviews_count = rating_row['count_r']
    chart_data = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        r = db.execute("SELECT COALESCE(SUM(total),0) rev FROM orders WHERE date(created_at)=? AND status!='cancelled'", (d,)).fetchone()
        chart_data.append({"date": d[5:], "rev": r['rev']})
    top_items = db.execute("SELECT oi.name, SUM(oi.qty) total_qty FROM order_items oi JOIN orders o ON oi.order_id = o.id WHERE date(o.created_at) = ? AND o.status != 'cancelled' GROUP BY oi.name ORDER BY total_qty DESC LIMIT 5", (today,)).fetchall()
    top_clients = db.execute("SELECT phone, COUNT(*) cnt, SUM(total) sum FROM orders WHERE date(created_at) = ? AND status != 'cancelled' AND phone != '' GROUP BY phone ORDER BY sum DESC LIMIT 5", (today,)).fetchall()
    return render_template('admin.html', stats=stats, avg_check=avg_check, chart_data=chart_data, top_items=top_items, top_clients=top_clients, menu=db.execute("SELECT * FROM menu ORDER BY sort_weight DESC, category, name").fetchall(), users=db.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall(), zones=db.execute("SELECT * FROM zones").fetchall(), promos=db.execute("SELECT * FROM promocodes ORDER BY id DESC").fetchall(), avg_rating=avg_rating, reviews_count=reviews_count, recent_reviews=db.execute("SELECT * FROM orders WHERE rating > 0 ORDER BY id DESC LIMIT 5").fetchall(), shop_status=get_setting('shop_status'), banners=db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall())

@app.route('/admin/users/add', methods=['POST'])
@login_required('admin')
def admin_user_add():
    username = clean_str(request.form.get('username', ''), 40); password = request.form.get('password', ''); role = request.form.get('role')
    if username and len(password) >= 6 and role in ('admin', 'cashier', 'kitchen', 'courier'):
        db = get_db()
        db.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?) ON CONFLICT(username) DO UPDATE SET password_hash=?, role=?",
                   (username, generate_password_hash(password), role, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), generate_password_hash(password), role))
        db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required('admin')
def admin_user_delete(user_id):
    if user_id == session.get('user_id'): return "Вы не можете удалить свой аккаунт!", 400
    db = get_db(); db.execute("DELETE FROM users WHERE id=?", (user_id,)); db.commit(); return redirect(url_for('admin_panel'))

@app.route('/admin/export/orders')
@login_required('admin')
def export_orders():
    db = get_db(); orders = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Заказы"
    ws.append(["ID", "Дата", "Клиент", "Адрес", "Тип", "Сумма", "Себестоимость", "Оплата", "Наличные", "Карта", "Сдача с", "Курьер", "Статус", "Промокод", "Оценка"])
    for o in orders: ws.append([o['id'], o['created_at'], o['phone'], o['address'], o['delivery_type'], o['total'], o['cost'], o['payment_method'], o['payment_cash'], o['payment_card'], o['change_from'], o['courier_name'], o['status'], o['promo_code'], o['rating']])
    output = io.BytesIO(); wb.save(output); output.seek(0)
    response = make_response(output.getvalue()); response.headers["Content-Disposition"] = "attachment; filename=orders.xlsx"; response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; return response

@app.route('/admin/export/clients')
@login_required('admin')
def export_clients():
    db = get_db(); clients = db.execute("SELECT * FROM clients ORDER BY total_spent DESC").fetchall()
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Клиенты"
    ws.append(["Телефон", "Заказов", "Потрачено (LTV)", "Бонусы", "Уровень", "Последний заказ"])
    for c in clients: ws.append([c['phone'], c['orders_count'], c['total_spent'], c['bonuses'], c['level'], c['last_order_at']])
    output = io.BytesIO(); wb.save(output); output.seek(0)
    response = make_response(output.getvalue()); response.headers["Content-Disposition"] = "attachment; filename=clients.xlsx"; response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; return response

@app.route('/api/check_promo', methods=['POST'])
def check_promo():
    data = request.json or {}; code = clean_str(data.get('code', ''), 30).upper()
    promo = get_db().execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (code,)).fetchone()
    if promo: return jsonify({"success": True, "type": promo['discount_type'], "value": promo['discount_value']})
    return jsonify({"success": False, "error": "Промокод не найден"})

@app.route('/admin/promo/add', methods=['POST'])
@login_required('admin')
def admin_promo_add():
    code = clean_str(request.form.get('code', ''), 30).upper(); dtype = request.form.get('type'); val = request.form.get('value')
    if code and dtype in ('percent', 'rub') and val:
        db = get_db()
        try: db.execute("INSERT INTO promocodes (code, discount_type, discount_value) VALUES (?,?,?)", (code, dtype, max(1, int(val)))); db.commit()
        except sqlite3.IntegrityError: pass
    return redirect(url_for('admin_panel'))

@app.route('/admin/promo/delete/<int:promo_id>', methods=['POST'])
@login_required('admin')
def admin_promo_delete(promo_id):
    db = get_db(); db.execute("DELETE FROM promocodes WHERE id=?", (promo_id,)); db.commit(); return redirect(url_for('admin_panel'))

@app.route('/admin/menu/add', methods=['POST'])
@login_required('admin')
def admin_menu_add():
    name = clean_str(request.form.get('name'), 100); price = request.form.get('price'); category = clean_str(request.form.get('category'), 60)
    file = request.files.get('image'); filename = ''
    if file and file.filename and allowed_file(file.filename):
        filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower(); file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    if name and price and category:
        db = get_db(); db.execute("INSERT INTO menu (name, price, category, image, composition, modifiers, sort_weight) VALUES (?,?,?,?,?,?,?)", (name, max(0, int(price)), category, filename, clean_str(request.form.get('composition', ''), 250), clean_str(request.form.get('modifiers', ''), 200), int(request.form.get('sort_weight', 0) or 0))); db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/menu/edit/<int:menu_id>', methods=['GET', 'POST'])
@login_required('admin')
def admin_menu_edit(menu_id):
    db = get_db()
    if request.method == 'POST':
        name = clean_str(request.form.get('name'), 100); price = max(0, int(request.form.get('price') or 0)); category = clean_str(request.form.get('category'), 60)
        comp = clean_str(request.form.get('composition', ''), 250); mods = clean_str(request.form.get('modifiers', ''), 200); sw = int(request.form.get('sort_weight', 0) or 0)
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower(); file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            db.execute("UPDATE menu SET name=?, price=?, category=?, composition=?, modifiers=?, image=?, sort_weight=? WHERE id=?", (name, price, category, comp, mods, filename, sw, menu_id))
        else:
            db.execute("UPDATE menu SET name=?, price=?, category=?, composition=?, modifiers=?, sort_weight=? WHERE id=?", (name, price, category, comp, mods, sw, menu_id))
        db.execute("DELETE FROM recipes WHERE menu_id=?", (menu_id,))
        for key, val in request.form.items():
            if key.startswith('ing_') and val.strip():
                amt = float(val)
                if amt > 0: db.execute("INSERT INTO recipes (menu_id, ingredient_id, amount) VALUES (?,?,?)", (menu_id, int(key.split('_')[1]), amt))
        db.commit(); return redirect(url_for('admin_panel'))
    return render_template('edit_menu.html', item=db.execute("SELECT * FROM menu WHERE id=?", (menu_id,)).fetchone(), ingredients=db.execute("SELECT * FROM ingredients ORDER BY name").fetchall(), recipe={r['ingredient_id']: r['amount'] for r in db.execute("SELECT * FROM recipes WHERE menu_id=?", (menu_id,)).fetchall()})

@app.route('/admin/menu/toggle/<int:menu_id>', methods=['POST'])
@login_required('admin')
def admin_menu_toggle(menu_id):
    db = get_db(); db.execute("UPDATE menu SET available = 1 - available WHERE id=?", (menu_id,)); db.commit(); return redirect(url_for('admin_panel'))

@app.route('/admin/menu/stop/<int:menu_id>', methods=['POST'])
@login_required('admin')
def admin_menu_stop(menu_id):
    db = get_db(); db.execute("UPDATE menu SET stop_list = 1 - stop_list WHERE id=?", (menu_id,)); db.commit(); return redirect(url_for('admin_panel'))

@app.route('/admin/menu/delete/<int:menu_id>', methods=['POST'])
@login_required('admin')
def admin_menu_delete(menu_id):
    db = get_db(); db.execute("DELETE FROM menu WHERE id=?", (menu_id,)); db.commit(); return redirect(url_for('admin_panel'))

@app.route('/admin/menu/clear', methods=['POST'])
@login_required('admin')
def admin_menu_clear():
    db = get_db(); db.execute("DELETE FROM menu"); db.commit(); return redirect(url_for('admin_panel'))

@app.route('/site')
def public_site():
    db = get_db()
    return render_template('public_site.html', menu=db.execute("SELECT * FROM menu WHERE available=1 AND stop_list=0 ORDER BY sort_weight DESC, category, name").fetchall(), categories=db.execute("SELECT DISTINCT category FROM menu WHERE available=1 AND stop_list=0 ORDER BY category").fetchall(), shop_open=is_shop_open(), banners=db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall())

# ЗАЩИЩЕННЫЙ ПУБЛИЧНЫЙ ЗАКАЗ (Анти-спам, Идемпотентность, Отложенные бонусы)
@app.route('/api/public_order', methods=['POST'])
def public_order():
    if not is_shop_open(): return jsonify({"error": "Приём заказов сейчас закрыт."}), 400
    ip = request.remote_addr or 'local'
    if not check_rate_limit(f"pub_order_{ip}", 4, 600):
        return jsonify({"error": "Слишком много заказов с вашего адреса. Подождите несколько минут."}), 429

    data = request.json or {}
    phone = clean_str(data.get('phone', ''), 25)
    if not re.match(r'^\+?[0-9\-\(\)\s]{10,18}$', phone):
        return jsonify({"error": "Укажите корректный номер телефона (10–15 цифр)"}), 400

    delivery_type = 'самовывоз' if data.get('delivery_type') == 'самовывоз' else 'доставка'
    address = 'Самовывоз' if delivery_type == 'самовывоз' else clean_str(data.get('address', ''), 200)
    if delivery_type == 'доставка' and len(address) < 4:
        return jsonify({"error": "Укажите точный адрес доставки"}), 400

    items, val_err = validate_and_prepare_items(data.get('items', []), allow_stop_list=False)
    if val_err: return jsonify({"error": val_err}), 400

    # Ключ идемпотентности на 60 секунд против двойного клика
    idem_raw = f"{ip}|{phone}|{address}|{[(i['id'], i['qty']) for i in items]}|{int(time.time() // 60)}"
    idem_key = hashlib.sha256(idem_raw.encode('utf-8')).hexdigest()[:24]

    db = get_db()
    dup = db.execute("SELECT public_token FROM orders WHERE idempotency_key=?", (idem_key,)).fetchone()
    if dup:
        return jsonify({"success": True, "order_id": dup['public_token']})

    shift = ensure_open_shift()
    subtotal = sum(i['price'] * i['qty'] for i in items)
    promo_code = clean_str(data.get('promo_code', ''), 30).upper(); promo_discount = 0
    if promo_code:
        promo = db.execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (promo_code,)).fetchone()
        if promo: promo_discount = (subtotal * promo['discount_value']) // 100 if promo['discount_type'] == 'percent' else promo['discount_value']

    total = max(0, subtotal - promo_discount)
    pay_method = 'наличные' if data.get('payment_method') == 'наличные' else 'карта'
    change_from = max(0, int(data.get('change_from', 0) or 0))
    comment = clean_str(data.get('comment', ''), 250)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pub_token = secrets.token_urlsafe(12)

    try:
        cur = db.execute("""
            INSERT INTO orders (
                created_at, status, total, cost, address, phone, comment, shift_id,
                payment_method, payment_cash, payment_card, change_from, delivery_type,
                promo_code, source, public_token, stock_deducted, bonus_awarded, idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)
        """, (now_str, 'new', total, 0, address, phone, comment, shift['id'], pay_method, 0, 0, change_from, delivery_type, promo_code, 'Сайт', pub_token, idem_key))
        order_id = cur.lastrowid

        err, total_cost = adjust_stock_for_order(order_id, items, direction=-1, actor='Сайт', reason_prefix='Заказ сайта')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400

        for i in items:
            db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                       (order_id, i['id'], i['name'], i['price'], i['qty'], i['mods']))

        pay_cash, pay_card = record_order_payments(db, order_id, shift['id'], pay_method, total, total if pay_method == 'наличные' else 0, 0)
        db.execute("UPDATE orders SET cost=?, payment_cash=?, payment_card=?, stock_deducted=1 WHERE id=?", (total_cost, pay_cash, pay_card, order_id))
        enqueue_print_job(db, order_id, 'receipt')
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": "Ошибка сохранения заказа"}), 500

    send_tg_async(f"🌐 <b>НОВЫЙ ЗАКАЗ С САЙТА #{order_id}</b>\n💰 Сумма: <b>{total} ₽</b> ({pay_method})\n📞 Тел: {phone}\n📍 Адрес: {address}")
    return jsonify({"success": True, "order_id": pub_token})

# ЗАКРЫТ ДОСТУП К ПДн БЕЗ АВТОРИЗАЦИИ (Пункт 2)
@app.route('/api/site/client/<phone>')
def site_client(phone):
    if 'user_id' not in session or session.get('role') not in ('admin', 'cashier'):
        return jsonify({"success": False})
    order = get_db().execute("SELECT * FROM orders WHERE phone=? ORDER BY id DESC LIMIT 1", (phone,)).fetchone()
    if order:
        return jsonify({"success": True, "address": order['address'], "last_order": [dict(i) for i in get_db().execute("SELECT * FROM order_items WHERE order_id=?", (order['id'],)).fetchall()]})
    return jsonify({"success": False})

@app.route('/api/client/<phone>')
@login_required('admin', 'cashier')
def api_client(phone):
    client = get_db().execute("SELECT * FROM clients WHERE phone=?", (phone,)).fetchone()
    if client: return jsonify({"success": True, "bonuses": client['bonuses'], "level": client['level']})
    return jsonify({"success": False})

@app.route('/api/create_order', methods=['POST'])
@login_required('admin', 'cashier')
def create_order():
    if not is_shop_open(): return jsonify({"error": "Прием заказов приостановлен."}), 400
    shift = get_open_shift()
    if not shift: return jsonify({"error": "Смена не открыта! Сначала откройте кассовую смену."}), 400

    data = request.json or {}
    items, val_err = validate_and_prepare_items(data.get('items', []), allow_stop_list=False)
    if val_err: return jsonify({"error": val_err}), 400

    db = get_db()
    phone = clean_str(data.get('phone', ''), 25)
    delivery_type = 'самовывоз' if data.get('delivery_type') == 'самовывоз' else 'доставка'
    address = 'Самовывоз' if delivery_type == 'самовывоз' else clean_str(data.get('address', ''), 200)
    zone_str = clean_str(data.get('zone', ''), 80) if delivery_type == 'доставка' else ''
    comment = clean_str(data.get('comment', ''), 250)

    subtotal = sum(i['price'] * i['qty'] for i in items)
    discount_val = max(0, int(data.get('discount', 0) or 0))
    discount_type = 'percent' if data.get('discount_type') == 'percent' else 'rub'
    manual_discount = (subtotal * min(100, discount_val) // 100) if discount_type == 'percent' else discount_val

    promo_code = clean_str(data.get('promo_code', ''), 30).upper(); promo_discount = 0
    if promo_code:
        promo = db.execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (promo_code,)).fetchone()
        if promo: promo_discount = (subtotal * promo['discount_value']) // 100 if promo['discount_type'] == 'percent' else promo['discount_value']

    client = db.execute("SELECT * FROM clients WHERE phone=?", (phone,)).fetchone() if phone else None
    client_level = client['level'] if client else 'bronze'
    delivery_price = parse_zone_price(zone_str, delivery_type, client_level)
    total = max(0, subtotal - manual_discount - promo_discount) + delivery_price

    use_bonus = max(0, int(data.get('use_bonus', 0) or 0))
    actual_bonus = 0
    if use_bonus > 0 and client:
        actual_bonus = min(use_bonus, client['bonuses'], total)
        total = max(0, total - actual_bonus)

    payment_method = clean_str(data.get('payment_method', 'не указан'), 30)
    change_from = max(0, int(data.get('change_from', 0) or 0))
    scheduled_time = clean_str(data.get('scheduled_time', ''), 30) or None
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pub_token = secrets.token_urlsafe(12)

    try:
        cur = db.execute("""
            INSERT INTO orders (
                created_at, status, total, cost, address, phone, comment, shift_id, cashier_id, source,
                payment_method, payment_cash, payment_card, change_from, delivery_type, delivery_zone, delivery_price,
                used_bonus, scheduled_time, discount, discount_type, promo_code, public_token, stock_deducted, bonus_awarded
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)
        """, (now_str, 'new', total, 0, address, phone, comment, shift['id'], session['user_id'], 'Касса', payment_method, 0, 0, change_from, delivery_type, zone_str, delivery_price, actual_bonus, scheduled_time, discount_val, discount_type, promo_code, pub_token))
        order_id = cur.lastrowid

        err, total_cost = adjust_stock_for_order(order_id, items, direction=-1, actor=session['username'], reason_prefix='Касса')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400

        if actual_bonus > 0 and phone:
            db.execute("UPDATE clients SET bonuses = MAX(0, bonuses - ?) WHERE phone=?", (actual_bonus, phone))

        for i in items:
            db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                       (order_id, i['id'], i['name'], i['price'], i['qty'], i['mods']))

        pay_cash, pay_card = record_order_payments(db, order_id, shift['id'], payment_method, total, data.get('pay_cash', 0), session['user_id'])
        db.execute("UPDATE orders SET cost=?, payment_cash=?, payment_card=?, stock_deducted=1 WHERE id=?", (total_cost, pay_cash, pay_card, order_id))
        enqueue_print_job(db, order_id, 'receipt')
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500

    send_tg_async(f"🖥️ <b>ЗАКАЗ С КАССЫ #{order_id}</b>\n💰 Сумма: <b>{total} ₽</b> ({payment_method})\n📞 Тел: {phone or '—'}\n📍 Адрес: {address or '—'}")
    return jsonify({"success": True, "order_id": order_id, "total": total})

@app.route('/api/orders')
@login_required()
def api_orders():
    status = request.args.get('status'); db = get_db()
    if status:
        if status == 'active': rows = db.execute("SELECT * FROM orders WHERE status IN ('new', 'cooking') ORDER BY id").fetchall()
        elif status == 'all_active': rows = db.execute("SELECT * FROM orders WHERE status IN ('new', 'cooking', 'ready', 'delivering') ORDER BY id").fetchall()
        else: rows = db.execute("SELECT * FROM orders WHERE status=? ORDER BY id", (status,)).fetchall()
    else: rows = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) | {"items": [dict(i) for i in db.execute("SELECT * FROM order_items WHERE order_id=?", (r['id'],)).fetchall()]} for r in rows])

@app.route('/api/courier/stats')
@login_required('courier', 'admin')
def api_courier_stats():
    db = get_db(); today = datetime.now().strftime("%Y-%m-%d"); name = session['username']
    row = db.execute("SELECT COUNT(*) cnt, COALESCE(SUM(payment_cash),0) cash_on_hand FROM orders WHERE date(created_at)=? AND courier_name=? AND status IN ('delivering', 'done')", (today, name)).fetchone()
    return jsonify({"courier": name, "delivered_count": row['cnt'], "cash_on_hand": row['cash_on_hand']})

# СТРОГИЙ STATE MACHINE ПЕРЕХОДОВ И РОЛЕЙ + СИНХРОНИЗАЦИЯ СКЛАДА И ПЛАТЕЖЕЙ (Пункт 5)
ALLOWED_TRANSITIONS = {
    'new': {'cooking', 'cancelled'},
    'cooking': {'ready', 'cancelled'},
    'ready': {'delivering', 'done', 'cancelled'},
    'delivering': {'done', 'cancelled'},
    'done': {'cancelled'},
    'cancelled': set()
}

ROLE_ALLOWED_TARGETS = {
    'kitchen': {'cooking', 'ready'},
    'courier': {'delivering', 'done'},
    'cashier': {'cooking', 'ready', 'delivering', 'done', 'cancelled'},
    'admin': {'cooking', 'ready', 'delivering', 'done', 'cancelled'}
}

@app.route('/api/set_status/<int:order_id>', methods=['POST'])
@login_required()
def set_status(order_id):
    data = request.json or {}
    new_status = data.get('status')
    role = session.get('role', 'cashier')
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return jsonify({"error": "Заказ не найден"}), 404

    cur_status = order['status']
    if cur_status == new_status:
        return jsonify({"success": True})

    if new_status not in ALLOWED_TRANSITIONS.get(cur_status, set()):
        return jsonify({"error": f"Недопустимый переход статуса: {cur_status} -> {new_status}"}), 400

    if new_status not in ROLE_ALLOWED_TARGETS.get(role, set()):
        return jsonify({"error": f"Роли '{role}' запрещено устанавливать статус '{new_status}'"}), 403

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if new_status == 'cancelled':
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
            db.execute("UPDATE orders SET status='done', bonus_awarded=1 WHERE id=?", (order_id,))

        elif new_status == 'cooking':
            db.execute("UPDATE orders SET status='cooking', cook_start_time=? WHERE id=?", (now_str, order_id))
        elif new_status == 'ready':
            db.execute("UPDATE orders SET status='ready', cook_end_time=? WHERE id=?", (now_str, order_id))
        elif new_status == 'delivering':
            c_name = clean_str(data.get('courier_name') or session.get('username', ''), 50)
            db.execute("UPDATE orders SET status='delivering', courier_name=? WHERE id=?", (c_name, order_id))

        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.context_processor
def inject_csrf_token():


@app.route('/api/customer_lookup')
def api_customer_lookup():
    phone = request.args.get('phone', '').strip()
    if len(phone) < 5:
        return jsonify({'found': False})
    db = get_db()
    rows = db.execute(
        "SELECT address, comment, total, created_at FROM orders WHERE phone LIKE ? ORDER BY id DESC LIMIT 20",
        (f"%{phone}%",)
    ).fetchall()
    if not rows:
        return jsonify({'found': False})
    last_addr = next((r['address'] for r in rows if r['address'] and r['address'] not in ('Самовывоз', '')), '')
    total_spent = sum(r['total'] or 0 for r in rows)
    return jsonify({
        'found': True,
        'orders_count': len(rows),
        'last_address': last_addr,
        'total_spent': total_spent
    })

if __name__ == '__main__':
    init_db()
    print("="*55)
    print("🛡️ СИСТЕМА КРЕВЕТКА PRO (PRODUCTION HARDENED) ЗАПУЩЕНА!")
    print("="*55)
    if os.environ.get('SUSHI_DEBUG') == '1':
        app.run(host='127.0.0.1', port=int(os.environ.get('SUSHI_PORT', '5000')), debug=True, use_reloader=False, threaded=True)
    else:
        from waitress import serve
        host = os.environ.get('SUSHI_HOST', '0.0.0.0')
        port = int(os.environ.get('SUSHI_PORT', '5000'))
        print(f"🚀 Waitress слушает http://{host}:{port}")
        serve(app, host=host, port=port, threads=8)