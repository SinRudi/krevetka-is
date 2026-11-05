### ФАЙЛ: app.py
```python
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, flash, make_response, send_from_directory, send_file, abort
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, re, uuid, io, openpyxl, time, secrets, hashlib, hmac, html, tempfile, urllib.request, urllib.parse, threading

app = Flask(__name__)
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
        ('payments', 'paid_at', 'TEXT'),
        ('orders', 'used_bonus_refunded', 'INTEGER DEFAULT 0'),
        ('stock_logs', 'order_id', 'INTEGER'),
    )
    for table, column, decl in columns:
        _ensure_column(db, table, column, decl)

    db.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (3, ?)", (now,))
    db.execute("PRAGMA user_version = 3")

    # Устаревшая колонка users.password хранила копию хеша — очищаем.
    db.execute("UPDATE users SET password='' WHERE password IS NOT NULL AND password != ''")

    # P1: фиксируем время фактической оплаты у старых платежей.
    db.execute("UPDATE payments SET paid_at=created_at WHERE paid_at IS NULL AND status IN ('paid','refunded')")

    # P1: история статусов — хотя бы точка создания для старых заказов.
    db.execute("""INSERT INTO order_status_history (order_id, old_status, new_status, changed_at, changed_by, comment)
                  SELECT o.id, NULL, 'new', o.created_at, 0, 'backfill: до включения аудита'
                  FROM orders o
                  WHERE NOT EXISTS (SELECT 1 FROM order_status_history h WHERE h.order_id=o.id AND h.new_status='new')""")

    # P1: старые выданные заказы уже кредитовали клиента — не начисляем повторно.
    db.execute("UPDATE orders SET bonus_awarded=1 WHERE status='done' AND client_credited=1 AND bonus_awarded=0")
    db.execute("UPDATE orders SET used_bonus_refunded=0 WHERE used_bonus_refunded IS NULL")

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
    CREATE TABLE IF NOT EXISTS stock_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, ingredient_id INTEGER, ing_name TEXT, change_amount REAL, op_type TEXT, reason TEXT, cost_impact REAL DEFAULT 0, username TEXT, order_id INTEGER);
    CREATE TABLE IF NOT EXISTS order_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, old_status TEXT,
        new_status TEXT NOT NULL, changed_at TEXT NOT NULL, changed_by INTEGER,
        comment TEXT DEFAULT '', FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_status_history_order ON order_status_history(order_id);
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
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.before_request
def csrf_protect():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        expected = session.get('_csrf_token', '')
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token') or ''
        if not expected or not supplied or not hmac.compare_digest(str(supplied), str(expected)):
            msg = 'CSRF-токен отсутствует или неверен. Обновите страницу и повторите.'
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
                return f"Не хватает на складе: {info['name']} (нужно {round(info['amt'], 2)}, есть {round(info['stock'], 2)})", 0.0, False

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for ing_id, info in changes.items():
        delta = round(info["amt"] * direction, 4)
        impact = round(delta * info["cost"], 1)
        db.execute("UPDATE ingredients SET stock = ROUND(stock + ?, 4) WHERE id=?", (delta, ing_id))
        db.execute("INSERT INTO stock_logs (created_at, ingredient_id, ing_name, change_amount, op_type, reason, cost_impact, username, order_id) VALUES (?,?,?,?,?,?,?,?,?)",
                   (now_str, ing_id, info['name'], delta, 'продажа' if direction < 0 else 'возврат заказа', f"{reason_prefix} #{order_id}", impact, actor, order_id))
        total_cost += info["amt"] * info["cost"]

    return None, round(total_cost, 2), bool(changes)

def record_order_payments(db, order_id, shift_id, payment_method, total, raw_cash=0, cashier_id=0, paid=True):
    """Пишет новую версию платежей, не уничтожая историю. Старые paid/pending помечаются void."""
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
    """Подтверждает оплату pending-платежей (выдача заказа / оплата при получении)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if cashier_id:
        cur = db.execute("UPDATE payments SET status='paid', paid_at=COALESCE(paid_at, ?), cashier_id=? WHERE order_id=? AND status='pending'",
                         (now_str, cashier_id, order_id))
    else:
        cur = db.execute("UPDATE payments SET status='paid', paid_at=COALESCE(paid_at, ?) WHERE order_id=? AND status='pending'",
                         (now_str, order_id))
    if db.execute("SELECT 1 FROM payments WHERE order_id=? AND status='paid' LIMIT 1", (order_id,)).fetchone():
        db.execute("UPDATE orders SET payment_status='paid', paid_at=COALESCE(paid_at, ?) WHERE id=?", (now_str, order_id))
    return cur.rowcount

def settle_client_loyalty(db, order, direction=1, earned_amount=None):
    """Начисляет/откатывает LTV и бонусы. Возвращает фактически начисленную сумму."""
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
        return earned
    if not client: return 0
    earned = int(earned_amount if earned_amount is not None else (order['earned_bonus'] or 0))
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
    return earned


def log_status_change(db, order_id, old_status, new_status, changed_by=0, comment=''):
    db.execute("INSERT INTO order_status_history (order_id, old_status, new_status, changed_at, changed_by, comment) VALUES (?,?,?,?,?,?)",
               (order_id, old_status, new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), changed_by, clean_str(comment, 200)))

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
        err, new_cost, deducted = adjust_stock_for_order(order_id, validated_items, direction=-1, actor=session['username'], reason_prefix='Правка (списание)')
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
        pay_cash, pay_card = record_order_payments(db, order_id, order['shift_id'], order['payment_method'], new_total,
                                                   order['payment_cash'], session['user_id'],
                                                   paid=(order['payment_status'] == 'paid'))

        db.execute("UPDATE orders SET total=?, cost=?, payment_cash=?, payment_card=?, stock_deducted=? WHERE id=?",
                   (new_total, new_cost, pay_cash, pay_card, 1 if deducted else 0, order_id))
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
    menu_items = db.execute("""SELECT m.id, m.name, m.category, m.price,
        (SELECT COUNT(*) FROM recipes r WHERE r.menu_id=m.id) recipe_count,
        (SELECT COALESCE(SUM(r.amount * ing.cost_price),0) FROM recipes r JOIN ingredients ing ON ing.id=r.ingredient_id WHERE r.menu_id=m.id) cost
        FROM menu m ORDER BY m.category, m.name""").fetchall()
    missing_recipes = [m for m in menu_items if (m['recipe_count'] or 0) == 0]
    return render_template('warehouse.html', ingredients=ings, preps=preps, raw_ings=raw_ings, logs=logs,
                           total_stock_value=round(total_stock_value, 1), menu_items=menu_items, missing_recipes=missing_recipes)

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
    missing_recipes_count = db.execute("SELECT COUNT(*) FROM menu m WHERE NOT EXISTS (SELECT 1 FROM recipes r WHERE r.menu_id=m.id)").fetchone()[0]
    return render_template('admin.html', stats=stats, avg_check=avg_check, chart_data=chart_data, top_items=top_items, top_clients=top_clients, missing_recipes_count=missing_recipes_count, menu=db.execute("SELECT * FROM menu ORDER BY sort_weight DESC, category, name").fetchall(), users=db.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall(), zones=db.execute("SELECT * FROM zones").fetchall(), promos=db.execute("SELECT * FROM promocodes ORDER BY id DESC").fetchall(), avg_rating=avg_rating, reviews_count=reviews_count, recent_reviews=db.execute("SELECT * FROM orders WHERE rating > 0 ORDER BY id DESC LIMIT 5").fetchall(), shop_status=get_setting('shop_status'), banners=db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall())

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
    return render_template('public_site.html', menu=db.execute("SELECT * FROM menu WHERE available=1 AND stop_list=0 ORDER BY sort_weight DESC, category, name").fetchall(), categories=db.execute("SELECT DISTINCT category FROM menu WHERE available=1 AND stop_list=0 ORDER BY category").fetchall(), zones=db.execute("SELECT id, name, price FROM zones ORDER BY id").fetchall(), shop_open=is_shop_open(), banners=db.execute("SELECT * FROM banners ORDER BY id DESC").fetchall())

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

    shift = get_open_shift()
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
    pay_method = 'наличные' if data.get('payment_method') == 'наличные' else 'карта'
    change_from = max(0, int(data.get('change_from', 0) or 0))
    comment = clean_str(data.get('comment', ''), 250)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pub_token = secrets.token_urlsafe(12)

    try:
        cur = db.execute("""
            INSERT INTO orders (
                created_at, status, total, cost, address, phone, comment, shift_id,
                payment_method, payment_cash, payment_card, change_from, delivery_type, delivery_zone, delivery_price,
                promo_code, source, public_token, stock_deducted, bonus_awarded, idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)
        """, (now_str, 'new', total, 0, address, phone, comment, shift['id'], pay_method, 0, 0, change_from, delivery_type, zone_name, delivery_price, promo_code, 'Сайт', pub_token, idem_key))
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
        log_status_change(db, order_id, None, 'new', 0, 'Создан на сайте')
        enqueue_print_job(db, order_id, 'receipt')
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": "Ошибка сохранения заказа"}), 500

    send_tg_async(f"🌐 <b>НОВЫЙ ЗАКАЗ С САЙТА #{order_id}</b>\n💰 Сумма: <b>{total} ₽</b> ({pay_method}, доставка {delivery_price} ₽)\n📞 Тел: {phone}\n📍 Адрес: {address}")
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
    if delivery_type == 'доставка' and delivery_price == 0 and zone_str:
        zone_row = db.execute("SELECT price FROM zones WHERE name=?", (zone_str,)).fetchone()
        if zone_row: delivery_price = int(zone_row['price'])
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

        err, total_cost, deducted = adjust_stock_for_order(order_id, items, direction=-1, actor=session['username'], reason_prefix='Касса')
        if err:
            db.rollback()
            return jsonify({"error": err}), 400

        if actual_bonus > 0 and phone:
            db.execute("UPDATE clients SET bonuses = MAX(0, bonuses - ?) WHERE phone=?", (actual_bonus, phone))

        for i in items:
            db.execute("INSERT INTO order_items (order_id, menu_id, name, price, qty, modifiers) VALUES (?,?,?,?,?,?)",
                       (order_id, i['id'], i['name'], i['price'], i['qty'], i['mods']))

        pay_cash, pay_card = record_order_payments(db, order_id, shift['id'], payment_method, total, data.get('pay_cash', 0), session['user_id'])
        db.execute("UPDATE orders SET cost=?, payment_cash=?, payment_card=?, stock_deducted=? WHERE id=?", (total_cost, pay_cash, pay_card, 1 if deducted else 0, order_id))
        log_status_change(db, order_id, None, 'new', session['user_id'], 'Создан на кассе')
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
    row = db.execute("SELECT COUNT(*) cnt, COALESCE(SUM(payment_cash),0) cash_on_hand FROM orders WHERE date(created_at)=? AND courier_name=? AND status='done' AND payment_status='paid'", (today, name)).fetchone()
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
                db.execute("UPDATE orders SET status='done' WHERE id=?", (order_id,))

        elif new_status == 'cooking':
            db.execute("UPDATE orders SET status='cooking', cook_start_time=? WHERE id=?", (now_str, order_id))
        elif new_status == 'ready':
            db.execute("UPDATE orders SET status='ready', cook_end_time=? WHERE id=?", (now_str, order_id))
        elif new_status == 'delivering':
            c_name = clean_str(data.get('courier_name') or session.get('username', ''), 50)
            db.execute("UPDATE orders SET status='delivering', courier_name=? WHERE id=?", (c_name, order_id))

        log_status_change(db, order_id, cur_status, new_status, session.get('user_id', 0), data.get('reason', ''))
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=get_csrf_token)


@app.route('/api/customer_lookup')
@login_required('admin', 'cashier')
def api_customer_lookup():
    digits = re.sub(r'\D', '', request.args.get('phone', ''))
    if len(digits) < 10:
        return jsonify({'found': False})
    phone = digits[-10:]
    db = get_db()
    rows = db.execute(
        "SELECT address, comment, total, created_at FROM orders "
        "WHERE substr(replace(replace(replace(replace(replace(phone,' ',''),'-',''),'(',''),')',''),'+',''), -10) = ? "
        "ORDER BY id DESC LIMIT 20",
        (phone,)
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


@app.route('/track/<int:order_id>')
def track_order_page(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return "Заказ не найден", 404
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    return render_template('track.html', order=order, items=items)

@app.route('/api/order_status/<int:order_id>')
def api_order_status_check(order_id):
    db = get_db()
    order = db.execute("SELECT id, status, delivery_type, address, total, payment_method, comment, created_at FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return jsonify({'found': False}), 404
    items = db.execute("SELECT name, qty, price FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    st_map = {
        'new': {'step': 1, 'title': 'Заказ принят', 'desc': 'Передан на кухню, повара начинают готовить'},
        'cooking': {'step': 2, 'title': 'Готовится на кухне', 'desc': 'Крутим роллы и запекаем горячие позиции'},
        'ready': {'step': 3, 'title': 'Готов и упакован', 'desc': 'Заказ собран, проверен и ожидает курьера / выдачи'},
        'delivering': {'step': 3, 'title': 'Курьер в пути', 'desc': 'Заказ передан курьеру и едет по вашему адресу'},
        'done': {'step': 4, 'title': 'Заказ выполнен', 'desc': 'Приятного аппетита! Спасибо, что выбрали КРЕВЕТКА Pro'},
        'cancelled': {'step': 0, 'title': 'Заказ отменён', 'desc': 'Свяжитесь с администратором при возникновении вопросов'}
    }
    st_info = st_map.get(order['status'], st_map['new'])
    return jsonify({
        'found': True,
        'id': order['id'],
        'status': order['status'],
        'step': st_info['step'],
        'status_title': st_info['title'],
        'status_desc': st_info['desc'],
        'delivery_type': order['delivery_type'],
        'address': order['address'],
        'total': order['total'],
        'payment_method': order['payment_method'],
        'comment': order['comment'],
        'created_at': order['created_at'],
        'items': [dict(i) for i in items]
    })

@app.route('/site')
def public_site_alias():
    db = get_db()
    menu = db.execute("SELECT * FROM menu WHERE is_available=1 OR is_available IS NULL").fetchall()
    categories = db.execute("SELECT DISTINCT category FROM menu WHERE category IS NOT NULL AND category != ''").fetchall()
    return render_template('public_site.html', menu=menu, categories=categories)

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
```

### ФАЙЛ: kitchen_printer.py
```python
import time, sqlite3, os, sys
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sushi.db')
last_order_id = 0

def print_ticket(order):
    # ЗДЕСЬ МОЖНО ПОДКЛЮЧИТЬ РЕАЛЬНЫЙ ПРИНТЕР (python-escpos)
    # Сейчас мы просто выводим в консоль
    print("\n" + "="*30)
    print(f"   НОВЫЙ ЗАКАЗ #{order['id']}")
    print("="*30)
    print(f"Время: {order['created_at']}")
    print("-"*30)
    for item in order['items']:
        print(f"{item['name']} x{item['qty']}")
    print("-"*30 + "\n")

print("🖨️ Агент печати запущен. Ожидание заказов...")
while True:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        orders = conn.execute("SELECT * FROM orders WHERE status='new' AND id > ?", (last_order_id,)).fetchall()
        for o in orders:
            items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (o['id'],)).fetchall()
            print_ticket({"id": o['id'], "created_at": o['created_at'], "items": [dict(i) for i in items]})
            last_order_id = max(last_order_id, o['id'])
        conn.close()
    except Exception as e:
        print("Ошибка:", e)
    time.sleep(5)
```

### ФАЙЛ: printer_agent.py
```python
#!/usr/bin/env python3
import sqlite3, time, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sushi.db')
print("🖨️ PRODUCTION-АГЕНТ ОЧЕРЕДИ ПЕЧАТИ (print_jobs) ЗАПУЩЕН...")

while True:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        jobs = conn.execute("SELECT * FROM print_jobs WHERE status='pending' AND attempts < 3 ORDER BY id LIMIT 10").fetchall()
        for j in jobs:
            o = conn.execute("SELECT * FROM orders WHERE id=?", (j['order_id'],)).fetchone()
            if not o:
                conn.execute("UPDATE print_jobs SET status='failed', last_error='Order not found' WHERE id=?", (j['id'],))
                conn.commit()
                continue
            items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (o['id'],)).fetchall()
            print("\n" + "="*42)
            print(f"   ЧЕК ЗАКАЗА #{o['id']} ({o['delivery_type'].upper()})")
            print("="*42)
            for i in items:
                print(f" {i['name']} x{i['qty']} = {i['price']*i['qty']} ₽")
                if i['modifiers']: print(f"   ↳ {i['modifiers']}")
            print("-"*42)
            print(f" ИТОГО: {o['total']} ₽ ({o['payment_method']})")
            print("="*42 + "\n")
            conn.execute("UPDATE print_jobs SET status='printed', attempts=attempts+1, printed_at=? WHERE id=?",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), j['id']))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Ошибка очереди печати: {e}")
    time.sleep(2)
```

### ФАЙЛ: run.py
```python
#!/usr/bin/env python3
"""Production entry point: init/migrate DB, then serve with waitress."""
import os

os.environ.setdefault('SUSHI_SKIP_INIT', '1')
from app import app, init_db  # noqa: E402

if __name__ == '__main__':
    init_db()
    from waitress import serve

    port = int(os.environ.get('SUSHI_PORT', '5000'))
    serve(app, host='0.0.0.0', port=port, threads=8)
```

### ФАЙЛ: telegram_setup.py
```python
import urllib.request
import json

print("="*55)
print("🤖 НАСТРОЙКА TELEGRAM-БОТА")
print("="*55)
print("1. Откройте Telegram, найдите бота @BotFather")
print("2. Напишите ему /newbot и придумайте имя (например, SushiKrevetkaBot)")
print("3. Он выдаст вам ТОКЕН (длинная строка с двоеточием).")
token = input("\n👉 Вставьте ТОКЕН сюда и нажмите Enter: ").strip()

print("\nТеперь найдите своего нового бота в Telegram и напишите ему ЛЮБОЕ сообщение (например, 'Привет').")
input("Когда напишете, нажмите Enter здесь...")

url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    req = urllib.request.urlopen(url)
    data = json.loads(req.read().decode())
    if data['result']:
        chat_id = data['result'][-1]['message']['chat']['id']
        print("\n" + "="*55)
        print(f"✅ УСПЕХ! Ваш Chat ID: {chat_id}")
        print(f"✅ Ваш Token: {token}")
        print("="*55)
        print("Скопируйте эти два значения, они понадобятся в следующем шаге.")
    else:
        print("\n❌ Бот не видит сообщений. Убедитесь, что вы написали ему в Telegram и запустите скрипт заново.")
except Exception as e:
    print("\n❌ Ошибка. Проверьте, правильно ли скопирован ТОКЕН.", e)
```

### ФАЙЛ: templates/admin.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>Админ-панель — Креветка</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0a0a0a">
<style>
:root {
    --bg-main: #0a0a0a; --bg-panel: #151515; --bg-card: #151515; --bg-input: #0a0a0a;
    --text-main: #ffffff; --text-muted: #888888; --border: #333333;
    --accent: #ff7a00; --accent-text: #000000; --btn-grey: #333333;
}
body.light-theme {
    --bg-main: #e9ecef; --bg-panel: #ffffff; --bg-card: #ffffff; --bg-input: #f8f9fa;
    --text-main: #212529; --text-muted: #6c757d; --border: #ced4da;
    --accent: #ff7a00; --accent-text: #ffffff; --btn-grey: #dee2e6;
}
body{font-family:-apple-system,sans-serif;background:var(--bg-main);color:var(--text-main);margin:0;padding:30px; transition: background 0.3s, color 0.3s;}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:30px}h1{margin:0;color:var(--accent)}a{color:var(--accent);text-decoration:none}
.stats{display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:20px;margin-bottom:30px}
.stat-card{background:var(--bg-panel);padding:20px;border-radius:15px;border:1px solid var(--border); box-shadow: 0 2px 5px rgba(0,0,0,0.05);}
.stat-card h3{margin:0 0 10px;color:var(--text-muted);font-size:13px;text-transform:uppercase;letter-spacing:1px}.stat-card p{margin:0;font-size:28px;font-weight:bold;color:var(--accent)}
.chart-container{background:var(--bg-panel);padding:20px;border-radius:15px;border:1px solid var(--border);margin-bottom:30px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);}
.chart{display:flex;align-items:flex-end;height:120px;gap:15px;margin-top:20px;padding-bottom:20px;border-bottom:1px solid var(--border)}
.bar-wrap{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.bar{width:100%;background:var(--accent);border-radius:5px 5px 0 0;transition:0.3s;min-height:5px}.bar:hover{opacity:0.8}
.bar-label{font-size:12px;color:var(--text-muted);margin-top:8px}.bar-value{font-size:12px;color:var(--text-main);font-weight:bold;margin-bottom:5px}
table{width:100%;border-collapse:collapse;margin-top:15px;margin-bottom:20px}
th,td{padding:12px;text-align:left;border-bottom:1px solid var(--border)}th{color:var(--text-muted);font-size:12px;text-transform:uppercase}tr:hover{background:var(--bg-card)}
img.thumb{width:60px;height:60px;object-fit:cover;border-radius:8px}
img.banner-thumb{width:200px;height:80px;object-fit:cover;border-radius:8px}
.btn{background:var(--accent);color:var(--accent-text);border:none;padding:8px 15px;border-radius:8px;cursor:pointer;font-weight:bold;font-size:13px;text-decoration:none;display:inline-block;transition:0.2s}
.btn:hover{opacity:0.9}
.btn-danger{background:#ff453a;color:#fff}.btn-warning{background:#ffd60a;color:#000}.btn-edit{background:#30d158;color:#000;}
input,select,textarea{background:var(--bg-input);color:var(--text-main);border:1px solid var(--border);padding:10px;border-radius:8px;margin-right:10px;font-size:14px;font-family:inherit;}
.badge{background:var(--btn-grey);padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold}
.badge-admin{background:var(--accent);color:var(--accent-text)}.badge-cashier{background:#30d158;color:#000}.badge-kitchen{background:#ff9f0a;color:#000}.badge-courier{background:#af52de;color:#fff}
.two-cols{display:grid;grid-template-columns:1fr 1fr;gap:30px}
.export-box{background:var(--bg-panel); padding:20px; border-radius:15px; border:1px solid var(--border); margin-bottom:30px; display:flex; gap:20px; align-items:center; box-shadow: 0 2px 5px rgba(0,0,0,0.05); flex-wrap:wrap;}
.stars{color:#ffd700; font-size:18px; letter-spacing:2px;}
.status-box{background:var(--bg-panel); padding:20px; border-radius:15px; border:1px solid var(--accent); margin-bottom:30px; display:flex; align-items:center; gap:20px; box-shadow: 0 2px 5px rgba(255,122,0,0.1);}
.theme-btn{background:var(--bg-card);color:var(--text-main);border:1px solid var(--border);padding:6px 10px;border-radius:8px;cursor:pointer;font-size:16px;margin-left:15px;}
</style>
<script>
    if(localStorage.getItem('theme') === 'light') { document.documentElement.classList.add('light-theme'); }
</script>
<link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>

<div class="topbar">
    <h1>⚙️ Дашборд</h1>
    <div>
        <a href="/" style="font-weight:bold">← В кассу</a> | 
        <a href="/crm" style="color:#ffd60a;font-weight:bold">👥 CRM</a> | 
        <a href="/map" style="color:#0a84ff;font-weight:bold">🗺️ Карта и Зоны</a> |
        <a href="/autopilot" style="background:#10b981;color:#000;padding:8px 14px;border-radius:8px;font-weight:bold;text-decoration:none;margin-right:8px">🧠 AI Шеф-Автопилот</a> <a href="/board" target="_blank" style="background:#3b82f6;color:#fff;padding:8px 14px;border-radius:8px;font-weight:bold;text-decoration:none;margin-right:8px">📺 ТВ-Табло</a> <a href="/warehouse" style="color:#ff9f0a;font-weight:bold">📦 Склад</a> |
        <a href="/analytics" style="color:#30d158;font-weight:bold">💰 Финансы</a> | 
        <a href="/reports">📊 Отчёты</a> | 
        <a href="/site" target="_blank">🌐 Сайт</a> | 
        <a href="/chat" style="color:#0a84ff;font-weight:bold;margin-right:15px;text-decoration:none;">💬 Чат</a> <a href="/logout" style="color:#ff453a">Выход</a>
        <button class="theme-btn" onclick="toggleTheme()" id="theme-btn">🌙</button>
    </div>
</div>

<div class="status-box">
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
{% endif %}


<div class="stat-card" style="margin-bottom:30px;">
    <h2 style="margin-top:0; color:var(--accent);">🏢 Настройки компании, карты и Telegram (Коробочная версия)</h2>
    <form method="post" action="/admin/brand_settings" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; align-items:end;">
        <div><label style="font-size:12px;color:var(--text-muted)">Название бренда</label><input name="brand_name" value="{{ brand.brand_name }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Город</label><input name="brand_city" value="{{ brand.brand_city }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Адрес точки (для чека)</label><input name="brand_address" value="{{ brand.brand_address }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Телефон доставки</label><input name="brand_phone" value="{{ brand.brand_phone }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Слоган на сайте</label><input name="brand_slogan" value="{{ brand.brand_slogan }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Открытие (ЧЧ:ММ)</label><input name="work_start" value="{{ brand.work_start }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Закрытие (ЧЧ:ММ)</label><input name="work_end" value="{{ brand.work_end }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Широта карты (Lat)</label><input name="map_lat" value="{{ brand.map_lat }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Долгота карты (Lng)</label><input name="map_lng" value="{{ brand.map_lng }}" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Telegram Bot Token</label><input name="tg_token" value="{{ brand.tg_token }}" placeholder="Токен от @BotFather" style="width:100%;box-sizing:border-box"></div>
        <div><label style="font-size:12px;color:var(--text-muted)">Telegram Chat ID</label><input name="tg_chat_id" value="{{ brand.tg_chat_id }}" placeholder="ID чата" style="width:100%;box-sizing:border-box"></div>
        <div><button type="submit" class="btn btn-edit" style="width:100%;padding:11px;">💾 Сохранить настройки</button></div>
    </form>
</div>

<div class="stats">
    <div class="stat-card"><h3>Выручка за сегодня</h3><p>{{ stats.rev }} ₽</p></div>
    <div class="stat-card"><h3>Заказов за сегодня</h3><p>{{ stats.cnt }}</p></div>
    <div class="stat-card"><h3>Средний чек</h3><p>{{ avg_check|round }} ₽</p></div>
    <div class="stat-card"><h3>Средняя оценка</h3><p style="color:#ffd700">{{ avg_rating }} <span style="font-size:16px;color:var(--text-muted);">({{ reviews_count }} отз.)</span></p></div>
</div>

<div class="two-cols">
    <div class="chart-container">
        <h3 style="margin-top:0">📈 Выручка за 7 дней</h3>
        <div class="chart">
            {% for d in chart_data %}
            <div class="bar-wrap">
                <div class="bar-value">{{ d.rev }}</div>
                <div class="bar" style="height: {{ (d.rev / 10000 * 100) if d.rev > 0 else 2 }}%"></div>
                <div class="bar-label">{{ d.date }}</div>
            </div>
            {% endfor %}
        </div>
    </div>
    
    <div>
        <h2>👑 Топ-5 клиентов</h2>
        <table>
            <tr><th>Телефон</th><th>Сумма</th></tr>
            {% for c in top_clients %}<tr><td>{{ c.phone }}</td><td style="color:var(--accent);font-weight:bold">{{ c.sum }} ₽</td></tr>{% endfor %}
        </table>
    </div>
</div>

<div class="export-box">
    <h2 style="margin:0; color:#30d158; flex:1;">📊 Экспорт и Бэкап</h2>
    <button onclick="downloadFile('/admin/export/orders', 'orders.xlsx')" class="btn" style="background:#30d158;">📥 Заказы (Excel)</button>
    <button onclick="downloadFile('/admin/export/clients', 'clients.xlsx')" class="btn" style="background:#30d158;">📥 Клиенты (Excel)</button>
    <a href="/admin/backup_db" class="btn" style="background:#0a84ff;">💾 Скачать базу (.db)</a>
</div>

<div class="two-cols">
    <div>
        <h2>⭐ Последние отзывы</h2>
        <table>
            {% for r in recent_reviews %}
            <tr>
                <td style="vertical-align:top;">Заказ #{{ r.id }}</td>
                <td>
                    <span class="stars">{% for i in range(r.rating) %}★{% endfor %}</span>
                    <div style="color:var(--text-muted); font-size:13px; margin-top:5px; font-style:italic;">{{ r.review_text or 'Без комментария' }}</div>
                </td>
            </tr>
            {% else %}<tr><td colspan="2" style="color:var(--text-muted)">Пока нет отзывов</td></tr>{% endfor %}
        </table>
    </div>
    
    <div>
        <h2>🖼️ Баннеры на сайт (Акции)</h2>
        <form method="post" action="/admin/banner/add" enctype="multipart/form-data" style="margin-bottom:15px; display:flex; gap:10px; align-items:center; background:var(--bg-panel); padding:10px; border-radius:10px;">
            <input type="file" name="image" accept="image/*" required style="flex:1;">
            <button type="submit" class="btn" style="background:#ff9f0a; color:#000;">➕ Загрузить</button>
        </form>
        <div style="display:flex; flex-wrap:wrap; gap:10px;">
            {% for b in banners %}
            <div style="position:relative; display:inline-block;">
                <img src="/static/uploads/{{ b.image }}" style="height:80px; border-radius:8px; border:1px solid var(--border);">
                <form method="post" action="/admin/banner/delete/{{ b.id }}" style="position:absolute; top:-5px; right:-5px;">
                    <button type="submit" style="background:#ff453a; color:#fff; border:none; border-radius:50%; width:20px; height:20px; cursor:pointer; font-size:12px; display:flex; align-items:center; justify-content:center;">×</button>
                </form>
            </div>
            {% endfor %}
        </div>
    </div>
</div>

<h2 style="margin-top:40px">🎟️ Промокоды</h2>
<form method="post" action="/admin/promo/add" style="margin-bottom:20px; display:flex; flex-wrap:wrap; gap:10px; background:var(--bg-panel); padding:15px; border-radius:15px; border:1px solid var(--border); align-items:center;">
    <input name="code" placeholder="КОД (напр. SUSHI10)" required style="text-transform:uppercase;">
    <select name="type"><option value="percent">Процент (%)</option><option value="rub">Рубли (₽)</option></select>
    <input name="value" type="number" placeholder="Размер скидки" required style="width:150px">
    <button type="submit" class="btn">➕ Добавить</button>
</form>
<table style="margin-bottom:40px;">
    <tr><th>Код</th><th>Скидка</th><th>Действие</th></tr>
    {% for p in promos %}
    <tr>
        <td style="font-weight:bold; color:var(--accent);">{{ p.code }}</td>
        <td>{% if p.discount_type == 'percent' %}{{ p.discount_value }}%{% else %}{{ p.discount_value }} ₽{% endif %}</td>
        <td><form method="post" action="/admin/promo/delete/{{ p.id }}" style="display:inline" onsubmit="return confirm('Удалить промокод?');"><button type="submit" class="btn btn-danger">🗑️</button></form></td>
    </tr>
    {% endfor %}
</table>

<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px">
    <h2 style="margin:0">🍣 Меню и Фотографии</h2>
    <form method="post" action="/admin/menu/clear" onsubmit="return confirm('Удалить ВСЁ меню?');"><button type="submit" class="btn btn-danger" style="padding:10px 20px;">🗑️ Очистить всё</button></form>
</div>

<form method="post" action="/admin/menu/add" enctype="multipart/form-data" style="margin-bottom:20px; display:flex; flex-wrap:wrap; gap:10px; background:var(--bg-panel); padding:15px; border-radius:15px; border:1px solid var(--border); align-items:center;">
    <input name="name" placeholder="Название" required>
    <input name="price" type="number" placeholder="Цена" required style="width:100px">
    <input name="category" placeholder="Категория" required style="width:120px">
    <input name="sort_weight" type="number" placeholder="Вес (сортировка)" style="width:140px" title="Чем больше число, тем выше блюдо в списке">
    <input name="composition" placeholder="Состав" style="flex:1; min-width:200px;">
    <input type="file" name="image" accept="image/*" style="padding:8px">
    <button type="submit" class="btn" style="padding:10px 20px;">➕ Добавить</button>
</form>

<table>
    <tr><th>Фото</th><th>Название / Состав</th><th>Цена</th><th>Действия</th></tr>
    {% for m in menu %}
    <tr>
        <td>{% if m.image %}<img src="/static/uploads/{{ m.image }}" class="thumb">{% else %}<div style="width:60px;height:60px;background:var(--btn-grey);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:10px;color:var(--text-muted)">Нет</div>{% endif %}</td>
        <td>
            <div style="font-weight:bold; margin-bottom:4px;">{{ m.name }} <span style="color:var(--accent)">{{ m.price }} ₽</span></div>
            <div style="color:var(--text-muted); font-size:12px; max-width:300px;">{{ m.composition or 'Состав не указан' }}</div>
            <div style="color:var(--text-muted); font-size:11px; margin-top:2px;">Вес: {{ m.sort_weight }}</div>
        </td>
        <td><span class="badge">{{ m.category }}</span></td>
        <td>
            <a href="/admin/menu/edit/{{ m.id }}" class="btn btn-edit">✏️ Изм.</a>
            <form method="post" action="/admin/menu/stop/{{ m.id }}" style="display:inline"><button type="submit" class="btn {% if m.stop_list %}btn-warning{% else %}btn-danger{% endif %}">{% if m.stop_list %}Снять стоп{% else %}В стоп{% endif %}</button></form>
            <form method="post" action="/admin/menu/delete/{{ m.id }}" style="display:inline" onsubmit="return confirm('Удалить?');"><button type="submit" class="btn btn-danger">🗑️</button></form>
        </td>
    </tr>
    {% endfor %}
</table>

<h2 style="margin-top:40px">👥 Сотрудники</h2>
<form method="post" action="/admin/users/add" style="margin-bottom:20px; display:flex; flex-wrap:wrap; gap:10px; background:var(--bg-panel); padding:15px; border-radius:15px; border:1px solid var(--border); align-items:center;">
    <input name="username" placeholder="Логин" required>
    <input name="password" type="text" placeholder="Пароль" required>
    <select name="role"><option value="cashier">Кассир</option><option value="kitchen">Повар</option><option value="courier">Курьер</option><option value="admin">Админ</option></select>
    <button type="submit" class="btn" style="background:#30d158;">➕ Добавить</button>
</form>
<table>
    <tr><th>ID</th><th>Логин</th><th>Роль</th><th>Дата создания</th><th>Действие</th></tr>
    {% for u in users %}
    <tr>
        <td>{{ u.id }}</td><td style="font-weight:bold">{{ u.username }}</td>
        <td><span class="badge badge-{{ u.role }}">{{ u.role }}</span></td>
        <td style="color:var(--text-muted)">{{ u.created_at }}</td>
        <td>
            {% if u.id != session.get('user_id') %}
            <form method="post" action="/admin/users/delete/{{ u.id }}" style="display:inline" onsubmit="return confirm('Уволить сотрудника?');"><button type="submit" class="btn btn-danger">🚪 Уволить</button></form>
            {% else %}<span style="color:var(--text-muted); font-size:12px;">(Это вы)</span>{% endif %}
        </td>
    </tr>
    {% endfor %}
</table>

<script>
function toggleTheme() {
    document.body.classList.toggle('light-theme');
    const isLight = document.body.classList.contains('light-theme');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    document.getElementById('theme-btn').innerText = isLight ? '🌙' : '☀️';
}
document.addEventListener('DOMContentLoaded', () => {
    if(localStorage.getItem('theme') === 'light') { document.body.classList.add('light-theme'); document.getElementById('theme-btn').innerText = '🌙'; } 
    else { document.getElementById('theme-btn').innerText = '☀️'; }
});
function downloadFile(url, filename) {
    fetch(url).then(response => response.blob()).then(blob => {
        const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename; document.body.appendChild(link); link.click(); document.body.removeChild(link);
    }).catch(error => alert('Ошибка при скачивании файла'));
}
</script>
</body></html>
```

### ФАЙЛ: templates/analytics.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>Продвинутая аналитика — Креветка PRO</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
body{margin:0;padding:30px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:30px}
h1{margin:0;color:#10b981}a{color:var(--accent);text-decoration:none}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;margin-bottom:30px}
.stat-card{padding:20px}
.stat-card h3{margin:0 0 10px;color:var(--text-muted);font-size:12px;text-transform:uppercase}
.stat-card p{margin:0;font-size:28px;font-weight:bold}
.two-cols{display:grid;grid-template-columns:1fr 1fr;gap:25px}
@media(max-width:900px){.two-cols{grid-template-columns:1fr}}
</style>
<script>if(localStorage.getItem('theme') === 'light') document.documentElement.classList.add('light-theme');</script>
<link rel="stylesheet" href="/static/ui.css">
</head><body>

<div class="topbar">
    <h1>📈 Финансы, Пиковые часы и ABC-анализ</h1>
    <div><a href="/admin">← Назад в дашборд</a></div>
</div>

<div class="stats">
    <div class="stat-card"><h3>Общая выручка</h3><p style="color:#10b981">{{ total_rev }} ₽</p></div>
    <div class="stat-card"><h3>Себестоимость продуктов</h3><p style="color:#ef4444">{{ total_cost|round(1) }} ₽</p></div>
    <div class="stat-card"><h3>Чистая прибыль</h3><p style="color:#f59e0b">{{ total_profit|round(1) }} ₽</p></div>
    <div class="stat-card"><h3>Маржинальность</h3><p style="color:#3b82f6">{{ margin }} %</p></div>
</div>

<div class="two-cols">
    <div>
        <h2>🔥 Последние 10 заказов</h2>
        <table>
            <tr><th>#</th><th>Дата</th><th>Выручка</th><th>Себестоимость</th><th>Прибыль</th></tr>
            {% for o in recent_orders %}
            <tr>
                <td><b>#{{ o.id }}</b></td>
                <td style="color:var(--text-muted)">{{ o.created_at }}</td>
                <td style="color:#10b981;font-weight:bold">{{ o.total }} ₽</td>
                <td style="color:#ef4444">{{ o.cost|round(1) }} ₽</td>
                <td style="color:#f59e0b;font-weight:bold">{{ (o.total - o.cost)|round(1) }} ₽</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    <div>
        <h2>⏰ Рекомендации по загрузке</h2>
        <div class="stat-card" style="line-height:1.6">
            <p>💡 <b>Пиковые часы:</b> традиционный всплеск заказов в службе доставки наблюдается с 17:00 до 21:00 в будни и с 14:00 до 22:00 в выходные дни.</p>
            <p style="margin-top:15px">💡 <b>Food Cost (Себестоимость):</b> целевой показатель для суши и WOK и супов составляет 25–30%. Ваша текущая рентабельность <b>{{ margin }}%</b> находится в зеленой зоне.</p>
        </div>
    </div>
</div>
</body></html>
```

### ФАЙЛ: templates/autopilot.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><title>Чек-лист Повара & Автопилот ULTRA X2</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
.prep-row.done-prep { opacity: 0.45; text-decoration: line-through; background: rgba(16,185,129,0.08); }
.kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 20px; }
.kpi-box { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
</style>
<link rel="stylesheet" href="/static/ui.css">
</head>
<body>

<div class="ultra-topbar">
    <a href="/" class="ultra-brand"><span>🔪 ЧЕК-ЛИСТ ПОВАРА & AI АВТОПИЛОТ</span><span class="ultra-tag">ULTRA X2</span></a>
    <div class="ultra-nav">
        <a href="/" class="btn btn-ghost">🖥️ Касса</a>
        <a href="/kitchen" class="btn btn-yellow">🍳 Кухня KDS</a>
        <a href="/warehouse" class="btn btn-purple">📦 Склад</a>
        <a href="/admin" class="btn btn-ghost">⚙️ Админка</a>
        <button onclick="window.print()" class="btn btn-blue">🖨️ Печать чек-листа</button>
        <button onclick="document.body.classList.toggle('light-theme');localStorage.setItem('theme', document.body.classList.contains('light-theme')?'light':'dark')" class="btn btn-ghost">🌓 Тема</button>
    </div>
</div>

<div class="container-x2">
    <div class="kpi-strip">
        <div class="kpi-box">
            <div style="font-size:12px;color:var(--text-muted);font-weight:700">ДЕНЬ НЕДЕЛИ И НАГРУЗКА</div>
            <div style="font-size:22px;font-weight:900;color:var(--accent);margin-top:4px">{{ today_name }} (x{{ day_mult }})</div>
        </div>
        <div class="kpi-box">
            <div style="font-size:12px;color:var(--text-muted);font-weight:700">СТАНДАРТ НАРЕЗКИ РОЛЛОВ</div>
            <div style="font-size:22px;font-weight:900;color:var(--green);margin-top:4px">8 кусочков / порция</div>
        </div>
        <div class="kpi-box">
            <div style="font-size:12px;color:var(--text-muted);font-weight:700">ПОЗИЦИЙ В ТЕХКАРТАХ</div>
            <div style="font-size:22px;font-weight:900;margin-top:4px">{{ menu_matrix|length }} блюд</div>
        </div>
    </div>

    <div style="display:grid;grid-template-columns:1.45fr 1fr;gap:20px;margin-bottom:20px">
        <!-- УТРЕННИЙ ПЛАН ЗАГОТОВОК С ИНТЕРАКТИВНЫМИ ГАЛОЧКАМИ -->
        <div class="card-x2" style="margin:0">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                <h2 style="margin:0;color:var(--green);font-size:18px">🔪 Утренний чек-лист заготовок (П/Ф и Сырьё)</h2>
                <button class="btn btn-ghost no-print" style="padding:6px 12px;font-size:12px" onclick="resetPrepChecks()">Сбросить галочки</button>
            </div>
            <table>
                <tr>
                    <th style="width:40px">Готово</th>
                    <th>Заготовка / Ингредиент</th>
                    <th>Остаток</th>
                    <th>Норма смены</th>
                    <th>Задание повару</th>
                </tr>
                {% for p in prep_plan %}
                <tr class="prep-row" id="prep-row-{{ p.id }}" onclick="togglePrepCheck({{ p.id }})" style="cursor:pointer">
                    <td style="text-align:center"><input type="checkbox" id="chk-prep-{{ p.id }}" style="width:18px;height:18px;pointer-events:none"></td>
                    <td><b>{{ p.name }}</b> {% if p.is_prep %}<span style="background:var(--blue);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:800">П/Ф ЦЕХ</span>{% endif %}</td>
                    <td>{{ p.stock }} {{ p.unit }}</td>
                    <td><b>{{ p.recommended }} {{ p.unit }}</b></td>
                    <td>
                        {% if p.to_make > 0 %}
                            <span style="color:var(--accent);font-weight:900">⚡ {% if p.is_prep %}Наготовить{% else %}Достать/Заказать{% endif %}: +{{ p.to_make }} {{ p.unit }}</span>
                        {% else %}
                            <span style="color:var(--green);font-weight:800">✅ В норме</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>

        <!-- АВТО-ЗАЯВКА ПОСТАВЩИКАМ + КАЛЬКУЛЯТОР РАЗДЕЛКИ И РИСА -->
        <div style="display:flex;flex-direction:column;gap:20px">
            <div class="card-x2" style="margin:0">
                <h3 style="margin-top:0;color:var(--accent);font-size:16px">🐟 Быстрый калькулятор цеха (Рис и Разделка рыбы)</h3>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
                    <div>
                        <label style="font-size:11px;color:var(--text-muted);font-weight:700">Сухой рис (кг):</label>
                        <input type="number" id="raw-rice" value="5" step="0.5" oninput="calcPrepYield()" style="width:100%;margin-top:4px">
                        <div id="rice-out" style="font-size:12px;color:var(--green);font-weight:800;margin-top:6px">Готовый рис: 11.0 кг | Заправка: 1.25 л</div>
                    </div>
                    <div>
                        <label style="font-size:11px;color:var(--text-muted);font-weight:700">Тушка лосося (кг, отход 22%):</label>
                        <input type="number" id="raw-fish" value="6" step="0.5" oninput="calcPrepYield()" style="width:100%;margin-top:4px">
                        <div id="fish-out" style="font-size:12px;color:#60a5fa;font-weight:800;margin-top:6px">Чистое филе: 4.68 кг | Отход: 1.32 кг</div>
                    </div>
                </div>
            </div>

            <div class="card-x2" style="margin:0;flex:1;display:flex;flex-direction:column">
                <h3 style="margin-top:0;color:var(--blue);font-size:16px">📲 Авто-заявка поставщикам в Telegram / WhatsApp</h3>
                <textarea id="sup-msg" rows="7" style="width:100%;font-family:monospace;font-size:13px;flex:1;margin-bottom:10px">📦 Заявка на поставку ({{ today_name }}):
{{ purchase_text }}</textarea>
                <button class="btn no-print" onclick="navigator.clipboard.writeText(document.getElementById('sup-msg').value);alert('✅ Заявка скопирована!')">📋 Скопировать список закупа</button>
            </div>
        </div>
    </div>

    <!-- ABC / МАТРИЦА МЕНЮ И КОНТРОЛЬ 8 КУСОЧКОВ -->
    <div class="card-x2">
        <h2 style="margin-top:0;font-size:18px">📊 Инжиниринг меню, Food Cost (с учётом отхода) и стандарт 8 кусочков</h2>
        <table>
            <tr>
                <th>Позиция</th>
                <th>Категория</th>
                <th>Выход ТТК</th>
                <th>Вес 1 кус. (8 шт)</th>
                <th>Цена</th>
                <th>Себест. брутто</th>
                <th>Food Cost %</th>
                <th>Маржа</th>
                <th>AI Статус</th>
                <th>Рекомендация Шефу</th>
            </tr>
            {% for m in menu_matrix %}
            <tr>
                <td><b>{{ m.name }}</b></td>
                <td style="color:var(--text-muted)">{{ m.category }}</td>
                <td><b>{{ m.weight }} г</b></td>
                <td>{% if m.piece_weight > 0 %}<b style="color:var(--green)">{{ m.piece_weight }} г/шт</b>{% else %}—{% endif %}</td>
                <td><b>{{ m.price }} ₽</b></td>
                <td style="color:var(--red);font-weight:700">{{ m.cost }} ₽</td>
                <td style="font-weight:900;color:{% if m.fc_pct <= 33 %}var(--green){% elif m.fc_pct <= 40 %}var(--yellow){% else %}var(--red){% endif %}">{{ m.fc_pct }}%</td>
                <td style="color:var(--green);font-weight:800">+{{ m.margin }} ₽</td>
                <td><span style="padding:4px 8px;border-radius:6px;font-size:11px;font-weight:800;background:{{ m.q_color }};color:#fff">{{ m.quadrant }}</span></td>
                <td style="font-size:12px;color:var(--text-muted)">{{ m.advice }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
</div>

<script>
if(localStorage.getItem('theme') === 'light') document.body.classList.add('light-theme');

let prepChecks = JSON.parse(localStorage.getItem('prep_checks_today') || '{}');
function applyPrepChecks() {
    for(let id in prepChecks) {
        let row = document.getElementById('prep-row-' + id);
        let chk = document.getElementById('chk-prep-' + id);
        if(row && chk) {
            row.classList.toggle('done-prep', !!prepChecks[id]);
            chk.checked = !!prepChecks[id];
        }
    }
}
function togglePrepCheck(id) {
    prepChecks[id] = !prepChecks[id];
    localStorage.setItem('prep_checks_today', JSON.stringify(prepChecks));
    applyPrepChecks();
}
function resetPrepChecks() {
    prepChecks = {};
    localStorage.setItem('prep_checks_today', '{}');
    document.querySelectorAll('.prep-row').forEach(r => r.classList.remove('done-prep'));
    document.querySelectorAll('input[type=checkbox]').forEach(c => c.checked = false);
}
function calcPrepYield() {
    let r = parseFloat(document.getElementById('raw-rice').value) || 0;
    let f = parseFloat(document.getElementById('raw-fish').value) || 0;
    document.getElementById('rice-out').innerText = `Готовый рис: ${(r * 2.2).toFixed(1)} кг | Заправка: ${(r * 0.25).toFixed(2)} л`;
    document.getElementById('fish-out').innerText = `Чистое филе: ${(f * 0.78).toFixed(2)} кг | Отход: ${(f * 0.22).toFixed(2)} кг`;
}
applyPrepChecks();
</script>
</body></html>
```

### ФАЙЛ: templates/board.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>Табло готовности — {{ brand.brand_name }}</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
body{margin:0;padding:25px;height:100vh;box-sizing:border-box;display:flex;flex-direction:column;overflow:hidden}
.top{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid var(--border);padding-bottom:15px;margin-bottom:20px}
.logo{font-size:32px;font-weight:900;color:var(--accent)}
.load-pill{padding:10px 20px;border-radius:14px;font-size:20px;font-weight:bold;background:var(--bg-panel);border:1px solid var(--border)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:30px;flex:1;min-height:0}
.col{background:var(--bg-panel);border:1px solid var(--border);border-radius:22px;padding:25px;display:flex;flex-direction:column}
.col h2{margin:0 0 20px;font-size:30px;text-align:center;padding-bottom:12px;border-bottom:1px solid var(--border)}
.num-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:16px;align-content:start}
.num-box{padding:22px 10px;border-radius:16px;text-align:center;font-size:38px;font-weight:900}
.cooking-box{background:rgba(245,158,11,0.15);border:2px solid #f59e0b;color:#f59e0b}
.ready-box{background:rgba(16,185,129,0.2);border:2px solid #10b981;color:#10b981;animation:pulse 2s infinite}
@keyframes pulse{0%{transform:scale(1)}50%{transform:scale(1.04)}100%{transform:scale(1)}}
</style><link rel="stylesheet" href="/static/ui.css">
</head><body>
<div class="top">
    <div class="logo">🍤 {{ brand.brand_name }} — ТАБЛО ЗАКАЗОВ</div>
    <div id="load-badge" class="load-pill">🟢 Среднее время ожидания: ~35 мин</div>
</div>
<div class="cols">
    <div class="col">
        <h2 style="color:#f59e0b">🍳 ГОТОВЯТСЯ НА КУХНЕ</h2>
        <div id="cooking-list" class="num-grid"></div>
    </div>
    <div class="col">
        <h2 style="color:#10b981">✅ ГОТОВО К ВЫДАЧЕ / КУРЬЕРАМ</h2>
        <div id="ready-list" class="num-grid"></div>
    </div>
</div>
<script>
let prevReadyIds = [];
function updateBoard(){
    fetch('/api/kitchen_load').then(r=>r.json()).then(d=>{
        const b = document.getElementById('load-badge');
        b.innerText = `${d.level} • Ожидание ~${d.est_minutes} мин`;
        b.style.color = d.color;
        document.getElementById('cooking-list').innerHTML = d.cooking.map(o=>`<div class="num-box cooking-box">#${o.id}</div>`).join('');
        document.getElementById('ready-list').innerHTML = d.ready.map(o=>`<div class="num-box ready-box">#${o.id}</div>`).join('');
        const curIds = d.ready.map(o=>o.id);
        curIds.forEach(id => {
            if(!prevReadyIds.includes(id) && 'speechSynthesis' in window){
                const u = new SpeechSynthesisUtterance("Заказ номер " + id + " готов");
                u.lang = 'ru-RU'; window.speechSynthesis.speak(u);
            }
        });
        prevReadyIds = curIds;
    });
}
setInterval(updateBoard, 3000); updateBoard();
</script></body></html>
```

### ФАЙЛ: templates/cashier.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>КРЕВЕТКА Pro — Кассовый терминал</title>
<link rel="stylesheet" href="/static/pro_style.css">
<script src="/static/zones_inta.js"></script>
<style>
body { display: flex; height: 100vh; overflow: hidden; }
.left-pane { flex: 1; display: flex; flex-direction: column; border-right: 1px solid var(--border); overflow: hidden; }
.search-cats-bar { display: flex; gap: 10px; padding: 10px 18px; background: var(--bg-panel); border-bottom: 1px solid var(--border); align-items: center; }
.cats-scroll { display: flex; gap: 8px; overflow-x: auto; flex: 1; scrollbar-width: none; }
.cats-scroll::-webkit-scrollbar { display: none; }
.cat-pill { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-main); padding: 10px 18px; border-radius: 10px; cursor: pointer; white-space: nowrap; font-size: 14px; font-weight: 800; }
.cat-pill.active { background: var(--accent); color: #fff; border-color: var(--accent); }

.sushi-upsell-bar { display: flex; gap: 8px; padding: 8px 18px; background: rgba(255, 107, 0, 0.08); border-bottom: 1px solid var(--border); align-items: center; overflow-x: auto; }
.addon-btn { background: var(--bg-card); border: 1px solid var(--accent); color: var(--text-main); padding: 7px 12px; border-radius: 8px; font-size: 13px; font-weight: 800; cursor: pointer; white-space: nowrap; }
.addon-btn:hover { background: var(--accent); color: #fff; }

.menu-grid { flex: 1; overflow-y: auto; padding: 14px 18px; display: grid; grid-template-columns: repeat(auto-fill, minmax(185px, 1fr)); gap: 12px; align-content: start; }
.sushi-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; cursor: pointer; display: flex; flex-direction: column; min-height: 110px; transition: 0.08s; }
.sushi-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.station-tag { display: inline-block; font-size: 10px; font-weight: 900; padding: 2px 6px; border-radius: 4px; margin-bottom: 6px; width: fit-content; }
.tag-baked { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }
.tag-tempura { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; }
.tag-cold { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid #3b82f6; }

.right-pane { width: 580px; background: var(--bg-card); display: flex; flex-direction: column; border-left: 1px solid var(--border); }
.tabs-bar { display: flex; background: var(--bg-panel); border-bottom: 1px solid var(--border); }
.tab-trigger { flex: 1; padding: 14px; text-align: center; font-weight: 900; font-size: 15px; cursor: pointer; border: none; background: transparent; color: var(--text-muted); }
.tab-trigger.active { color: var(--accent); border-bottom: 4px solid var(--accent); background: var(--bg-card); }

.sushi-stats-bar { padding: 8px 14px; background: var(--bg-panel); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; gap: 6px; flex-wrap: wrap; }
.stat-pill { background: var(--bg-main); border: 1px solid var(--border); padding: 5px 10px; border-radius: 8px; font-size: 12px; font-weight: 800; display: flex; align-items: center; gap: 6px; }

.cart-list { flex: 1; overflow-y: auto; padding: 10px 14px; }
.cart-row { background: var(--bg-main); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; }
.mod-bar { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 6px; }
.mod-pill { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-muted); padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; }
.mod-pill.active { background: var(--blue); color: #fff; border-color: var(--blue); }
.qty-btn { padding: 5px 12px; font-size: 15px; font-weight: 900; border-radius: 8px; }

.checkout-panel { padding: 12px 16px; background: var(--bg-panel); border-top: 1px solid var(--border); overflow-y: auto; max-height: 58vh; }
.zone-pill { flex: 1; padding: 8px 4px; font-size: 11px; font-weight: 900; border: 1px solid var(--border); background: var(--bg-card); color: var(--text-main); border-radius: 8px; cursor: pointer; text-align: center; transition: 0.1s; }
.zone-pill.active { background: var(--purple); color: #fff; border-color: var(--purple); box-shadow: 0 0 10px rgba(139,92,246,0.4); }
.pay-pill { flex: 1; padding: 10px 6px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text-main); border-radius: 8px; font-weight: 900; font-size: 13px; cursor: pointer; text-align: center; }
.pay-pill.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.bill-quick { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-main); padding: 7px; border-radius: 6px; font-size: 12px; font-weight: 800; cursor: pointer; flex: 1; text-align: center; }

/* КАРТОЧКИ ЗАКАЗОВ С ПРОГРЕСС-БАРОМ СОСТОЯНИЯ */
.orders-feed { flex: 1; overflow-y: auto; padding: 14px; }
.order-card { background: var(--bg-main); border: 2px solid var(--border); border-radius: 12px; padding: 14px; margin-bottom: 12px; transition: 0.2s; }
.order-card.highlight-new { border-color: var(--green); box-shadow: 0 0 20px rgba(16,185,129,0.3); }
.state-stepper { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin: 8px 0 10px 0; }
.step-node { padding: 5px 4px; text-align: center; font-size: 11px; font-weight: 800; border-radius: 6px; background: var(--bg-card); color: var(--text-muted); border: 1px solid var(--border); }
.step-node.done { background: rgba(16, 185, 129, 0.2); color: #34d399; border-color: var(--green); }
.step-node.current { background: var(--accent); color: #fff; border-color: var(--accent); }
</style>
</head>
<body>

<div class="left-pane">
    <div class="pro-topbar">
        <div class="pro-brand">
            <span>🦐 КРЕВЕТКА</span>
            <span class="pro-badge">PRO POS</span>
        </div>
        <div class="pro-nav">
            <button class="btn btn-green" onclick="doCashOp('float_in')">💵 Размен</button>
            <button class="btn btn-yellow" onclick="doCashOp('collection')">🏦 Инкасс.</button>
            <a href="/kitchen" class="btn btn-blue">🍳 Кухня KDS</a>
            <a href="/autopilot" class="btn" style="background:#0ea5e9">🔪 Чек-лист</a>
            <a href="/warehouse" class="btn btn-purple">📦 Склад</a>
            <a href="/site" target="_blank" class="btn btn-ghost">📱 Витрина сайта</a>
            <a href="/admin" class="btn">⚙️ Админка</a>
            <button onclick="document.body.classList.toggle('light-theme');localStorage.setItem('theme', document.body.classList.contains('light-theme')?'light':'dark')" class="btn btn-ghost">🌓 Тема</button>
        </div>
    </div>

    <div class="search-cats-bar">
        <input type="text" id="search-input" placeholder="🔍 Быстрый поиск блюда (Esc)..." oninput="filterMenu()" style="width: 250px; font-weight: 700;">
        <div class="cats-scroll">
            <button class="cat-pill active" onclick="filterCat('all', this)">Все блюда</button>
            <button class="cat-pill" onclick="filterStation('baked', this)" style="border-color:#ef4444">🔥 Запечённые</button>
            <button class="cat-pill" onclick="filterStation('tempura', this)" style="border-color:#f59e0b">🍤 Темпура</button>
            {% for c in categories %}
            <button class="cat-pill" onclick="filterCat('{{ c.category }}', this)">{{ c.category }}</button>
            {% endfor %}
        </div>
    </div>

    <div class="sushi-upsell-bar">
        <span style="font-size:12px;font-weight:900;color:var(--accent)">🥢 ДОПЫ В 1 КЛИК:</span>
        <button class="addon-btn" onclick="addCustomItem('Соевый соус 50мл', 40)">+ Соевый (40₽)</button>
        <button class="addon-btn" onclick="addCustomItem('Имбирь 30г', 40)">+ Имбирь (40₽)</button>
        <button class="addon-btn" onclick="addCustomItem('Васаби 15г', 30)">+ Васаби (30₽)</button>
        <button class="addon-btn" onclick="addCustomItem('Набор для суши', 90)">🍱 +Набор (90₽)</button>
        <button class="addon-btn" onclick="addCustomItem('Спайси соус', 50)">🌶️ +Спайси (50₽)</button>
        <button class="addon-btn" onclick="addCustomItem('Унаги соус', 50)">🍯 +Унаги (50₽)</button>
    </div>

    <div class="menu-grid" id="menu-grid">
        {% for m in menu %}
        {% set lname = m.name | lower %}
        {% set lcat = (m.category or '') | lower %}
        {% if 'запеч' in lname or 'запеч' in lcat %}
            {% set st_type = 'baked' %}{% set st_label = '🔥 ЗАПЕЧЁННЫЙ' %}{% set st_class = 'tag-baked' %}
        {% elif 'темпур' in lname or 'жарен' in lname or 'темпур' in lcat %}
            {% set st_type = 'tempura' %}{% set st_label = '🍤 ТЕМПУРА' %}{% set st_class = 'tag-tempura' %}
        {% else %}
            {% set st_type = 'cold' %}{% set st_label = '❄️ ХОЛОДНЫЙ ЦЕХ' %}{% set st_class = 'tag-cold' %}
        {% endif %}
        <div class="sushi-card" data-name="{{ lname }}" data-cat="{{ m.category }}" data-station="{{ st_type }}" onclick="addToCart({{ m.id }}, '{{ m.name }}', {{ m.price }}, '{{ m.category }}')">
            <span class="station-tag {{ st_class }}">{{ st_label }}</span>
            <div style="font-weight:800;font-size:15px;margin-bottom:4px;line-height:1.25">{{ m.name }}</div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;flex:1">{{ m.category }} {% if 'ролл' in lcat or 'ролл' in lname %}• 8 кус.{% endif %}</div>
            <div style="font-weight:900;color:var(--accent);font-size:18px">{{ m.price }} ₽</div>
        </div>
        {% endfor %}
    </div>
</div>

<div class="right-pane">
    <div class="tabs-bar">
        <button class="tab-trigger active" id="tab-new" onclick="switchRightTab('new')">🛒 Оформление заказа</button>
        <button class="tab-trigger" id="tab-orders" onclick="switchRightTab('orders')">📋 Состояние заказов (<span id="orders-cnt">0</span>)</button>
    </div>

    <!-- ВКЛАДКА 1: НОВЫЙ ЗАКАЗ -->
    <div id="pane-new" style="flex:1;display:flex;flex-direction:column;overflow:hidden">
        <div class="sushi-stats-bar">
            <div class="stat-pill"><span>🍣 Роллов: <b id="rolls-count" style="color:var(--accent)">0</b> (<b id="pieces-count">0</b> кус.)</span></div>
            <div class="stat-pill"><span>🎁 Беспл. наборов: <b id="free-kits-count" style="color:var(--green)">0</b></span></div>
            <div class="stat-pill">
                <span>🥢 Персон:</span>
                <button class="btn btn-red" style="padding:2px 8px;font-size:13px" onclick="changeCutlery(-1)">-</button>
                <b id="cutlery-cnt" style="font-size:14px;min-width:16px;text-align:center">2</b>
                <button class="btn btn-green" style="padding:2px 8px;font-size:13px" onclick="changeCutlery(1)">+</button>
            </div>
            <button onclick="clearFullCart()" style="background:none;border:none;color:var(--red);cursor:pointer;font-weight:900;font-size:12px">✕ Очистить</button>
        </div>

        <div class="cart-list" id="cart-list">
            <div style="color:var(--text-muted);text-align:center;margin-top:50px;font-size:15px">Добавьте позиции из меню слева 👈</div>
        </div>

        <div class="checkout-panel">
            <!-- ТЕЛЕФОН И ТИП ЗАКАЗА -->
            <div style="display:grid;grid-template-columns:1.1fr 0.9fr;gap:8px;margin-bottom:8px">
                <input type="tel" id="phone" placeholder="📞 Телефон клиента..." style="width:100%;font-weight:700">
                <select id="del-type" onchange="onDeliveryTypeChange()" style="width:100%;font-weight:800">
                    <option value="самовывоз">🏃 Самовывоз (0 ₽)</option>
                    <option value="доставка">🚗 Доставка курьером</option>
                </select>
            </div>

            <!-- ВСЕГДА ДОСТУПНОЕ ПОЛЕ АДРЕСА: ПРИ ВВОДЕ АВТОМАТОМ ВКЛЮЧАЕТ ДОСТАВКУ И ЗОНУ -->
            <div style="background:var(--bg-main);padding:10px;border-radius:10px;border:1px solid var(--border);margin-bottom:8px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                    <span style="font-size:11px;font-weight:900;color:var(--text-muted)">📍 АДРЕС И ЗОНА ДОСТАВКИ (АВТОВКЛЮЧЕНИЕ ПРИ ВВОДЕ):</span>
                    <span id="zone-indicator" style="font-size:11px;font-weight:900;color:var(--accent)">Самовывоз</span>
                </div>
                <div style="display:grid;grid-template-columns:2.2fr 1fr;gap:6px;margin-bottom:8px">
                    <input type="text" id="address" list="inta-streets" placeholder="🏠 Введите улицу/район (авто-доставка)..." oninput="onAddressTyped(this.value)" style="width:100%;font-weight:700">
                    <input type="text" id="entrance-code" placeholder="Подъезд/Домофон" oninput="onAddressTyped(document.getElementById('address').value)" style="width:100%">
                </div>
                <datalist id="inta-streets">
                    <option value="Центр, ул. Горького, д. ">
                    <option value="Центр, ул. Мира, д. ">
                    <option value="Центр, ул. Куратова, д. ">
                    <option value="Центр, ул. Полярная, д. ">
                    <option value="Западный, ул. Бабушкина, д. ">
                    <option value="Западный, ул. Чайковского, д. ">
                    <option value="Западный, ул. Промышленная, д. ">
                    <option value="Южный, ул. Морозова, д. ">
                    <option value="Южный, ул. Лунина, д. ">
                    <option value="Верхняя Инта, ул. Станционная, д. ">
                    <option value="Верхняя Инта, ул. Вокзальная, д. ">
                </datalist>
                <div style="display:flex;gap:5px">
                    <div class="zone-pill" id="z-center" onclick="selectZoneManual('center')">Центр (0₽)</div>
                    <div class="zone-pill" id="z-zapad" onclick="selectZoneManual('zapad')">Западный (150₽)</div>
                    <div class="zone-pill" id="z-yug" onclick="selectZoneManual('yug')">Южный (250₽)</div>
                    <div class="zone-pill" id="z-verh" onclick="selectZoneManual('verh')">Верхняя Инта (1000₽)</div>
                </div>
            </div>

            <div style="margin-bottom:8px">
                <input type="text" id="comment" placeholder="💬 Комментарий к заказу..." style="width:100%;padding:8px 12px">
            </div>

            <!-- СПОСОБЫ ОПЛАТЫ (ЕДИНЫЙ СТАНДАРТ CASH / CARD / SBP) -->
            <div style="display:flex;gap:6px;margin-bottom:8px">
                <div class="pay-pill active" id="btn-cash" onclick="setPayment('cash')">💵 Наличные</div>
                <div class="pay-pill" id="btn-card" onclick="setPayment('card')">💳 Карта</div>
                <div class="pay-pill" id="btn-sbp" onclick="setPayment('sbp')">📱 СБП</div>
            </div>

            <div id="cash-change-box" style="margin-bottom:8px;background:var(--bg-main);padding:8px 10px;border-radius:8px;border:1px solid var(--border)">
                <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
                    <span style="font-size:12px;color:var(--text-muted)">Купюра клиента:</span>
                    <input type="number" id="cash-given" placeholder="₽" oninput="calcChange()" style="width:105px;padding:4px 8px;margin-left:auto;font-weight:800">
                    <span id="change-output" style="font-size:13px;font-weight:900;color:var(--green);min-width:120px;text-align:right">Сдача: 0 ₽</span>
                </div>
                <div style="display:flex;gap:5px">
                    <button type="button" class="bill-quick" onclick="setCashGiven(500)">500</button>
                    <button type="button" class="bill-quick" onclick="setCashGiven(1000)">1000</button>
                    <button type="button" class="bill-quick" onclick="setCashGiven(2000)">2000</button>
                    <button type="button" class="bill-quick" onclick="setCashGiven(5000)">5000</button>
                    <button type="button" class="bill-quick" onclick="setExactCash()" style="background:var(--accent);color:#fff">Точно</button>
                </div>
            </div>

            <div style="display:flex;justify-content:space-between;align-items:center;margin:6px 0 8px 0">
                <span style="font-size:15px;font-weight:800">ИТОГО К ОПЛАТЕ:</span>
                <strong id="cart-total" style="color:var(--accent);font-size:24px;font-weight:900">0 ₽</strong>
            </div>
            <button class="btn" style="width:100%;padding:15px;font-size:16px" onclick="submitOrder()">🚀 ОФОРМИТЬ ЗАКАЗ И ОТКРЫТЬ СТАТУС (F9)</button>
        </div>
    </div>

    <!-- ВКЛАДКА 2: НАГЛЯДНОЕ СОСТОЯНИЕ ВСЕХ ЗАКАЗОВ СМЕНЫ -->
    <div id="pane-orders" style="flex:1;display:none;flex-direction:column;overflow:hidden">
        <div style="padding:10px 16px;background:var(--bg-panel);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
            <span style="font-size:13px;font-weight:900">🔴 ЖИВОЙ МОНИТОР СОСТОЯНИЯ ЗАКАЗОВ</span>
            <button class="btn" style="padding:6px 12px;font-size:12px" onclick="loadPosOrders()">🔄 Обновить</button>
        </div>
        <div class="orders-feed" id="pos-orders-container"></div>
    </div>
</div>

<script>
let cart = {};
let activeCategory = 'all';
let activeStation = null;
let currentPayment = 'cash';
let currentTotal = 0;
let cutleryCount = 2;
let currentZoneKey = 'center';
let deliveryFee = 0;
let customIdCounter = 95000;
let lastCreatedOrderId = null;

if(localStorage.getItem('theme') === 'light') document.body.classList.add('light-theme');

// Автоматическое включение доставки и зоны при вводе адреса
function onAddressTyped(val) {
    let clean = (val || '').trim();
    let delSelect = document.getElementById('del-type');
    if(clean.length > 0) {
        if(delSelect.value !== 'доставка') {
            delSelect.value = 'доставка';
        }
        let detected = window.detectIntaZoneByAddress(clean);
        if(detected) {
            applyZone(detected);
        }
    } else {
        delSelect.value = 'самовывоз';
        onDeliveryTypeChange();
    }
}

function selectZoneManual(zoneKey) {
    document.getElementById('del-type').value = 'доставка';
    let addrInput = document.getElementById('address');
    let zName = window.INTA_ZONES[zoneKey].name;
    if(!addrInput.value.trim()) {
        addrInput.value = zName + ', ул. ';
        addrInput.focus();
    }
    applyZone(zoneKey);
}

function applyZone(zoneKey) {
    currentZoneKey = zoneKey;
    let z = window.INTA_ZONES[zoneKey] || window.INTA_ZONES['center'];
    deliveryFee = z.fee;
    ['center', 'zapad', 'yug', 'verh'].forEach(k => {
        document.getElementById('z-' + k).classList.toggle('active', k === zoneKey);
    });
    document.getElementById('zone-indicator').innerText = `🚗 ${z.name} (+${z.fee} ₽)`;
    renderCart();
}

function onDeliveryTypeChange() {
    let t = document.getElementById('del-type').value;
    if(t === 'самовывоз') {
        deliveryFee = 0;
        ['center', 'zapad', 'yug', 'verh'].forEach(k => document.getElementById('z-' + k).classList.remove('active'));
        document.getElementById('zone-indicator').innerText = '🏃 Самовывоз (0 ₽)';
    } else {
        let detected = window.detectIntaZoneByAddress(document.getElementById('address').value) || currentZoneKey || 'center';
        applyZone(detected);
    }
    renderCart();
}

function changeCutlery(delta) {
    cutleryCount = Math.max(0, cutleryCount + delta);
    document.getElementById('cutlery-cnt').innerText = cutleryCount;
}

function switchRightTab(tab) {
    document.getElementById('tab-new').classList.toggle('active', tab === 'new');
    document.getElementById('tab-orders').classList.toggle('active', tab === 'orders');
    document.getElementById('pane-new').style.display = (tab === 'new') ? 'flex' : 'none';
    document.getElementById('pane-orders').style.display = (tab === 'orders') ? 'flex' : 'none';
    if(tab === 'orders') loadPosOrders();
}

function setPayment(method) {
    currentPayment = method;
    ['cash', 'card', 'sbp'].forEach(k => {
        document.getElementById('btn-' + k).classList.toggle('active', method === k);
    });
    document.getElementById('cash-change-box').style.display = (method === 'cash') ? 'block' : 'none';
    calcChange();
}

function setCashGiven(amount) { document.getElementById('cash-given').value = amount; calcChange(); }
function setExactCash() { document.getElementById('cash-given').value = currentTotal; calcChange(); }

function calcChange() {
    let given = parseInt(document.getElementById('cash-given').value) || 0;
    let out = document.getElementById('change-output');
    let change = given - currentTotal;
    if(change >= 0) {
        out.innerText = `Сдача: ${change} ₽`;
        out.style.color = 'var(--green)';
    } else {
        out.innerText = `Ещё: ${Math.abs(change)} ₽`;
        out.style.color = 'var(--red)';
    }
}

function filterCat(cat, btn) {
    activeCategory = cat; activeStation = null;
    document.querySelectorAll('.cat-pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    filterMenu();
}

function filterStation(st, btn) {
    activeStation = st; activeCategory = 'all';
    document.querySelectorAll('.cat-pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    filterMenu();
}

function filterMenu() {
    let query = document.getElementById('search-input').value.toLowerCase().trim();
    document.querySelectorAll('.sushi-card').forEach(card => {
        let matchCat = (activeCategory === 'all' || card.dataset.cat === activeCategory);
        let matchSt = (!activeStation || card.dataset.station === activeStation);
        let matchQuery = (!query || card.dataset.name.includes(query));
        card.style.display = (matchCat && matchSt && matchQuery) ? 'flex' : 'none';
    });
}

function addToCart(id, name, price, category) {
    if(!cart[id]) cart[id] = {id, name, price, category: category || '', qty: 0, note: ''};
    cart[id].qty++;
    renderCart();
}

function addCustomItem(name, price) {
    let existing = Object.values(cart).find(i => i.name === name);
    if(existing) existing.qty++;
    else {
        let cid = ++customIdCounter;
        cart[cid] = {id: cid, name: name, price: price, category: 'Допы', qty: 1, note: ''};
    }
    renderCart();
}

function toggleItemNote(id, tag) {
    if(!cart[id]) return;
    let notes = cart[id].note ? cart[id].note.split(', ') : [];
    if(notes.includes(tag)) notes = notes.filter(n => n !== tag);
    else notes.push(tag);
    cart[id].note = notes.join(', ');
    renderCart();
}

function changeQty(id, delta) {
    if(!cart[id]) return;
    cart[id].qty += delta;
    if(cart[id].qty <= 0) delete cart[id];
    renderCart();
}

function clearFullCart() {
    cart = {};
    document.getElementById('address').value = '';
    document.getElementById('entrance-code').value = '';
    document.getElementById('del-type').value = 'самовывоз';
    onDeliveryTypeChange();
}

function renderCart() {
    let list = document.getElementById('cart-list'), subtotal = 0, html = '', rollsPortions = 0;
    for(let id in cart) {
        let i = cart[id];
        subtotal += i.price * i.qty;
        let lname = i.name.toLowerCase(), lcat = (i.category || '').toLowerCase();
        if(lname.includes('ролл') || lcat.includes('ролл')) rollsPortions += i.qty;
        else if(lname.includes('сет') || lcat.includes('сет')) rollsPortions += i.qty * 4;

        let tags = ['Без васаби', 'Без имбиря', 'Без лука', 'Острый 🔥', 'В фольгу 🥡'];
        let chipsHtml = tags.map(t => `<span class="mod-pill ${(i.note || '').includes(t) ? 'active' : ''}" onclick="toggleItemNote(${id}, '${t}')">${t}</span>`).join('');

        html += `<div class="cart-row">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                    <b style="font-size:15px">${i.name}</b>
                    ${i.note ? `<div style="font-size:11px;color:#60a5fa;font-weight:800">⚡ ${i.note}</div>` : ''}
                    <div style="color:var(--text-muted);font-size:12px">${i.price} ₽ × ${i.qty} = <b>${i.price * i.qty} ₽</b></div>
                </div>
                <div style="display:flex;align-items:center;gap:6px">
                    <button onclick="changeQty(${id}, -1)" class="btn btn-red qty-btn">-</button>
                    <b style="min-width:22px;text-align:center;font-size:16px">${i.qty}</b>
                    <button onclick="changeQty(${id}, 1)" class="btn btn-green qty-btn">+</button>
                </div>
            </div>
            <div class="mod-bar">${chipsHtml}</div>
        </div>`;
    }
    list.innerHTML = html || '<div style="color:var(--text-muted);text-align:center;margin-top:50px;font-size:15px">Добавьте позиции из меню слева 👈</div>';

    document.getElementById('rolls-count').innerText = rollsPortions;
    document.getElementById('pieces-count').innerText = rollsPortions * 8;
    document.getElementById('free-kits-count').innerText = Math.ceil(rollsPortions / 2);

    let delType = document.getElementById('del-type').value;
    let activeFee = (delType === 'доставка') ? deliveryFee : 0;
    currentTotal = subtotal + activeFee;
    document.getElementById('cart-total').innerText = currentTotal + ' ₽' + (activeFee > 0 ? ` (вкл. дост. ${activeFee}₽)` : '');
    calcChange();
}

function submitOrder() {
    let items = Object.values(cart).map(i => ({
        id: i.id,
        name: i.name + (i.note ? ` [${i.note}]` : ''),
        qty: i.qty,
        price: i.price
    }));
    if(items.length === 0) return alert('Корзина пуста!');

    let phone = document.getElementById('phone').value.trim();
    let delType = document.getElementById('del-type').value;
    let addrMain = document.getElementById('address').value.trim();
    let addrCode = document.getElementById('entrance-code').value.trim();

    if(addrMain.length > 0 && delType !== 'доставка') {
        delType = 'доставка';
        document.getElementById('del-type').value = 'доставка';
    }
    if(delType === 'доставка' && !addrMain) return alert('Введите адрес доставки!');

    if(delType === 'доставка' && deliveryFee > 0) {
        let zName = (window.INTA_ZONES[currentZoneKey] || {}).name || 'Доставка';
        items.push({ id: 99901, name: `Доставка (${zName})`, qty: 1, price: deliveryFee });
    }

    let address = (delType === 'доставка') ? (addrMain + (addrCode ? ` (${addrCode})` : '')) : 'Самовывоз';
    let comment = document.getElementById('comment').value.trim();
    let fullComment = (`🥢 Персон: ${cutleryCount}` + (comment ? ' | ' + comment : '')).trim();
    let payCashVal = (currentPayment === 'cash') ? currentTotal : 0;

    fetch('/api/create_order', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            items, phone, delivery_type: delType, address, comment: fullComment,
            payment_method: currentPayment, pay_cash: payCashVal
        })
    }).then(r=>r.json()).then(d=>{
        if(d.success){
            lastCreatedOrderId = d.order_id;
            clearFullCart();
            document.getElementById('phone').value = '';
            document.getElementById('comment').value = '';
            document.getElementById('cash-given').value = '';
            // Сразу переключаем кассира на вкладку состояния заказов, чтобы он видел статус нового заказа!
            switchRightTab('orders');
            window.open('/receipt/' + d.order_id, '_blank');
        } else {
            alert('Ошибка: ' + (d.error || 'Не удалось создать заказ'));
        }
    });
}

function quickOrderStatus(id, st) {
    fetch('/api/set_status/' + id, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: st})
    }).then(r=>r.json()).then(d => {
        if(d.success) loadPosOrders();
    });
}

function renderStepper(status) {
    let steps = [
        {key: 'new', label: '1. Принят'},
        {key: 'cooking', label: '2. Готовится'},
        {key: 'delivering', label: '3. В пути/Готов'},
        {key: 'done', label: '4. Выдан'}
    ];
    let orderIdx = {'new':0, 'cooking':1, 'ready':2, 'delivering':2, 'done':3}[status] ?? 0;
    return `<div class="state-stepper">` + steps.map((s, idx) => {
        let cls = idx < orderIdx ? 'done' : (idx === orderIdx ? 'current' : '');
        return `<div class="step-node ${cls}">${s.label}</div>`;
    }).join('') + `</div>`;
}

function loadPosOrders() {
    fetch('/api/orders').then(r=>r.json()).then(data => {
        let orders = Array.isArray(data) ? data : (data.orders || []);
        document.getElementById('orders-cnt').innerText = orders.length;
        let c = document.getElementById('pos-orders-container');
        if(!orders.length) {
            c.innerHTML = '<div style="text-align:center;color:var(--text-muted);margin-top:70px">Активных заказов за смену пока нет</div>';
            return;
        }
        let html = '';
        orders.slice(0, 35).forEach(o => {
            let isJustCreated = (o.id === lastCreatedOrderId) ? 'highlight-new' : '';
            let itemsText = (o.items || []).map(i => `<b>${i.name}</b> ×${i.qty}`).join(', ');
            html += `<div class="order-card ${isJustCreated}">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-weight:900;font-size:16px">#${o.id} • ${(o.delivery_type || 'доставка').toUpperCase()} ${o.phone ? '📞 '+o.phone : ''}</span>
                    <a href="/track/${o.id}" target="_blank" style="color:var(--accent);font-size:12px;font-weight:800;text-decoration:none">🔗 Экран статуса →</a>
                </div>
                ${renderStepper(o.status || 'new')}
                ${o.address && o.address !== 'Самовывоз' ? `<div style="font-size:13px;color:#60a5fa;margin-bottom:4px;font-weight:700">📍 ${o.address}</div>` : ''}
                ${o.comment ? `<div style="font-size:12px;color:#fbbf24;margin-bottom:6px">${o.comment}</div>` : ''}
                <div style="font-size:13px;color:var(--text-main);margin-bottom:10px">${itemsText}</div>
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
                    <span style="font-weight:900;color:var(--accent);font-size:18px">${o.total} ₽ <span style="font-size:12px;color:var(--text-muted)">(${o.payment_method || 'cash'})</span></span>
                    <div style="display:flex;gap:5px;flex-wrap:wrap">
                        <button class="btn btn-yellow" style="padding:6px 10px;font-size:11px" onclick="quickOrderStatus(${o.id}, 'cooking')">👨‍🍳 Готовится</button>
                        <button class="btn btn-green" style="padding:6px 10px;font-size:11px" onclick="quickOrderStatus(${o.id}, 'ready')">✅ Готов</button>
                        <button class="btn btn-purple" style="padding:6px 10px;font-size:11px" onclick="quickOrderStatus(${o.id}, 'delivering')">🚗 В пути</button>
                        <button class="btn" style="padding:6px 10px;font-size:11px;background:#475569" onclick="quickOrderStatus(${o.id}, 'done')">🏁 Выдан</button>
                        <button class="btn btn-blue" style="padding:6px 10px;font-size:11px" onclick="window.open('/receipt/${o.id}', '_blank')">🧾 Чек</button>
                    </div>
                </div>
            </div>`;
        });
        c.innerHTML = html;
    }).catch(() => {});
}

function doCashOp(opType){
    fetch('/api/cash_balance').then(r=>r.json()).then(b=>{
        let title = opType === 'float_in' ? '💵 Внесение размена' : '🏦 Инкассация';
        let amt = parseInt(prompt(`${title}\nВ кассе наличных: ${b.drawer_cash || 0} ₽\nВведите сумму (₽):`, ''));
        if(!amt || amt <= 0) return;
        let comm = prompt('Комментарий:', opType === 'float_in' ? 'Размен' : 'Инкассация') || '';
        fetch('/api/cash_op', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({op_type:opType, amount:amt, comment:comm})})
        .then(r=>r.json()).then(d => { if(d.success) alert('✅ Операция проведена!'); else alert(d.error); });
    });
}

loadPosOrders();
setInterval(loadPosOrders, 5000);
</script>
</body></html>
```

### ФАЙЛ: templates/change_password.html
```html
<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Смена пароля — Креветка</title>
<meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script>
<style>
body{font-family:-apple-system,sans-serif;background:#1e1e1e;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px}
.box{background:#252525;padding:36px;border-radius:16px;width:360px;max-width:100%;box-shadow:0 16px 40px rgba(0,0,0,.45)}
h1{margin-top:0;text-align:center;font-size:22px}
p.hint{color:#aaa;font-size:13px;line-height:1.45;text-align:center}
label{display:block;font-size:13px;color:#aaa;margin:14px 0 4px}
input{width:100%;box-sizing:border-box;padding:12px;background:#1e1e1e;color:#fff;border:1px solid #444;border-radius:8px}
button{width:100%;padding:14px;background:#30d158;color:#000;border:none;border-radius:8px;font-size:16px;font-weight:bold;cursor:pointer;margin-top:18px}
a{display:block;text-align:center;color:#0a84ff;margin-top:14px;text-decoration:none;font-size:13px}
.msg{color:#ff453a;text-align:center;margin-top:14px}
</style><link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>
<div class="box">
<h1>🔐 Смена пароля</h1>
<p class="hint">Пароль по умолчанию больше не действует. Задайте новый пароль (не короче 10 символов).</p>
<form method="post">
<label>Текущий пароль</label>
<input name="old_password" type="password" required autofocus autocomplete="current-password">
<label>Новый пароль</label>
<input name="new_password" type="password" required minlength="10" autocomplete="new-password">
<label>Повторите новый пароль</label>
<input name="confirm_password" type="password" required minlength="10" autocomplete="new-password">
<button type="submit">Сохранить пароль</button>
</form>
{% for m in get_flashed_messages() %}<div class="msg">{{ m }}</div>{% endfor %}
<a href="/logout">Выйти</a>
</div></body></html>
```

### ФАЙЛ: templates/chat.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>Чат — Креветка</title>
<!-- PWA для отдельного приложения -->
<link rel="manifest" href="/chat_manifest.json">
<meta name="theme-color" content="#0a0a0a">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
:root {
    --bg-main: #0a0a0a; --bg-panel: #151515; --bg-card: #1c1c1e; --bg-input: #151515;
    --text-main: #ffffff; --text-muted: #888888; --border: #333333;
    --accent: #ff7a00; --accent-text: #000000; --btn-grey: #333333;
    --msg-mine: #ff7a00; --msg-mine-text: #000000;
    --msg-other: #2a2a2a; --msg-other-text: #ffffff;
}
body.light-theme {
    --bg-main: #e9ecef; --bg-panel: #ffffff; --bg-card: #ffffff; --bg-input: #ffffff;
    --text-main: #212529; --text-muted: #6c757d; --border: #ced4da;
    --accent: #ff7a00; --accent-text: #ffffff; --btn-grey: #dee2e6;
    --msg-mine: #ff7a00; --msg-mine-text: #ffffff;
    --msg-other: #ffffff; --msg-other-text: #212529;
}
body{font-family:-apple-system,sans-serif;background:var(--bg-main);color:var(--text-main);margin:0;display:flex;flex-direction:column;height:100vh; transition: background 0.3s, color 0.3s;}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:15px 20px;background:var(--bg-panel);border-bottom:1px solid var(--border); z-index: 10;}
h1{margin:0;color:var(--accent);font-size:20px;}
a{color:var(--accent);text-decoration:none;font-weight:bold;}

.chat-container{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:15px; background: var(--bg-main);}
.msg-row{display:flex; width: 100%;}
.msg-row.mine{justify-content: flex-end;}
.msg-row.other{justify-content: flex-start;}

.avatar {
    width: 35px; height: 35px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-weight: bold; font-size: 16px; color: #fff; margin-right: 10px; flex-shrink: 0;
}
.msg-content { display: flex; flex-direction: column; max-width: 70%; }
.msg { padding: 10px 15px; border-radius: 15px; font-size: 15px; line-height: 1.4; box-shadow:0 1px 2px rgba(0,0,0,0.1); word-break: break-word; }
.msg.mine { background: var(--msg-mine); color: var(--msg-mine-text); border-bottom-right-radius: 4px; }
.msg.other { background: var(--msg-other); color: var(--msg-other-text); border-bottom-left-radius: 4px; border: 1px solid var(--border); }

.msg-meta { display: flex; justify-content: flex-end; align-items: center; gap: 5px; font-size: 11px; margin-top: 4px; opacity: 0.7; }
.msg-author { font-size: 12px; margin-bottom: 4px; color: var(--text-muted); font-weight: bold;}

.typing-indicator { font-size: 13px; color: var(--text-muted); padding: 0 20px 10px 20px; height: 20px; font-style: italic; }

.input-area{padding:10px 20px;background:var(--bg-panel);border-top:1px solid var(--border);display:flex;gap:10px; align-items: center;}
input[type="text"]{flex:1;padding:12px 15px;border-radius:20px;border:1px solid var(--border);background:var(--bg-input);color:var(--text-main);font-size:15px;outline:none;}
input[type="text"]:focus{border-color:var(--accent);}
button.send-btn{background:var(--accent);color:var(--accent-text);border:none;width:45px;height:45px;border-radius:50%;font-weight:bold;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;}
button.send-btn:hover{opacity:0.9;}
.theme-btn{background:var(--bg-card);color:var(--text-main);border:1px solid var(--border);padding:6px 10px;border-radius:8px;cursor:pointer;font-size:16px;margin-left:15px;}
.btn-clear{background:#ff453a;color:#fff;border:none;padding:6px 12px;border-radius:8px;font-size:13px;cursor:pointer;margin-left:10px;}
.btn-sound{background:#30d158;color:#000;border:none;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:bold;cursor:pointer;margin-left:10px; display:none;}
.btn-sound.off{background:#555;color:#fff;}

/* Генератор случайных цветов для аватарок */
.bg-1 { background: #e74c3c; } .bg-2 { background: #3498db; } .bg-3 { background: #2ecc71; }
.bg-4 { background: #9b59b6; } .bg-5 { background: #f1c40f; } .bg-6 { background: #e67e22; }
</style>
<script>
    if(localStorage.getItem('theme') === 'light') { document.documentElement.classList.add('light-theme'); }
</script>
<link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>

<div class="topbar">
    <div style="display:flex; align-items:center;">
        <h1>💬 Чат</h1>
        <button id="sound-btn" class="btn-sound off" onclick="toggleSound()">🔕 Включить звук</button>
        <button class="btn-clear" onclick="clearChat()">Очистить</button>
    </div>
    <div style="display:flex; align-items:center;">
        <a href="javascript:history.back()">← Назад</a>
        <button class="theme-btn" onclick="toggleTheme()" id="theme-btn">🌙</button>
    </div>
</div>

<div class="chat-container" id="chat-box"></div>
<div class="typing-indicator" id="typing-indicator"></div>

<div class="input-area">
    <input type="text" id="msg-input" placeholder="Написать сообщение..." oninput="sendTyping()" onkeypress="handleEnter(event)">
    <button class="send-btn" onclick="sendMessage()">➤</button>
</div>

<script>
function toggleTheme() {
    document.body.classList.toggle('light-theme');
    const isLight = document.body.classList.contains('light-theme');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    document.getElementById('theme-btn').innerText = isLight ? '🌙' : '☀️';
}
document.addEventListener('DOMContentLoaded', () => {
    if(localStorage.getItem('theme') === 'light') { document.body.classList.add('light-theme'); document.getElementById('theme-btn').innerText = '🌙'; } 
    else { document.getElementById('theme-btn').innerText = '☀️'; }
});

const MY_NAME = "{{ session['username'] }}";
let lastMsgId = 0;
let isFirstLoad = true;
let typingTimeout = null;

// --- ЛОГИКА ЗВУКА ---
let soundEnabled = false;
let audioCtx = null;

function toggleSound() {
    if (!soundEnabled) {
        // Разблокируем аудио-контекст (требование браузеров)
        if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (audioCtx.state === 'suspended') audioCtx.resume();
        soundEnabled = true;
        document.getElementById('sound-btn').innerText = '🔔 Звук включен';
        document.getElementById('sound-btn').classList.remove('off');
        // Проигрываем тестовый звук
        playBeep();
    } else {
        soundEnabled = false;
        document.getElementById('sound-btn').innerText = '🔕 Включить звук';
        document.getElementById('sound-btn').classList.add('off');
    }
}

function playBeep() {
    if (!soundEnabled || !audioCtx) return;
    try {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        
        osc.type = 'square'; // Квадратная волна звучит резче и громче
        osc.frequency.setValueAtTime(800, audioCtx.currentTime);
        osc.frequency.setValueAtTime(1200, audioCtx.currentTime + 0.1);
        
        gain.gain.setValueAtTime(1, audioCtx.currentTime); // Максимальная громкость
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.4);
        
        osc.start();
        osc.stop(audioCtx.currentTime + 0.4);
    } catch(e) { console.log("Audio error:", e); }
}
// --------------------

function getAvatarClass(name) {
    let hash = 0;
    for (let i = 0; i < name.length; i++) { hash = name.charCodeAt(i) + ((hash << 5) - hash); }
    let color = Math.abs(hash) % 6 + 1;
    return `bg-${color}`;
}

function loadMessages() {
    fetch('/api/chat/get').then(r=>r.json()).then(data=>{
        const msgs = data.messages;
        const typers = data.typing;
        const box = document.getElementById('chat-box');
        let isScrolledToBottom = box.scrollHeight - box.clientHeight <= box.scrollTop + 50;
        
        // Проверка на новое сообщение (для звука)
        if (msgs.length > 0) {
            const latestMsg = msgs[msgs.length - 1];
            if (!isFirstLoad && latestMsg.id > lastMsgId && latestMsg.sender_name !== MY_NAME) {
                playBeep();
            }
            lastMsgId = latestMsg.id;
        }
        isFirstLoad = false;
        
        box.innerHTML = '';
        msgs.forEach(m => {
            const isMine = m.sender_name === MY_NAME;
            
            const row = document.createElement('div');
            row.className = `msg-row ${isMine ? 'mine' : 'other'}`;
            
            let avatarHtml = '';
            if (!isMine) {
                const initial = m.sender_name.charAt(0).toUpperCase();
                avatarHtml = `<div class="avatar ${getAvatarClass(m.sender_name)}">${initial}</div>`;
            }
            
            const textDiv = document.createElement('div');
            textDiv.textContent = m.text;
            
            const checkmarks = isMine ? `<span style="font-size:12px; margin-left:5px; color:${m.is_read ? '#30d158' : 'var(--msg-mine-text)'}">${m.is_read ? '✓✓' : '✓'}</span>` : '';
            
            row.innerHTML = `
                ${avatarHtml}
                <div class="msg-content">
                    ${!isMine ? `<div class="msg-author">${m.sender_name}</div>` : ''}
                    <div class="msg ${isMine ? 'mine' : 'other'}"></div>
                    <div class="msg-meta">${m.created_at} ${checkmarks}</div>
                </div>
            `;
            row.querySelector('.msg').appendChild(textDiv);
            box.appendChild(row);
        });
        
        const tInd = document.getElementById('typing-indicator');
        if (typers.length > 0) {
            tInd.innerText = `${typers.join(', ')} печатает...`;
        } else {
            tInd.innerText = '';
        }
        
        if (msgs.length > 0 && (isScrolledToBottom || lastMsgId !== msgs[msgs.length-1].id)) {
            box.scrollTop = box.scrollHeight;
        }
    });
}

function sendMessage() {
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text) return;
    
    input.value = '';
    fetch('/api/chat/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text})
    }).then(() => loadMessages());
}

function sendTyping() {
    if (typingTimeout) return;
    fetch('/api/chat/typing', {method: 'POST'});
    typingTimeout = setTimeout(() => { typingTimeout = null; }, 2000);
}

function handleEnter(e) {
    if (e.key === 'Enter') sendMessage();
}

function clearChat() {
    if(!confirm('Вы уверены, что хотите удалить все сообщения?')) return;
    fetch('/api/chat/clear', {method: 'POST'}).then(() => loadMessages());
}

setInterval(loadMessages, 2000);
loadMessages();
</script>
</body></html>
```

### ФАЙЛ: templates/courier.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Курьер PRO — Креветка</title>
<link rel="manifest" href="/manifest.json">
<style>
body{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#fff;margin:0;padding:20px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}
h1{margin:0;color:#ff7a00;font-size:24px}a{color:#888;text-decoration:none;font-weight:bold}
.stats-bar{background:#151515;border:1px solid #333;border-radius:12px;padding:12px 15px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}
.orders-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:20px}
.order-card{background:#151515;border-radius:15px;padding:18px;border:2px solid #ff7a00}
.order-card.cash{border-color:#ffd60a}
.order-header{display:flex;justify-content:space-between;border-bottom:1px solid #333;padding-bottom:10px;margin-bottom:10px}
.order-id{font-size:22px;font-weight:bold;color:#ff7a00}
.order-items{list-style:none;padding:0;margin:0 0 12px}.order-items li{padding:4px 0;font-size:16px}
.info{color:#ccc;margin-bottom:12px;font-size:14px;line-height:1.5}.info b{color:#fff}
.change-alert{background:#ffd60a;color:#000;padding:8px;border-radius:8px;font-weight:bold;text-align:center;margin-bottom:10px;font-size:15px}
.btn{width:100%;border:none;padding:13px;border-radius:10px;font-size:15px;font-weight:bold;cursor:pointer;margin-top:6px;background:#30d158;color:#000;text-decoration:none;display:block;text-align:center;box-sizing:border-box}
.btn-pay{background:#ff7a00;color:#000}.btn-call{background:#333;color:#fff}.btn-map{background:#0a84ff;color:#fff}
.empty{text-align:center;color:#555;margin-top:50px;font-size:22px;grid-column:1/-1}
</style><link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>
<div class="topbar">
    <h1>🛵 Курьер: <span id="c-name">...</span></h1>
    <a href="/logout">Выход 🚪</a>
</div>
<div class="stats-bar">
    <div>Выполнено сегодня: <b id="c-count" style="color:#30d158">0</b></div>
    <div>💵 Наличных к сдаче в кассу: <b id="c-cash" style="color:#ffd60a;font-size:18px">0 ₽</b></div>
</div>
<div class="orders-grid" id="orders-container"></div>
<script>
setInterval(() => {
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(pos => {
            fetch('/api/courier/location', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat:pos.coords.latitude,lng:pos.coords.longitude})});
        });
    }
}, 10000);
function fetchStats(){
    fetch('/api/courier/stats').then(r=>r.json()).then(d=>{
        document.getElementById('c-name').innerText = d.courier;
        document.getElementById('c-count').innerText = d.delivered_count;
        document.getElementById('c-cash').innerText = d.cash_on_hand + ' ₽';
    });
}
function fetchOrders(){
    fetchStats();
    fetch('/api/orders?status=ready').then(r=>r.json()).then(ready=>{
        fetch('/api/orders?status=delivering').then(r=>r.json()).then(delivering=>render([...ready,...delivering]));
    });
}
function render(orders){
    const c=document.getElementById('orders-container');c.innerHTML='';
    if(orders.length===0){c.innerHTML='<div class="empty">Нет готовых заказов</div>';return;}
    orders.forEach(o=>{
        const isCash = o.payment_method === 'наличные' || o.payment_cash > 0;
        const card=document.createElement('div');card.className='order-card '+(isCash?'cash':'');
        const items=o.items.map(i=>`<li>${i.name} × ${i.qty}</li>`).join('');
        let changeHtml = (isCash && o.change_from > 0) ? `<div class="change-alert">💵 Сдача с ${o.change_from} ₽: ${o.change_from - o.total} ₽</div>` : '';
        let courierTag = o.courier_name ? `<div>🛵 Взял: <b style="color:#ff7a00">${o.courier_name}</b></div>` : '';
        let mapUrl = o.address ? `https://yandex.ru/maps/?text=${encodeURIComponent('Инта, ' + o.address)}` : '';
        card.innerHTML=`<div class="order-header"><span class="order-id">#${o.id}</span><span>${o.delivery_type === 'самовывоз' ? '🏃 Самовывоз' : '🛵 Доставка'}</span></div>
          <ul class="order-items">${items}</ul>
          <div class="info"><div>💰 Сумма: <b>${o.total} ₽</b> (${o.payment_method})</div><div>📍 Адрес: <b>${o.address || '—'}</b></div>${courierTag}</div>
          ${changeHtml}
          ${mapUrl && o.delivery_type !== 'самовывоз' ? `<a href="${mapUrl}" target="_blank" class="btn btn-map">🗺️ Открыть в Яндекс.Картах</a>` : ''}
          ${o.phone ? `<a href="tel:${o.phone}" class="btn btn-call">📞 Позвонить: ${o.phone}</a>` : ''}
          ${o.status==='ready'?`<button class="btn btn-pay" onclick="setStatus(${o.id},'delivering')">🛵 Забрать заказ (В пути)</button>`:''}
          ${o.status==='delivering'?`<button class="btn" onclick="setStatus(${o.id},'done')">✅ Выдано клиенту</button>`:''}`;
        c.appendChild(card);
    });
}
function setStatus(id,status){fetch('/api/set_status/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})}).then(()=>fetchOrders());}
setInterval(fetchOrders, 3000); fetchOrders();
</script></body></html>
```

### ФАЙЛ: templates/crm.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8"><title>CRM - Клиенты</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0a0a0a">
<style>
body{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#fff;margin:0;padding:30px}
h1{color:#ff7a00}
table{width:100%;border-collapse:collapse;margin-top:20px}
th,td{padding:15px;text-align:left;border-bottom:1px solid #333}
th{color:#888;text-transform:uppercase;font-size:12px;letter-spacing:1px}
tr:hover{background:#151515}
.badge{background:#ffd60a;color:#000;padding:4px 10px;border-radius:12px;font-weight:bold;font-size:12px}
.lvl-bronze{background:#cd7f32;color:#fff;}
.lvl-silver{background:#c0c0c0;color:#000;}
.lvl-gold{background:#ffd700;color:#000; box-shadow: 0 0 10px rgba(255,215,0,0.5);}
a{color:#ff7a00;text-decoration:none;}
</style><link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>
<h1>👥 База клиентов (CRM)</h1>
<a href="/admin" style="color:#888">← Назад в админку</a>
<table>
    <tr><th>Телефон</th><th>Уровень</th><th>Всего заказов</th><th>Потрачено (LTV)</th><th>Бонусы</th><th>Последний заказ</th></tr>
    {% for c in clients %}
    <tr>
        <td><b>{{ c.phone }}</b></td>
        <td>
            {% if c.level == 'gold' %}<span class="badge lvl-gold">🥇 Золото</span>
            {% elif c.level == 'silver' %}<span class="badge lvl-silver">🥈 Серебро</span>
            {% else %}<span class="badge lvl-bronze">🥉 Бронза</span>{% endif %}
        </td>
        <td>{{ c.orders_count }}</td>
        <td style="color:#30d158;font-weight:bold">{{ c.total_spent }} ₽</td>
        <td><span class="badge" style="background:#ff7a00;color:#000;">{{ c.bonuses }} ₽</span></td>
        <td style="color:#888">{{ c.last_order_at or '—' }}</td>
    </tr>
    {% endfor %}
</table>
</body></html>
```

### ФАЙЛ: templates/edit_menu.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>Техкарта (ТТК): {{ item.name }}</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
body{margin:0;padding:30px;display:flex;justify-content:center}
.box{padding:30px;width:720px;max-width:100%}
h1{margin-top:0;color:var(--accent);font-size:24px}
.field{margin-bottom:14px}
.field label{display:block;margin-bottom:5px;color:var(--text-muted);font-size:13px}
.field input{width:100%;padding:10px;box-sizing:border-box;font-size:14px}
.ttc-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;background:var(--bg-card);padding:14px;border-radius:12px;border:1px solid var(--border);margin:15px 0}
.ttc-metric span{display:block;font-size:11px;color:var(--text-muted)}
.ttc-metric b{font-size:18px}
.recipe-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;max-height:360px;overflow-y:auto;padding-right:5px}
.ing-row{display:flex;justify-content:space-between;align-items:center;background:var(--bg-card);padding:8px 12px;border-radius:10px;border:1px solid var(--border)}
.ing-row input{width:75px;padding:6px;text-align:right;font-weight:bold}
.btn{background:var(--accent);color:#fff;border:none;padding:14px;border-radius:10px;cursor:pointer;font-weight:bold;width:100%;font-size:16px;margin-top:15px}
.btn-back{display:block;text-align:center;color:var(--text-muted);margin-top:12px;text-decoration:none}
</style>
<script>if(localStorage.getItem('theme') === 'light') document.documentElement.classList.add('light-theme');</script>
<link rel="stylesheet" href="/static/ui.css">
</head><body>
<div class="box">
    <h1>🍣 Техкарта (ТТК): {{ item.name }}</h1>
    <form method="post" enctype="multipart/form-data">
        <div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:10px">
            <div class="field"><label>Название</label><input name="name" value="{{ item.name }}" required></div>
            <div class="field"><label>Цена продажи (₽)</label><input id="sell-price" name="price" type="number" value="{{ item.price }}" oninput="calcTTC()" required></div>
            <div class="field"><label>Категория</label><input name="category" value="{{ item.category }}" required></div>
            <div class="field"><label>Приоритет</label><input name="sort_weight" type="number" value="{{ item.sort_weight or 0 }}"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
            <div class="field"><label>Описание для сайта (8 шт.)</label><input name="composition" value="{{ item.composition or '' }}"></div>
            <div class="field"><label>Модификаторы (Сыр:50, Спайси:40)</label><input name="modifiers" value="{{ item.modifiers or '' }}"></div>
        </div>
        <div class="field"><label>Обновить фото</label><input type="file" name="image" accept="image/*"></div>

        <div class="ttc-summary">
            <div class="ttc-metric"><span>⚖️ Выход Нетто</span><b id="m-weight">0 г</b></div>
            <div class="ttc-metric"><span>🥩 Себестоимость (с отх.)</span><b id="m-cost" style="color:#ef4444">0 ₽</b></div>
            <div class="ttc-metric"><span>📊 Food Cost (%)</span><b id="m-fc">0 %</b></div>
            <div class="ttc-metric"><span>💰 Чистая маржа</span><b id="m-profit" style="color:#10b981">0 ₽</b></div>
        </div>

        <h3 style="color:#10b981;margin:10px 0 8px">📋 Закладка Нетто на 1 порцию (сырье и П/Ф заготовки):</h3>
        <div class="recipe-grid">
            {% for ing in ingredients %}
            {% set w = ing.waste_pct or 0 %}
            {% set eff_cost = (ing.cost_price / (1 - w/100)) if w < 95 and w > 0 else ing.cost_price %}
            <div class="ing-row">
                <span style="font-size:13px">
                    {% if ing.is_prep %}🍲{% else %}🥩{% endif %} <b>{{ ing.name }}</b>
                    <small style="color:var(--text-muted);display:block">{{ eff_cost|round(2) }} ₽/{{ ing.unit }} {% if w > 0 %}(отх. {{ w }}%){% endif %}</small>
                </span>
                <input type="number" step="any" class="ttc-inp" data-effcost="{{ eff_cost }}" name="ing_{{ ing.id }}" value="{{ recipe.get(ing.id, '') }}" placeholder="0" oninput="calcTTC()">
            </div>
            {% endfor %}
        </div>

        <button type="submit" class="btn">💾 Сохранить блюдо и ТТК</button>
        <a href="/admin" class="btn-back">← Отмена и возврат в дашборд</a>
    </form>
</div>
<script>
function calcTTC(){
    const sellPrice = parseFloat(document.getElementById('sell-price').value) || 0;
    let totalWeight = 0, totalCost = 0;
    document.querySelectorAll('.ttc-inp').forEach(inp => {
        const amt = parseFloat(inp.value) || 0;
        const effCost = parseFloat(inp.dataset.effcost) || 0;
        if(amt > 0){
            totalWeight += amt;
            totalCost += amt * effCost;
        }
    });
    const fc = sellPrice > 0 ? (totalCost / sellPrice * 100) : 0;
    const profit = sellPrice - totalCost;
    document.getElementById('m-weight').innerText = Math.round(totalWeight) + ' ед.';
    document.getElementById('m-cost').innerText = totalCost.toFixed(1) + ' ₽';
    const fcEl = document.getElementById('m-fc');
    fcEl.innerText = fc.toFixed(1) + ' %';
    fcEl.style.color = fc <= 30 ? '#10b981' : (fc <= 37 ? '#f59e0b' : '#ef4444');
    document.getElementById('m-profit').innerText = profit.toFixed(1) + ' ₽';
}
window.onload = calcTTC;
</script></body></html>
```

### ФАЙЛ: templates/history.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>История заказов</title>
<style>
body{font-family:-apple-system,sans-serif;background:#1e1e1e;color:#fff;margin:0;padding:30px}
h1{color:#0a84ff}
a{color:#0a84ff}
table{width:100%;border-collapse:collapse;margin-top:20px}
th,td{padding:12px;text-align:left;border-bottom:1px solid #333}
th{color:#888;font-size:14px}
tr:hover{background:#252525}
.badge{padding:3px 8px;border-radius:5px;font-size:12px;background:#333}
.b-done{background:#30d158;color:#000}
.b-new{background:#ffd60a;color:#000}
.b-cooking{background:#ff9f0a;color:#000}
.b-ready{background:#0a84ff;color:#fff}
</style><link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>
<h1>📜 История заказов</h1>
<a href="/admin">← Назад в админку</a> | <a href="/">В кассу</a>
<table>
<tr><th>ID</th><th>Время</th><th>Сумма</th><th>Клиент</th><th>Тип</th><th>Оплата</th><th>Статус</th><th>Чек</th></tr>
{% for o in orders %}
<tr>
    <td>{{ o.id }}</td>
    <td>{{ o.created_at }}</td>
    <td>{{ o.total }} ₽</td>
    <td>{{ o.phone or '—' }}</td>
    <td>{{ o.delivery_type }}</td>
    <td>{{ o.payment_method }}</td>
    <td><span class="badge b-{{ o.status }}">{{ o.status }}</span></td>
    <td><a href="/receipt/{{ o.id }}" target="_blank">🖨️ Чек</a></td>
</tr>
{% endfor %}
</table>
</body></html>
```

### ФАЙЛ: templates/kitchen.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><title>KDS Кухня ULTRA X2 — Креветка</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
.kds-subbar { background: var(--bg-panel); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.station-filters { display: flex; gap: 8px; flex-wrap: wrap; }
.st-pill { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-main); padding: 10px 18px; border-radius: 10px; font-weight: 900; font-size: 14px; cursor: pointer; }
.st-pill.active { background: var(--accent); color: #fff; border-color: var(--accent); }

/* АГРЕГАТОР ПОРЦИЙ (ЧТО КРУТИТЬ ПРЯМО СЕЙЧАС) */
.batch-strip { background: rgba(255, 107, 0, 0.08); border-bottom: 1px solid var(--border); padding: 10px 20px; display: flex; gap: 10px; align-items: center; overflow-x: auto; }
.batch-item { background: var(--bg-card); border: 1px solid var(--accent); padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 800; white-space: nowrap; }

.kds-grid { padding: 18px 20px; display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; align-items: start; }
.kds-ticket { background: var(--bg-card); border: 2px solid var(--border); border-radius: 14px; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 8px 24px rgba(0,0,0,0.25); }
.kds-ticket.status-new { border-color: var(--blue); }
.kds-ticket.status-cooking { border-color: var(--yellow); }
.kds-ticket.late-order { border-color: var(--red); animation: pulseRed 2s infinite; }
@keyframes pulseRed { 0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.4); } 50% { box-shadow: 0 0 0 8px rgba(239,68,68,0); } }

.ticket-head { padding: 12px 16px; background: var(--bg-panel); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.ticket-body { padding: 12px 16px; flex: 1; }
.dish-line { display: flex; justify-content: space-between; align-items: center; padding: 10px 8px; border-bottom: 1px dashed var(--border); cursor: pointer; border-radius: 8px; transition: 0.1s; }
.dish-line:hover { background: rgba(255,255,255,0.04); }
.dish-line.done-line { opacity: 0.38; text-decoration: line-through; background: rgba(16,185,129,0.08); }
.station-mini { font-size: 10px; font-weight: 900; padding: 2px 6px; border-radius: 4px; margin-right: 6px; }
.s-baked { background: #ef4444; color: #fff; }
.s-tempura { background: #f59e0b; color: #000; }
.s-cold { background: #3b82f6; color: #fff; }
</style>
<link rel="stylesheet" href="/static/ui.css">
</head>
<body>

<div class="ultra-topbar">
    <a href="/" class="ultra-brand"><span>🍳 KDS ЭЛЕКТРОННАЯ КУХНЯ</span><span class="ultra-tag">ULTRA X2</span></a>
    <div class="ultra-nav">
        <a href="/" class="btn btn-ghost">🖥️ Касса</a>
        <a href="/autopilot" class="btn btn-blue">🔪 Утренний чек-лист</a>
        <a href="/warehouse" class="btn btn-purple">📦 Склад и Заготовки</a>
        <a href="/board" target="_blank" class="btn btn-green">📺 ТВ-Табло</a>
        <button onclick="document.body.classList.toggle('light-theme');localStorage.setItem('theme', document.body.classList.contains('light-theme')?'light':'dark')" class="btn btn-ghost">🌓 Тема</button>
    </div>
</div>

<div class="kds-subbar">
    <div class="station-filters">
        <button class="st-pill active" onclick="setStation('all', this)">🍱 Все станции</button>
        <button class="st-pill" onclick="setStation('cold', this)">❄️ Холодный цех (Роллы)</button>
        <button class="st-pill" onclick="setStation('baked', this)">🔥 Запечённые / Гриль</button>
        <button class="st-pill" onclick="setStation('tempura', this)">🍤 Темпура / Фритюр</button>
    </div>
    <div style="display:flex;gap:12px;align-items:center">
        <span style="font-size:14px;font-weight:800">Активных чеков: <b id="active-tickets-cnt" style="color:var(--accent)">0</b></span>
        <button class="btn btn-ghost" style="padding:8px 14px" onclick="playDing()">🔔 Тест звука</button>
    </div>
</div>

<!-- СВОДКА ПОВАРУ: СКОЛЬКО ОДИНАКОВЫХ РОЛЛОВ СЕЙЧАС В РАБОТЕ -->
<div class="batch-strip" id="batch-summary">
    <span style="font-size:12px;font-weight:900;color:var(--accent)">🍣 СВОДКА В РАБОТЕ:</span>
    <span style="font-size:13px;color:var(--text-muted)">Ожидание активных заказов...</span>
</div>

<div class="kds-grid" id="kds-container"></div>

<script>
if(localStorage.getItem('theme') === 'light') document.body.classList.add('light-theme');

let currentStation = 'all';
let checkedItems = JSON.parse(localStorage.getItem('kds_checked_items') || '{}');
let knownOrderIds = new Set();
let firstLoad = true;

function playDing() {
    try {
        let ctx = new (window.AudioContext || window.webkitAudioContext)();
        let osc = ctx.createOscillator();
        let gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.frequency.setValueAtTime(1174, ctx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.25, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
        osc.connect(gain); gain.connect(ctx.destination);
        osc.start(); osc.stop(ctx.currentTime + 0.6);
    } catch(e) {}
}

function detectStation(name) {
    let n = (name || '').toLowerCase();
    if(n.includes('запеч')) return {code: 'baked', label: '🔥 ПЕЧЬ', cls: 's-baked'};
    if(n.includes('темпур') || n.includes('жарен') || n.includes('кляр') || n.includes('фри')) return {code: 'tempura', label: '🍤 ФРИТЮР', cls: 's-tempura'};
    return {code: 'cold', label: '❄️ ХОЛОД', cls: 's-cold'};
}

function setStation(st, btn) {
    currentStation = st;
    document.querySelectorAll('.st-pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadKitchen();
}

function toggleLineDone(key) {
    checkedItems[key] = !checkedItems[key];
    localStorage.setItem('kds_checked_items', JSON.stringify(checkedItems));
    loadKitchen();
}

function loadKitchen() {
    fetch('/api/orders?status=active').then(r=>r.json()).then(data => {
        let orders = Array.isArray(data) ? data : (data.orders || []);
        document.getElementById('active-tickets-cnt').innerText = orders.length;

        // Проверка новых заказов для звукового сигнала
        let hasNew = false;
        orders.forEach(o => {
            if(!knownOrderIds.has(o.id)) {
                knownOrderIds.add(o.id);
                if(!firstLoad) hasNew = true;
            }
        });
        firstLoad = false;
        if(hasNew) playDing();

        // Считаем агрегированную сводку по роллам/блюдам
        let batchTotals = {};
        let html = '';

        orders.forEach(o => {
            let filteredItems = (o.items || []).filter(i => {
                let st = detectStation(i.name);
                return currentStation === 'all' || st.code === currentStation;
            });
            if(filteredItems.length === 0) return;

            let mins = 0;
            if(o.created_at) {
                let dt = new Date(o.created_at.replace(' ', 'T'));
                if(!isNaN(dt)) mins = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 60000));
            }
            let lateCls = mins >= 30 ? 'late-order' : '';
            let stCls = 'status-' + (o.status || 'new');

            let linesHtml = filteredItems.map((i, idx) => {
                let cleanName = i.name.split('[')[0].trim();
                batchTotals[cleanName] = (batchTotals[cleanName] || 0) + i.qty;
                let st = detectStation(i.name);
                let lineKey = `${o.id}_${idx}_${i.name}`;
                let isDone = checkedItems[lineKey] ? 'done-line' : '';
                return `<div class="dish-line ${isDone}" onclick="toggleLineDone('${lineKey.replace(/'/g, "")}')">
                    <div>
                        <span class="station-mini ${st.cls}">${st.label}</span>
                        <b style="font-size:16px">${i.name}</b>
                    </div>
                    <span style="font-size:18px;font-weight:900;color:var(--accent);margin-left:10px">×${i.qty}</span>
                </div>`;
            }).join('');

            let nextStatus = o.status === 'new' ? 'cooking' : 'ready';
            let btnText = o.status === 'new' ? '👨‍🍳 НАЧАТЬ ГОТОВИТЬ' : '✅ ЗАКАЗ ГОТОВ (НА ВЫДАЧУ)';
            let btnColor = o.status === 'new' ? 'btn-yellow' : 'btn-green';

            html += `<div class="kds-ticket ${stCls} ${lateCls}">
                <div class="ticket-head">
                    <div>
                        <span style="font-size:20px;font-weight:900">#${o.id}</span>
                        <span style="margin-left:8px;padding:4px 8px;border-radius:6px;font-size:12px;font-weight:800;background:var(--bg-card)">${(o.delivery_type || 'Доставка').toUpperCase()}</span>
                    </div>
                    <div style="font-size:14px;font-weight:900;color:${mins >= 25 ? 'var(--red)' : 'var(--green)'}">⏱ ${mins} мин.</div>
                </div>
                <div class="ticket-body">
                    ${o.comment ? `<div style="background:rgba(245,158,11,0.15);border:1px solid var(--yellow);color:#fbbf24;padding:8px 10px;border-radius:8px;font-size:13px;font-weight:800;margin-bottom:10px">💬 ${o.comment}</div>` : ''}
                    <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">Нажмите на строку блюда, чтобы вычеркнуть готовую позицию:</div>
                    ${linesHtml}
                </div>
                <div style="padding:12px 16px;background:var(--bg-panel);border-top:1px solid var(--border);display:flex;gap:8px">
                    <button class="btn ${btnColor}" style="flex:1;padding:14px;font-size:15px" onclick="setStatus(${o.id}, '${nextStatus}')">${btnText}</button>
                    <button class="btn btn-ghost" style="padding:14px" onclick="window.open('/receipt/${o.id}', '_blank')" title="Печать бегунка">🖨️</button>
                </div>
            </div>`;
        });

        document.getElementById('kds-container').innerHTML = html || '<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:70px;font-size:18px">На выбранной станции нет активных заказов 🍣</div>';

        // Рендер сводки порций
        let batchEntries = Object.entries(batchTotals);
        if(batchEntries.length > 0) {
            document.getElementById('batch-summary').innerHTML = '<span style="font-size:12px;font-weight:900;color:var(--accent)">🍣 СВОДКА ПОРЦИЙ:</span>' +
                batchEntries.map(([k, v]) => `<span class="batch-item">${k}: <b style="color:var(--accent)">${v} порц.</b></span>`).join('');
        } else {
            document.getElementById('batch-summary').innerHTML = '<span style="font-size:12px;font-weight:900;color:var(--accent)">🍣 СВОДКА ПОРЦИЙ:</span><span style="font-size:13px;color:var(--text-muted)">Свободно</span>';
        }
    });
}

function setStatus(id, st){
    fetch('/api/set_status/' + id, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status: st})})
    .then(r=>r.json()).then(d => { if(d.success) loadKitchen(); });
}

setInterval(loadKitchen, 3000);
loadKitchen();
</script>
</body></html>
```

### ФАЙЛ: templates/login.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script>
<title>Вход в систему — Креветка PRO</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1218;color:#f1f5f9;font-family:sans-serif}
.login-box{background:#171b24;border:1px solid #2a3242;border-radius:18px;padding:35px;width:340px;box-shadow:0 12px 35px rgba(0,0,0,0.4);text-align:center}
h1{margin:0 0 8px;color:#ff7a00;font-size:26px}
p{margin:0 0 22px;color:#94a3b8;font-size:13px}
input{width:100%;box-sizing:border-box;padding:12px 14px;margin-bottom:12px;border-radius:10px;border:1px solid #2a3242;background:#12161f;color:#fff;font-size:15px}
button{width:100%;padding:13px;border:none;border-radius:10px;background:linear-gradient(135deg,#ff8800,#ff5e00);color:#fff;font-size:16px;font-weight:bold;cursor:pointer}
.flash{background:rgba(239,68,68,0.15);border:1px solid #ef4444;color:#ef4444;padding:10px;border-radius:8px;margin-bottom:15px;font-size:13px}
</style><link rel="stylesheet" href="/static/ui.css">
</head><body>
<div class="login-box">
    <h1>🍤 КРЕВЕТКА PRO</h1>
    <p>Авторизация сотрудников</p>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for msg in messages %}<div class="flash">{{ msg }}</div>{% endfor %}
      {% endif %}
    {% endwith %}
    <form method="post" action="/login">
        <input type="text" name="username" placeholder="Логин" required autofocus>
        <input type="password" name="password" placeholder="Пароль" required>
        <button type="submit">Войти в систему</button>
    </form>
</div>
</body></html>
```

### ФАЙЛ: templates/map.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>Карта Инты и Зоны доставки — Креветка</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" />
<link rel="stylesheet" href="/static/pro_style.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
<style>
body{margin:0;padding:20px;height:100vh;box-sizing:border-box;display:flex;flex-direction:column}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}
h1{margin:0;color:var(--accent);font-size:24px}
a{color:var(--accent);text-decoration:none;font-weight:bold}
.container{display:flex;gap:20px;flex:1;min-height:0}
.map-wrapper{flex:2.5;border-radius:18px;overflow:hidden;border:1px solid var(--border);box-shadow:var(--shadow-soft);position:relative}
#map{height:100%;width:100%}
.sidebar{flex:1;padding:20px;overflow-y:auto;max-width:360px;display:flex;flex-direction:column;gap:12px}
h2{margin:0;color:var(--accent);font-size:18px}
.field label{display:block;margin-bottom:5px;color:var(--text-muted);font-size:13px}
.field input{width:100%;box-sizing:border-box;padding:10px}
.btn{background:var(--accent);color:#fff;border:none;padding:11px 15px;cursor:pointer;width:100%;font-size:14px}
.zone-card{background:var(--bg-card);padding:12px 15px;border-radius:12px;margin-bottom:8px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.btn-danger{background:#ef4444;color:#fff;padding:6px 10px;font-size:12px;width:auto;border:none;border-radius:8px;cursor:pointer}
.recenter-btn{position:absolute;top:12px;right:12px;z-index:1000;background:var(--bg-panel);color:var(--text-main);border:1px solid var(--border);padding:8px 14px;border-radius:10px;cursor:pointer;font-weight:bold;box-shadow:0 4px 12px rgba(0,0,0,0.3)}
.recenter-btn:hover{border-color:var(--accent)}
</style>
<script>if(localStorage.getItem('theme') === 'light') document.documentElement.classList.add('light-theme');</script>
<link rel="stylesheet" href="/static/ui.css">
</head><body>

<div class="topbar">
    <h1>🗺️ Карта ({{ brand.brand_city }}) — Зоны доставки и Курьеры</h1>
    <div style="display:flex;gap:15px;align-items:center">
        <a href="/admin">← В дашборд</a>
        <a href="/">В кассу</a>
    </div>
</div>

<div class="container">
    <div class="map-wrapper">
        <button class="recenter-btn" onclick="centerInta()">📍 Центр ({{ brand.brand_city }})</button>
        <div id="map"></div>
    </div>
    <div class="sidebar">
        <h2>➕ Новая зона доставки</h2>
        <p style="font-size:12px;color:var(--text-muted);margin:0;line-height:1.4">Нажмите на значок многоугольника ⬠ слева на карте, обведите район Инты (например: Центр, Южный, Восточный, Станция) и замкните контур.</p>
        <div class="field"><label>Название района / зоны</label><input type="text" id="z-name" placeholder="Напр.: Центр / Заречный"></div>
        <div class="field"><label>Стоимость доставки (₽)</label><input type="number" id="z-price" placeholder="Напр.: 100"></div>
        <button class="btn" style="background:#10b981" onclick="saveZone()">💾 Сохранить зону</button>
        <hr style="border:none;border-top:1px solid var(--border);margin:8px 0">
        <h2>📌 Активные зоны</h2>
        <div id="zones-list" style="flex:1;overflow-y:auto"></div>
<script>
function loadDeliveryRoute(){
    fetch('/api/delivery_route').then(r=>r.json()).then(points => {
        if(points.length === 0) return alert('Нет активных заказов для построения маршрута!');
        let latlngs = [[66.0350, 60.1450]]; // Стартовая точка (ресторан)
        points.forEach(p => {
            latlngs.push([p.lat, p.lng]);
            L.marker([p.lat, p.lng]).addTo(map)
              .bindPopup(`<b>Заказ #${p.id}</b><br>Адрес: ${p.address}<br>Сумма: ${p.total} ₽`);
        });
        latlngs.push([66.0350, 60.1450]); // Возврат в ресторан
        let polyline = L.polyline(latlngs, {color: '#10b981', weight: 4, dashArray: '8, 8'}).addTo(map);
        map.fitBounds(polyline.getBounds());
    });
}
</script>
<button class="btn" style="background:#10b981;margin-top:10px" onclick="loadDeliveryRoute()">🚗 Построить оптимальный маршрут курьеру</button>

    </div>
</div>

<script>
// КООРДИНАТЫ ГОРОДА ИНТА (Республика Коми)
const INTA_COORDS = [{{ brand.map_lat }}, {{ brand.map_lng }}];
const INTA_ZOOM = 13;

let map = L.map('map').setView(INTA_COORDS, INTA_ZOOM);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap | г. Инта'
}).addTo(map);

function centerInta() {
    map.setView(INTA_COORDS, INTA_ZOOM);
}

let drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);
let currentPolygonData = null;

let drawControl = new L.Control.Draw({
    draw: {
        polygon: { shapeOptions: { color: '#ff7a00', fillColor: '#ff7a00', fillOpacity: 0.28 } },
        polyline: false, rect: false, circle: false, marker: false, circlemarker: false
    },
    edit: { featureGroup: drawnItems, remove: false }
});
map.addControl(drawControl);

map.on(L.Draw.Event.CREATED, function (e) {
    drawnItems.clearLayers();
    drawnItems.addLayer(e.layer);
    let latlngs = e.layer.getLatLngs()[0];
    currentPolygonData = JSON.stringify(latlngs.map(p => [p.lat, p.lng]));
    document.getElementById('z-name').focus();
});

function loadZones() {
    fetch('/api/zones/full').then(r=>r.json()).then(data => {
        const list = document.getElementById('zones-list');
        list.innerHTML = '';
        map.eachLayer((layer) => {
            if(layer instanceof L.Polygon && !drawnItems.hasLayer(layer)) map.removeLayer(layer);
        });
        if(data.length === 0) {
            list.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Зоны еще не созданы</div>';
        }
        data.forEach(z => {
            if(z.polygon_data) {
                try {
                    let poly = L.polygon(JSON.parse(z.polygon_data), { color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.22 }).addTo(map);
                    poly.bindPopup(`<b>${z.name}</b><br>Доставка: ${z.price} ₽`);
                } catch(e) {}
            }
            const div = document.createElement('div');
            div.className = 'zone-card';
            div.innerHTML = `<div><b>${z.name}</b><br><span style="color:var(--accent);font-weight:bold">${z.price} ₽</span></div><button class="btn-danger" onclick="deleteZone(${z.id})">✖</button>`;
            list.appendChild(div);
        });
    });
}

function saveZone() {
    const name = document.getElementById('z-name').value.trim();
    const price = document.getElementById('z-price').value;
    if(!name || !price) return alert('Укажите название района и стоимость!');
    if(!currentPolygonData) return alert('Сначала обведите зону на карте Инты!');
    fetch('/api/zones', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, price: price, polygon_data: currentPolygonData})
    }).then(r=>r.json()).then(d=>{
        if(d.success) {
            drawnItems.clearLayers();
            currentPolygonData = null;
            document.getElementById('z-name').value = '';
            document.getElementById('z-price').value = '';
            loadZones();
        }
    });
}
function deleteZone(id) {
    if(!confirm('Удалить эту зону доставки?')) return;
    fetch('/api/zones/delete/' + id, {method: 'POST'}).then(()=>loadZones());
}

let courierMarkers = {};
function loadCouriers() {
    fetch('/api/couriers/locations').then(r=>r.json()).then(data => {
        data.forEach(c => {
            if(courierMarkers[c.username]) {
                courierMarkers[c.username].setLatLng([c.lat, c.lng]);
                courierMarkers[c.username].getPopup().setContent(`🛵 <b>${c.username}</b><br>Обновлено: ${c.updated_at}`);
            } else {
                courierMarkers[c.username] = L.marker([c.lat, c.lng]).addTo(map)
                    .bindPopup(`🛵 Курьер: <b>${c.username}</b><br>Обновлено: ${c.updated_at}`);
            }
        });
    });
}

loadZones();
setInterval(loadCouriers, 5000);
loadCouriers();
</script>
</body></html>
```

### ФАЙЛ: templates/orders.html
```html
<!DOCTYPE html>
<html lang="ru">
<head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Все заказы — Креветка</title>
<style>
:root {
    --bg-main: #0a0a0a; --bg-panel: #151515; --bg-card: #151515; --bg-input: #0a0a0a;
    --text-main: #ffffff; --text-muted: #888888; --border: #333333;
    --accent: #ff7a00; --accent-text: #000000; --btn-grey: #333333;
}
body.light-theme {
    --bg-main: #e9ecef; --bg-panel: #ffffff; --bg-card: #ffffff; --bg-input: #f8f9fa;
    --text-main: #212529; --text-muted: #6c757d; --border: #ced4da;
    --accent: #ff7a00; --accent-text: #ffffff; --btn-grey: #dee2e6;
}
body{font-family:-apple-system,sans-serif;background:var(--bg-main);color:var(--text-main);margin:0;padding:20px; transition: background 0.3s, color 0.3s;}
h1{color:var(--accent);margin-bottom:20px}
a{color:var(--accent);text-decoration:none}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.stats-panel{display:flex; gap:20px; margin-bottom:20px;}
.stat-box{background:var(--bg-panel); padding:15px 25px; border-radius:12px; border:1px solid var(--border); box-shadow: 0 2px 5px rgba(0,0,0,0.05);}
.stat-box h4{margin:0; color:var(--text-muted); font-size:12px; text-transform:uppercase;}
.stat-box p{margin:5px 0 0; font-size:22px; font-weight:bold; color:#30d158;}
.filters{display:flex; gap:10px; margin-bottom:20px; background:var(--bg-panel); padding:15px; border-radius:12px; border:1px solid var(--border); flex-wrap:wrap; align-items:center;}
.filters input, .filters select {background:var(--bg-input); color:var(--text-main); border:1px solid var(--border); padding:8px 12px; border-radius:8px; font-size:14px; outline:none;}
.filters button {background:var(--accent); color:var(--accent-text); border:none; padding:8px 15px; border-radius:8px; font-weight:bold; cursor:pointer;}
.orders-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}
.order-card{background:var(--bg-card);border-radius:15px;padding:15px;border:2px solid var(--border);transition:0.2s; position:relative; box-shadow: 0 2px 5px rgba(0,0,0,0.05);}
.order-card:hover{border-color:var(--text-muted)}
.order-card.new{border-left-color:#ffd60a; border-left-width:4px;}
.order-card.cooking{border-left-color:var(--accent); border-left-width:4px;}
.order-card.ready{border-left-color:#30d158; border-left-width:4px;}
.order-card.delivering{border-left-color:#af52de; border-left-width:4px;}
.order-card.done{border-color:var(--border); opacity:0.6}
.order-card.cancelled{border-color:#ff453a; opacity:0.6}
.order-header{display:flex;justify-content:space-between;border-bottom:1px solid var(--border);padding-bottom:8px;margin-bottom:8px}
.order-id{font-size:20px;font-weight:bold;color:var(--accent)}
.order-time{color:var(--text-muted);font-size:13px}
.order-items{list-style:none;padding:0;margin:0 0 10px}
.order-items li{padding:4px 0;font-size:14px; display:flex; justify-content:space-between;}
.info{color:var(--text-muted);font-size:13px;margin-bottom:10px;line-height:1.4;}
.info b{color:var(--text-main);}
.source-badge{position:absolute; top:15px; right:15px; background:var(--btn-grey); padding:3px 8px; border-radius:5px; font-size:11px; color:var(--text-main);}
.btn{width:100%;border:none;padding:10px;border-radius:8px;font-size:14px;font-weight:bold;cursor:pointer;margin-top:5px;background:#30d158;color:#000}
.btn-cancel{background:#ff453a;color:#fff}.btn-view{background:var(--btn-grey);color:var(--text-main);margin-bottom:5px; border:1px solid var(--border);}
.btn-print{background:#0a84ff;color:#fff;margin-bottom:5px}
.btn-edit{background:#ffd60a;color:#000;margin-bottom:5px;}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:none;align-items:center;justify-content:center;z-index:100}
.modal-content{background:var(--bg-panel);padding:25px;border-radius:15px;width:600px;max-width:90%;max-height:90vh;overflow-y:auto;border:1px solid var(--border); box-shadow: 0 10px 30px rgba(0,0,0,0.2);}
.modal-header{display:flex;justify-content:space-between;border-bottom:1px solid var(--border);padding-bottom:15px;margin-bottom:15px}
.modal-header h2{margin:0;color:var(--accent)}.close-btn{background:none;border:none;color:var(--text-muted);font-size:24px;cursor:pointer}
.modal-body p{margin:8px 0;line-height:1.5}.modal-body ul{list-style:none;padding:0}.modal-body li{padding:5px 0;border-bottom:1px solid var(--border)}
.theme-btn{background:var(--bg-card);color:var(--text-main);border:1px solid var(--border);padding:6px 10px;border-radius:8px;cursor:pointer;font-size:16px;}
/* Стили для редактирования */
.edit-item-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; padding: 8px; background: var(--bg-input); border-radius: 8px; border: 1px solid var(--border);}
.edit-item-row input { width: 50px; text-align: center; background: var(--bg-main); color: var(--text-main); border: 1px solid var(--border); border-radius: 5px; padding: 4px;}
.add-item-select { width: 100%; padding: 10px; margin-top: 10px; background: var(--bg-input); color: var(--text-main); border: 1px solid var(--border); border-radius: 8px;}
</style>
<script>
    if(localStorage.getItem('theme') === 'light') { document.documentElement.classList.add('light-theme'); }
</script>
<link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head>
<body>
<div class="top-bar">
    <h1>📋 Все заказы</h1>
    <div style="display:flex; gap:15px; align-items:center;">
        <a href="/" style="font-weight:bold">← Назад в кассу</a>
        <button class="theme-btn" onclick="toggleTheme()" id="theme-btn">🌙</button>
    </div>
</div>

<div class="stats-panel" id="stats-panel">
    <div class="stat-box"><h4>Заказов</h4><p id="stat-count">0</p></div>
    <div class="stat-box"><h4>Выручка</h4><p id="stat-total">0 ₽</p></div>
    <div class="stat-box"><h4>Средний чек</h4><p id="stat-avg">0 ₽</p></div>
</div>

<div class="filters">
    <input type="date" id="f-date" value="" onchange="fetchOrders()">
    <select id="f-cashier" onchange="fetchOrders()">
        <option value="">Все сотрудники</option>
        {% for u in users %}{% if u.id != 1 %}<option value="{{ u.id }}">{{ u.username }}</option>{% endif %}{% endfor %}
    </select>
    <select id="f-source" onchange="fetchOrders()">
        <option value="">Все источники</option>
        <option value="Касса">Касса</option>
        <option value="Сайт">Сайт</option>
    </select>
    <button onclick="setToday()">Сегодня</button>
</div>

<div class="orders-grid" id="orders-container"></div>

<!-- МОДАЛЬНОЕ ОКНО ПРОСМОТРА -->
<div class="modal-overlay" id="viewModal">
    <div class="modal-content">
        <div class="modal-header"><h2 id="m-id">Заказ #</h2><button class="close-btn" onclick="closeModal()">×</button></div>
        <div class="modal-body" id="m-body"></div>
        <div id="m-actions"></div>
    </div>
</div>

<!-- МОДАЛЬНОЕ ОКНО РЕДАКТИРОВАНИЯ -->
<div class="modal-overlay" id="editModal">
    <div class="modal-content">
        <div class="modal-header"><h2 id="edit-title">✏️ Редактирование заказа</h2><button class="close-btn" onclick="closeEditModal()">×</button></div>
        <div id="edit-items-list" style="margin-bottom:15px;"></div>
        
        <h3 style="margin-top:0; font-size:16px;">Добавить блюдо:</h3>
        <select class="add-item-select" id="add-menu-item" onchange="addNewItem()">
            <option value="">-- Выберите блюдо для добавления --</option>
            {% for m in menu %}
                <option value="{{ m.id }}" data-name="{{ m.name }}" data-price="{{ m.price }}">{{ m.name }} ({{ m.price }} ₽)</option>
            {% endfor %}
        </select>

        <div style="text-align:right; margin-top:20px; font-size:20px; font-weight:bold;">
            Итого: <span id="edit-total" style="color:#30d158;">0 ₽</span>
        </div>
        <button class="btn" style="background:#30d158; font-size:16px; padding:12px;" onclick="saveEditedOrder()">💾 Сохранить изменения</button>
    </div>
</div>

<script>
function toggleTheme() {
    document.body.classList.toggle('light-theme');
    const isLight = document.body.classList.contains('light-theme');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    document.getElementById('theme-btn').innerText = isLight ? '🌙' : '☀️';
}
document.addEventListener('DOMContentLoaded', () => {
    if(localStorage.getItem('theme') === 'light') { document.body.classList.add('light-theme'); document.getElementById('theme-btn').innerText = '🌙'; } 
    else { document.getElementById('theme-btn').innerText = '☀️'; }
});

let currentOrders = [];
const labels = {new:'🟡 Новый', cooking:'🟠 Готовится', ready:'🟢 Готов', delivering:'🟣 В пути', done:'✅ Выдан', cancelled:'❌ Отменен'};

function setToday(){const today = new Date().toISOString().split('T')[0];document.getElementById('f-date').value = today;fetchOrders();}
function fetchOrders(){
    const date = document.getElementById('f-date').value;
    const cashier = document.getElementById('f-cashier').value;
    const source = document.getElementById('f-source').value;
    let url = `/api/all_orders?date=${date}`;
    if(cashier) url += `&cashier_id=${cashier}`;
    if(source) url += `&source=${source}`;
    fetch(url).then(r=>r.json()).then(data=>{
        currentOrders = data.orders;
        render(data.orders);
        document.getElementById('stat-count').innerText = data.stats.count;
        document.getElementById('stat-total').innerText = data.stats.total + ' ₽';
        document.getElementById('stat-avg').innerText = data.stats.avg + ' ₽';
    });
}

function render(orders){
  const c = document.getElementById('orders-container'); c.innerHTML = '';
  if(orders.length === 0){ c.innerHTML = '<div style="color:var(--text-muted);font-size:20px;grid-column:1/-1;text-align:center;margin-top:50px">Заказов за этот день нет</div>'; return; }
  orders.forEach(o => {
    const card = document.createElement('div'); card.className = 'order-card ' + o.status;
    const items = o.items.map(i => `<li><span>${i.name}</span><b>x${i.qty}</b></li>`).join('');
    card.innerHTML = `
      <span class="source-badge">${o.source}</span>
      <div class="order-header"><span class="order-id">#${o.id}</span><span class="order-time">${o.created_at.slice(11,16)}</span></div>
      <ul class="order-items">${items}</ul>
      <div class="info">
        <div>💰 Сумма: <b>${o.total} ₽</b> | 💳 ${o.payment_method}</div>
        <div>👤 Кассир: <b>${o.cashier_name || 'Неизвестно'}</b></div>
        ${o.phone ? `<div>📞 ${o.phone}</div>` : ''}
        ${o.comment ? `<div>💬 ${o.comment}</div>` : ''}
      </div>
      <button class="btn btn-view" onclick="viewOrder(${o.id})">👁️ Подробнее</button>
      ${o.status !== 'done' && o.status !== 'cancelled' ? `<button class="btn btn-edit" onclick="openEditModal(${o.id})">✏️ Редактировать</button>` : ''}
      <a href="/receipt/${o.id}" target="_blank" class="btn btn-print" style="display:block;text-align:center;text-decoration:none;">🖨️ Печать чека</a>
      ${o.status !== 'done' && o.status !== 'cancelled' ? `<button class="btn btn-cancel" onclick="cancelOrder(${o.id})">❌ Отменить</button>` : ''}
    `;
    c.appendChild(card);
  });
}

function viewOrder(id){
  const o = currentOrders.find(x => x.id === id); if(!o) return;
  document.getElementById('m-id').innerText = 'Заказ #' + o.id;
  const itemsHtml = o.items.map(i => `<li style="display:flex;justify-content:space-between"><span>${i.name} × ${i.qty}</span><span>${i.price * i.qty} ₽</span></li>`).join('');
  document.getElementById('m-body').innerHTML = `
    <p><b>Статус:</b> ${labels[o.status] || o.status}</p>
    <p><b>Источник:</b> ${o.source} (${o.cashier_name || 'Без кассира'})</p>
    <p><b>Создан:</b> ${o.created_at}</p>
    <hr style="border-color:var(--border); margin:10px 0">
    <ul>${itemsHtml}</ul>
    <hr style="border-color:var(--border); margin:10px 0">
    <p style="font-size:20px;font-weight:bold;text-align:right">Итого: ${o.total} ₽</p>
    <p><b>Оплата:</b> ${o.payment_method}</p>
    <p><b>Тип:</b> ${o.delivery_type === 'самовывоз' ? '🏃 Самовывоз' : '🛵 Доставка'}</p>
    ${o.address ? `<p><b>Адрес:</b> ${o.address}</p>` : ''}
    ${o.phone ? `<p><b>Телефон:</b> ${o.phone}</p>` : ''}
    ${o.comment ? `<p><b>Комментарий:</b> ${o.comment}</p>` : ''}
  `;
  document.getElementById('viewModal').style.display = 'flex';
}

function closeModal(){document.getElementById('viewModal').style.display = 'none';}

function cancelOrder(id){if(!confirm('Вы уверены, что хотите отменить заказ?')) return;fetch('/api/set_status/'+id, {method: 'POST', headers: {'Content-Type': 'application/json'},body: JSON.stringify({status: 'cancelled'})}).then(()=>fetchOrders());}

// --- ЛОГИКА РЕДАКТИРОВАНИЯ ---
let editOrderId = null;
let editCart = [];

function openEditModal(id) {
    const o = currentOrders.find(x => x.id === id); if(!o) return;
    editOrderId = id;
    // Копируем текущие позиции в editCart
    editCart = o.items.map(i => ({ id: i.menu_id, name: i.name, price: i.price, qty: i.qty }));
    
    document.getElementById('edit-title').innerText = '✏️ Редактирование заказа #' + id;
    document.getElementById('editModal').style.display = 'flex';
    renderEditCart();
}

function closeEditModal(){ document.getElementById('editModal').style.display = 'none'; }

function renderEditCart() {
    const container = document.getElementById('edit-items-list');
    container.innerHTML = '';
    let total = 0;
    
    editCart.forEach((it, idx) => {
        total += it.price * it.qty;
        const div = document.createElement('div');
        div.className = 'edit-item-row';
        div.innerHTML = `
            <span>${it.name}</span>
            <div style="display:flex; align-items:center; gap:10px;">
                <input type="number" min="1" value="${it.qty}" onchange="changeEditQty(${idx}, this.value)">
                <span style="width: 60px; text-align:right; font-weight:bold;">${it.price * it.qty} ₽</span>
                <button onclick="removeEditItem(${idx})" style="background:none; border:none; color:#ff453a; cursor:pointer; font-size:16px;">✖</button>
            </div>
        `;
        container.appendChild(div);
    });
    
    document.getElementById('edit-total').innerText = total + ' ₽';
}

function changeEditQty(idx, val) {
    editCart[idx].qty = Math.max(1, parseInt(val) || 1);
    renderEditCart();
}

function removeEditItem(idx) {
    editCart.splice(idx, 1);
    renderEditCart();
}

function addNewItem() {
    const sel = document.getElementById('add-menu-item');
    const id = sel.value;
    if (!id) return;
    const name = sel.options[sel.selectedIndex].dataset.name;
    const price = parseInt(sel.options[sel.selectedIndex].dataset.price);
    
    const ex = editCart.find(i => i.id == id);
    if (ex) ex.qty++;
    else editCart.push({ id: id, name: name, price: price, qty: 1 });
    
    sel.value = ''; // Сброс селекта
    renderEditCart();
}

function saveEditedOrder() {
    if (editCart.length === 0) return alert('В заказе должна остаться хотя бы одна позиция!');
    
    fetch('/api/order/update_items/' + editOrderId, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ items: editCart })
    }).then(r=>r.json()).then(d=>{
        if(d.success) {
            alert('Заказ успешно обновлен! Новая сумма: ' + d.new_total + ' ₽');
            closeEditModal();
            fetchOrders(); // Обновляем список
        } else {
            alert('Ошибка: ' + (d.error || 'Не удалось сохранить'));
        }
    });
}

document.addEventListener("DOMContentLoaded", function() { setToday(); });
</script>
</body>
</html>
```

### ФАЙЛ: templates/public_site.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>КРЕВЕТКА — Ресторан доставки роллов, WOK и супов в Инте</title>
<link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="/static/zones_inta.js"></script>
<style>
.site-hero { background: linear-gradient(135deg, #131b2e 0%, #24142c 100%); border-bottom: 1px solid var(--border); padding: 24px 18px; text-align: center; }
.cats-nav { max-width: 1280px; margin: 14px auto 0 auto; padding: 0 18px; display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; }
.cats-nav::-webkit-scrollbar { display: none; }
.cat-tab { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-main); padding: 10px 18px; border-radius: 10px; font-weight: 800; font-size: 14px; cursor: pointer; white-space: nowrap; }
.cat-tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }

.site-grid { max-width: 1280px; margin: 0 auto; padding: 18px; display: grid; grid-template-columns: repeat(auto-fill, minmax(255px, 1fr)); gap: 18px; }
.site-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; display: flex; flex-direction: column; transition: 0.15s; box-shadow: 0 8px 20px rgba(0,0,0,0.2); }
.site-card:hover { transform: translateY(-3px); border-color: var(--accent); }
.card-img-wrap { width: 100%; height: 185px; overflow: hidden; position: relative; background: #101520; }
.card-img-wrap img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.3s; }
.site-card:hover .card-img-wrap img { transform: scale(1.05); }
.card-cat-badge { position: absolute; top: 10px; left: 10px; background: rgba(11,15,23,0.85); color: var(--accent); padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: 900; backdrop-filter: blur(4px); }
.card-body { padding: 14px 16px; display: flex; flex-direction: column; flex: 1; }

/* СЕКЦИЯ ИНТЕРАКТИВНОЙ КАРТЫ ЗОН ИНТЫ */
.map-section { max-width: 1280px; margin: 10px auto 30px auto; padding: 0 18px; }
.map-box { background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; padding: 18px; }
#inta-map { width: 100%; height: 380px; border-radius: 12px; border: 1px solid var(--border); margin-top: 12px; z-index: 10; }
.zone-legend { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.legend-pill { display: flex; align-items: center; gap: 8px; background: var(--bg-panel); border: 1px solid var(--border); padding: 8px 14px; border-radius: 10px; font-size: 13px; font-weight: 800; cursor: pointer; }
.legend-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }

.drawer-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.75); display: none; justify-content: flex-end; z-index: 500; }
.drawer-box { width: 100%; max-width: 500px; background: var(--bg-card); height: 100%; display: flex; flex-direction: column; padding: 18px; overflow-y: auto; }
.zone-chip { flex: 1; padding: 8px 4px; font-size: 11px; font-weight: 800; border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-main); border-radius: 8px; cursor: pointer; text-align: center; }
.zone-chip.active { background: var(--purple); color: #fff; border-color: var(--purple); }
.pay-chip { flex: 1; padding: 10px 6px; font-size: 13px; font-weight: 900; border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-main); border-radius: 8px; cursor: pointer; text-align: center; }
.pay-chip.active { background: var(--accent); color: #fff; border-color: var(--accent); }
</style>
</head>
<body>
<div class="pro-topbar">
    <div class="pro-brand"><span>🦐 КРЕВЕТКА</span><span class="pro-badge">РОЛЛЫ • WOK • СУПЫ</span></div>
    <div style="display:flex;gap:10px;align-items:center">
        <div id="my-last-order-link"></div>
        <a href="#delivery-map-block" class="btn btn-ghost">🗺️ Зоны Инты</a>
        <button class="btn" onclick="openCartDrawer()">🛒 Корзина (<span id="site-cart-cnt">0</span>)</button>
    </div>
</div>

<div class="site-hero">
    <h1 style="margin:0 0 8px 0;font-size:26px">Ресторан доставки «КРЕВЕТКА» в Инте</h1>
    <div style="font-size:14px;color:var(--text-muted)">Авторские роллы (8 кусочков), горячий WOK и насыщенные азиатские супы</div>
</div>

<div class="cats-nav">
    <button class="cat-tab active" onclick="filterSiteCat('all', this)">🍱 Все блюда</button>
    {% for c in categories %}
    <button class="cat-tab" onclick="filterSiteCat('{{ c.category }}', this)">{{ c.category }}</button>
    {% endfor %}
</div>

<div class="site-grid" id="site-menu-grid">
    {% for m in menu %}
    {% set raw_img = m.image_url or m.image or m.photo or '' %}
    <div class="site-card" data-cat="{{ m.category }}">
        <div class="card-img-wrap">
            <img class="dish-auto-img" data-name="{{ m.name }}" data-cat="{{ m.category }}" data-dbimg="{{ raw_img }}" src="{{ raw_img }}" alt="{{ m.name }}">
            <span class="card-cat-badge">{{ m.category }}</span>
        </div>
        <div class="card-body">
            <div style="font-size:17px;font-weight:900;margin-bottom:6px;line-height:1.3">{{ m.name }}</div>
            {% if m.description %}
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;flex:1">{{ m.description }}</div>
            {% else %}
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;flex:1">Свежее приготовление из-под ножа</div>
            {% endif %}
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:8px;border-top:1px solid var(--border)">
                <span style="font-size:20px;font-weight:900;color:var(--accent)">{{ m.price }} ₽</span>
                <button class="btn" onclick="siteAdd({{ m.id }}, '{{ m.name }}', {{ m.price }})">+ В корзину</button>
            </div>
        </div>
    </div>
    {% endfor %}
</div>

<!-- ИНТЕРАКТИВНАЯ КАРТА ЗОН ДОСТАВКИ ИНТЫ И ПОСЕЛКОВ -->
<div class="map-section" id="delivery-map-block">
    <div class="map-box">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
            <div>
                <h2 style="margin:0;font-size:20px">🗺️ Карта зон доставки по Инте и посёлкам</h2>
                <div style="font-size:13px;color:var(--text-muted);margin-top:2px">Нажмите на свой район на карте, чтобы автоматически применить тариф доставки к заказу</div>
            </div>
            <span id="selected-map-zone-badge" style="background:var(--bg-panel);border:1px solid var(--accent);color:var(--accent);padding:6px 12px;border-radius:8px;font-weight:900;font-size:13px">Выбрано: Центр (0 ₽)</span>
        </div>
        <div class="zone-legend">
            <div class="legend-pill" onclick="focusIntaZone('center')"><span class="legend-dot" style="background:#10b981"></span> Центр Инты — 0 ₽</div>
            <div class="legend-pill" onclick="focusIntaZone('zapad')"><span class="legend-dot" style="background:#3b82f6"></span> Западный посёлок — 150 ₽</div>
            <div class="legend-pill" onclick="focusIntaZone('yug')"><span class="legend-dot" style="background:#f59e0b"></span> Южный посёлок — 250 ₽</div>
            <div class="legend-pill" onclick="focusIntaZone('verh')"><span class="legend-dot" style="background:#ef4444"></span> Верхняя Инта — 1000 ₽</div>
        </div>
        <div id="inta-map"></div>
    </div>
</div>

<!-- ВЫЕЗЖАЮЩАЯ КОРЗИНА -->
<div class="drawer-backdrop" id="cart-drawer">
    <div class="drawer-box">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
            <h2 style="margin:0;font-size:20px">🛒 Ваш заказ в «КРЕВЕТКА»</h2>
            <button class="btn btn-ghost" onclick="closeCartDrawer()">✕</button>
        </div>
        <div id="site-cart-items" style="margin-bottom:14px"></div>

        <div style="background:var(--bg-panel);padding:12px;border-radius:12px;border:1px solid var(--border);margin-bottom:12px">
            <input type="tel" id="s-phone" placeholder="📞 Ваш телефон *" style="width:100%;margin-bottom:8px;font-weight:700">
            <select id="s-del-type" onchange="siteDelTypeChanged()" style="width:100%;margin-bottom:8px;font-weight:800">
                <option value="самовывоз">🏃 Самовывоз (0 ₽)</option>
                <option value="доставка">🚗 Доставка курьером</option>
            </select>

            <div style="font-size:11px;font-weight:800;color:var(--text-muted);margin-bottom:6px">📍 АДРЕС (ДОСТАВКА И РАЙОН ВКЛЮЧАТСЯ АВТОМАТИЧЕСКИ):</div>
            <input type="text" id="s-address" list="site-inta-streets" placeholder="🏠 Улица, дом, квартира..." oninput="siteAddressTyped(this.value)" style="width:100%;margin-bottom:8px">
            <datalist id="site-inta-streets">
                <option value="Центр, ул. Горького, д. "><option value="Центр, ул. Мира, д. "><option value="Центр, ул. Куратова, д. ">
                <option value="Западный, ул. Бабушкина, д. "><option value="Западный, ул. Чайковского, д. ">
                <option value="Южный, ул. Морозова, д. "><option value="Южный, ул. Лунина, д. ">
                <option value="Верхняя Инта, ул. Вокзальная, д. "><option value="Верхняя Инта, ул. Станционная, д. ">
            </datalist>
            <div style="display:flex;gap:4px;margin-bottom:8px">
                <div class="zone-chip" id="sz-center" onclick="siteSelectZone('center')">Центр 0₽</div>
                <div class="zone-chip" id="sz-zapad" onclick="siteSelectZone('zapad')">Западный 150₽</div>
                <div class="zone-chip" id="sz-yug" onclick="siteSelectZone('yug')">Южный 250₽</div>
                <div class="zone-chip" id="sz-verh" onclick="siteSelectZone('verh')">В. Инта 1000₽</div>
            </div>
            <input type="text" id="s-comment" placeholder="💬 Комментарий (палочки, домофон, сдача)..." style="width:100%">
        </div>

        <div style="margin-bottom:14px">
            <div style="font-size:12px;font-weight:800;margin-bottom:6px">💳 СПОСОБ ОПЛАТЫ:</div>
            <div style="display:flex;gap:6px">
                <div class="pay-chip active" id="sp-cash" onclick="siteSetPay('cash')">💵 Наличные</div>
                <div class="pay-chip" id="sp-card" onclick="siteSetPay('card')">💳 Картой</div>
                <div class="pay-chip" id="sp-sbp" onclick="siteSetPay('sbp')">📱 СБП</div>
            </div>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:center;font-size:20px;font-weight:900;margin-bottom:14px">
            <span>К оплате:</span>
            <span id="site-total-sum" style="color:var(--accent)">0 ₽</span>
        </div>
        <button class="btn" style="width:100%;padding:16px;font-size:16px" onclick="submitPublicOrder()">✅ ПОДТВЕРДИТЬ ЗАКАЗ</button>
    </div>
</div>

<script>
// Подставляем красивые фото блюд для роллов, WOK и супов
document.querySelectorAll('.dish-auto-img').forEach(img => {
    img.src = window.getDishPhoto(img.dataset.name, img.dataset.cat, img.dataset.dbimg);
    img.onerror = function() {
        this.src = window.getDishPhoto(this.dataset.name, this.dataset.cat, '');
    };
});

function filterSiteCat(cat, btn) {
    document.querySelectorAll('.cat-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.site-card').forEach(c => {
        c.style.display = (cat === 'all' || c.dataset.cat === cat) ? 'flex' : 'none';
    });
}

// ИНИЦИАЛИЗАЦИЯ КАРТЫ ИНТЫ С ОБВЕДЕННЫМИ ПОЛИГОНАМИ ЗОН
let intaMap = L.map('inta-map').setView([66.042, 60.160], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap • КРЕВЕТКА Доставка Инта'
}).addTo(intaMap);

let zonePolygons = {};
Object.keys(window.INTA_ZONES).forEach(key => {
    let z = window.INTA_ZONES[key];
    let poly = L.polygon(z.coords, {
        color: z.color,
        weight: 3,
        fillColor: z.color,
        fillOpacity: 0.28
    }).addTo(intaMap);
    poly.bindTooltip(`<b>${z.name}</b><br>Доставка: ${z.fee} ₽`, {sticky: true});
    poly.on('click', function() {
        siteSelectZone(key);
        document.getElementById('selected-map-zone-badge').innerText = `Выбрано: ${z.name} (${z.fee} ₽)`;
        openCartDrawer();
    });
    zonePolygons[key] = poly;
});

function focusIntaZone(key) {
    let z = window.INTA_ZONES[key];
    if(!z) return;
    intaMap.setView(z.center, 13);
    siteSelectZone(key);
    document.getElementById('selected-map-zone-badge').innerText = `Выбрано: ${z.name} (${z.fee} ₽)`;
}

let sCart = {};
let sPay = 'cash';
let sZone = 'center';
let sFee = 0;

let savedOrderId = localStorage.getItem('last_krevetka_order');
if(savedOrderId) {
    document.getElementById('my-last-order-link').innerHTML = `<a href="/track/${savedOrderId}" class="btn btn-green">📡 Статус заказа #${savedOrderId}</a>`;
}

function openCartDrawer() { document.getElementById('cart-drawer').style.display = 'flex'; renderSiteCart(); }
function closeCartDrawer() { document.getElementById('cart-drawer').style.display = 'none'; }

function siteAdd(id, name, price) {
    if(!sCart[id]) sCart[id] = {id, name, price, qty: 0};
    sCart[id].qty++;
    updateSiteBadge();
}

function updateSiteBadge() {
    let cnt = Object.values(sCart).reduce((acc, i) => acc + i.qty, 0);
    document.getElementById('site-cart-cnt').innerText = cnt;
}

function siteAddressTyped(val) {
    let clean = (val || '').trim();
    if(clean.length > 0) {
        document.getElementById('s-del-type').value = 'доставка';
        let z = window.detectIntaZoneByAddress(clean) || 'center';
        siteApplyZone(z);
    } else {
        document.getElementById('s-del-type').value = 'самовывоз';
        siteDelTypeChanged();
    }
}

function siteSelectZone(zKey) {
    document.getElementById('s-del-type').value = 'доставка';
    let inp = document.getElementById('s-address');
    if(!inp.value.trim()) inp.value = window.INTA_ZONES[zKey].name + ', ул. ';
    siteApplyZone(zKey);
}

function siteApplyZone(zKey) {
    sZone = zKey;
    sFee = window.INTA_ZONES[zKey].fee;
    ['center', 'zapad', 'yug', 'verh'].forEach(k => {
        document.getElementById('sz-' + k).classList.toggle('active', k === zKey);
    });
    document.getElementById('selected-map-zone-badge').innerText = `Выбрано: ${window.INTA_ZONES[zKey].name} (${sFee} ₽)`;
    renderSiteCart();
}

function siteDelTypeChanged() {
    if(document.getElementById('s-del-type').value === 'самовывоз') {
        sFee = 0;
        ['center', 'zapad', 'yug', 'verh'].forEach(k => document.getElementById('sz-' + k).classList.remove('active'));
    } else {
        siteApplyZone(window.detectIntaZoneByAddress(document.getElementById('s-address').value) || 'center');
    }
    renderSiteCart();
}

function siteSetPay(m) {
    sPay = m;
    ['cash', 'card', 'sbp'].forEach(k => document.getElementById('sp-' + k).classList.toggle('active', k === m));
}

function renderSiteCart() {
    let sub = 0, html = '';
    for(let id in sCart) {
        let i = sCart[id];
        sub += i.price * i.qty;
        html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)">
            <div><b>${i.name}</b><br><span style="font-size:12px;color:var(--text-muted)">${i.price} ₽ × ${i.qty}</span></div>
            <div style="display:flex;gap:6px;align-items:center">
                <button class="btn btn-red" style="padding:4px 10px" onclick="sCart[${id}].qty--;if(sCart[${id}].qty<=0)delete sCart[${id}];updateSiteBadge();renderSiteCart()">-</button>
                <b>${i.qty}</b>
                <button class="btn btn-green" style="padding:4px 10px" onclick="sCart[${id}].qty++;updateSiteBadge();renderSiteCart()">+</button>
            </div>
        </div>`;
    }
    document.getElementById('site-cart-items').innerHTML = html || '<div style="color:var(--text-muted);text-align:center;padding:20px">Корзина пуста</div>';
    let del = document.getElementById('s-del-type').value;
    let total = sub + (del === 'доставка' ? sFee : 0);
    document.getElementById('site-total-sum').innerText = total + ' ₽' + (del === 'доставка' && sFee > 0 ? ` (дост. +${sFee}₽)` : '');
}

function submitPublicOrder() {
    let items = Object.values(sCart).map(i => ({id: i.id, name: i.name, qty: i.qty, price: i.price}));
    if(!items.length) return alert('Корзина пуста!');
    let phone = document.getElementById('s-phone').value.trim();
    if(!phone) return alert('Укажите ваш номер телефона!');
    let delType = document.getElementById('s-del-type').value;
    let addr = document.getElementById('s-address').value.trim();
    if(addr && delType !== 'доставка') delType = 'доставка';
    if(delType === 'доставка' && !addr) return alert('Укажите адрес доставки!');

    if(delType === 'доставка' && sFee > 0) {
        items.push({id: 99901, name: `Доставка (${window.INTA_ZONES[sZone].name})`, qty: 1, price: sFee});
    }

    fetch('/api/create_order', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            items, phone, delivery_type: delType,
            address: delType === 'доставка' ? addr : 'Самовывоз',
            comment: document.getElementById('s-comment').value.trim(),
            payment_method: sPay
        })
    }).then(r=>r.json()).then(d => {
        if(d.success) {
            localStorage.setItem('last_krevetka_order', d.order_id);
            window.location.href = '/track/' + d.order_id;
        } else {
            alert('Ошибка: ' + (d.error || 'Не удалось отправить заказ'));
        }
    });
}
</script>
</body></html>
```

### ФАЙЛ: templates/rate.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Оцените заказ — Креветка</title>
<style>
body{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#fff;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.box{background:#151515;padding:40px;border-radius:20px;text-align:center;border:1px solid #333;max-width:400px;width:90%}
h1{color:#ff7a00;margin-top:0}
.stars{display:flex;justify-content:center;gap:15px;margin:30px 0;font-size:50px;cursor:pointer;}
.star{color:#333;transition:0.2s;}
.star:hover, .star.active{color:#ffd700;text-shadow:0 0 20px rgba(255,215,0,0.5)}
.btn{background:#ff7a00;color:#000;border:none;padding:15px 40px;border-radius:10px;font-size:18px;font-weight:bold;cursor:pointer;margin-top:20px;}
</style><link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>
<div class="box">
    <h1>Оцените заказ!</h1>
    <p style="color:#888">Заказ #{{ order.id }} на сумму {{ order.total }} ₽</p>
    <form method="POST" id="rateForm">
        <input type="hidden" name="rating" id="ratingInput" value="5">
        <div class="stars">
            <span class="star" onclick="setRating(1)">★</span>
            <span class="star" onclick="setRating(2)">★</span>
            <span class="star" onclick="setRating(3)">★</span>
            <span class="star" onclick="setRating(4)">★</span>
            <span class="star active" onclick="setRating(5)">★</span>
        </div>
        <button type="submit" class="btn">Отправить</button>
    </form>
</div>
<script>
function setRating(val){
    document.getElementById('ratingInput').value = val;
    const stars = document.querySelectorAll('.star');
    stars.forEach((s, i) => {
        if(i < val) s.classList.add('active');
        else s.classList.remove('active');
    });
}
</script>
</body></html>
```

### ФАЙЛ: templates/receipt.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Чек #{{ order.id }}</title>
<style>
body { font-family: 'Courier New', monospace; width: 300px; margin: 0 auto; padding: 10px; color: #000; background: #fff; font-size: 13px; }
.title { text-align: center; font-weight: 900; font-size: 18px; margin-bottom: 4px; }
.sub { text-align: center; font-size: 12px; margin-bottom: 8px; border-bottom: 2px dashed #000; padding-bottom: 6px; }
.big-box { border: 2px solid #000; padding: 6px; margin: 8px 0; font-weight: 900; font-size: 14px; }
.item-line { display: flex; justify-content: space-between; margin: 4px 0; font-weight: 700; }
.total-line { border-top: 2px solid #000; border-bottom: 2px solid #000; padding: 6px 0; margin: 8px 0; font-size: 17px; font-weight: 900; display: flex; justify-content: space-between; }
.packer-box { background: #f3f4f6; border: 2px dashed #000; padding: 8px; margin-top: 10px; font-size: 12px; }
@media print { .no-print { display: none; } }
</style>
<link rel="stylesheet" href="/static/ui.css">
</head>
<body onload="window.print()">
<div class="no-print" style="margin-bottom:10px;display:flex;gap:6px">
    <button onclick="window.print()" style="flex:1;padding:8px;font-weight:bold;cursor:pointer">🖨️ Печать</button>
    <button onclick="window.close()" style="padding:8px;cursor:pointer">✕ Закрыть</button>
</div>

<div class="title">🍣 {{ brand.brand_name if brand else 'КРЕВЕТКА' }}</div>
<div class="sub">Заказ #{{ order.id }} • {{ order.created_at }}</div>

<div class="big-box">
    ТИП: {{ (order.delivery_type or 'ДОСТАВКА') | upper }}<br>
    {% if order.phone %}ТЕЛ: {{ order.phone }}<br>{% endif %}
    {% if order.address and order.address != 'Самовывоз' %}АДРЕС: {{ order.address }}{% endif %}
</div>

{% if order.comment %}
<div style="border:1px solid #000;padding:6px;margin-bottom:8px;font-weight:bold">
    📋 ИНФО / КОМПЛЕКТАЦИЯ:<br>{{ order.comment }}
</div>
{% endif %}

<div>
    {% for it in items %}
    <div class="item-line">
        <span>{{ it.name }} ×{{ it.qty }}</span>
        <span>{{ it.price * it.qty }}₽</span>
    </div>
    {% endfor %}
</div>

<div class="total-line">
    <span>ИТОГО ({{ order.payment_method or 'нал' }}):</span>
    <span>{{ order.total }} ₽</span>
</div>

<div class="packer-box">
    <b>☑️ ЧЕК-ЛИСТ СБОРЩИКА ПЕРЕД ОТДАЧЕЙ:</b><br>
    [ ] Проверить палочки, салфетки, зубочистки<br>
    [ ] Проверить соевый соус, имбирь, васаби<br>
    [ ] Запечённые/темпура упакованы в фольгу
</div>
</body></html>
```

### ФАЙЛ: templates/reports.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8"><title>Отчёты</title>
<style>
body{font-family:-apple-system,sans-serif;background:#121212;color:#fff;margin:0;padding:30px}
h1{color:#0a84ff}table{width:100%;border-collapse:collapse;margin-top:20px}
th,td{padding:15px;text-align:left;border-bottom:1px solid #333}th{color:#888}
a{color:#0a84ff;text-decoration:none}
</style><link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="/static/ui.css">
</head><body>
<h1>📊 Z-Отчеты</h1><a href="/admin">← Назад</a>
<table>
<tr><th>Смена</th><th>Открыта</th><th>Закрыта</th><th>Выручка</th><th>Нал</th><th>Карта</th><th>Размен/инкассация</th><th>В кассе</th><th>Ожидаемо</th><th>Факт</th><th>Расхождение</th></tr>
{% for s in shifts %}
<tr><td>#{{ s.id }}</td><td>{{ s.opened_at }}</td><td>{{ s.closed_at or '—' }}</td>
<td style="color:#30d158;font-weight:bold">{{ s.total_revenue }} ₽</td><td>{{ s.total_cash }} ₽</td><td>{{ s.total_card }} ₽</td><td>{{ s.cash_ops or 0 }} ₽</td><td><b>{{ (s.total_cash or 0) + (s.cash_ops or 0) }} ₽</b></td><td>{{ s.expected_cash or 0 }} ₽</td><td>{{ s.actual_cash or 0 }} ₽</td><td style="color:{{ '#ff453a' if (s.discrepancy or 0) < 0 else '#30d158' }};font-weight:bold">{{ s.discrepancy or 0 }} ₽</td></tr>
{% endfor %}
</table></body></html>
```

### ФАЙЛ: templates/ticket.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8"><title>Встречка #{{ order.id }}</title>
<style>
body { font-family: monospace; width: 300px; margin: 0 auto; padding: 10px; color: #000; background: #fff; }
.center { text-align: center; }
.dashed { border-top: 2px dashed #000; margin: 8px 0; }
table { width: 100%; border-collapse: collapse; font-size: 18px; font-weight: bold; }
td { padding: 4px 0; }
.mods { font-size: 14px; font-weight: normal; font-style: italic; }
.btn { display: block; width: 100%; padding: 12px; margin-top: 12px; background: #000; color: #fff; font-weight: bold; border: none; cursor: pointer; text-align: center; text-decoration: none; box-sizing: border-box; }
@media print { .no-print { display: none !important; } }
</style><link rel="stylesheet" href="/static/ui.css">
</head>
<body onload="window.print()">
<h2 class="center" style="margin:0;">🍳 КУХНЯ #{{ order.id }}</h2>
<div class="center">{{ order.created_at[11:16] }} | {{ order.delivery_type|upper }}</div>
{% if order.scheduled_time %}
<div class="center" style="font-size:18px;font-weight:bold;margin-top:6px;border:2px solid #000;padding:4px;">⏰ КО ВРЕМЕНИ: {{ order.scheduled_time }}</div>
{% endif %}
<div class="dashed"></div>
<table>
{% for item in items %}
<tr><td>{{ item.name }}</td><td style="text-align:right;">x{{ item.qty }}</td></tr>
{% if item.modifiers %}<tr><td colspan="2" class="mods">↳ {{ item.modifiers }}</td></tr>{% endif %}
{% endfor %}
</table>
{% if order.comment %}
<div class="dashed"></div>
<div style="font-size:16px;"><b>КОММ:</b> {{ order.comment }}</div>
{% endif %}
<div class="no-print">
    <button class="btn" onclick="window.print()">🖨️ Печать встречки</button>
    <a href="javascript:history.back()" class="btn" style="background:#555;">← Назад</a>
</div>
</body></html>
```

### ФАЙЛ: templates/track.html
```html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Статус заказа #{{ order.id }} — КРЕВЕТКА Pro</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
.track-wrap { max-width: 620px; margin: 25px auto; padding: 16px; }
.pulse-dot { width: 14px; height: 14px; border-radius: 50%; background: var(--green); display: inline-block; animation: pulseG 1.6s infinite; }
@keyframes pulseG { 0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0.6); } 50% { box-shadow: 0 0 0 10px rgba(16,185,129,0); } }
.steps-vertical { display: flex; flex-direction: column; gap: 10px; margin: 20px 0; }
.step-card { display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-radius: 12px; background: var(--bg-panel); border: 1px solid var(--border); opacity: 0.45; transition: 0.25s; }
.step-card.active { opacity: 1; border-color: var(--accent); background: rgba(255, 107, 0, 0.12); transform: scale(1.01); }
.step-card.completed { opacity: 0.9; border-color: var(--green); background: rgba(16, 185, 129, 0.1); }
.step-icon { width: 42px; height: 42px; border-radius: 10px; background: var(--bg-card); display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 900; }
</style>
</head>
<body>
<div class="pro-topbar">
    <a href="/site" class="pro-brand"><span>🦐 КРЕВЕТКА</span><span class="pro-badge">LIVE TRACKER</span></a>
    <div style="display:flex;gap:8px">
        <a href="/site" class="btn btn-ghost">← В меню</a>
        <a href="/" class="btn btn-ghost">🖥️ Касса</a>
    </div>
</div>

<div class="track-wrap">
    <div class="pro-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-size:22px;font-weight:900">Заказ #{{ order.id }}</span>
            <span style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:800;color:var(--green)">
                <span class="pulse-dot"></span> Онлайн-обновление
            </span>
        </div>
        <div id="st-main-title" style="font-size:20px;font-weight:900;color:var(--accent);margin-bottom:4px">Загрузка статуса...</div>
        <div id="st-main-desc" style="font-size:14px;color:var(--text-muted)">Пожалуйста, подождите</div>

        <div class="steps-vertical">
            <div class="step-card" id="st-step-1">
                <div class="step-icon">📝</div>
                <div>
                    <div style="font-weight:900;font-size:15px">1. Заказ принят</div>
                    <div style="font-size:12px;color:var(--text-muted)">Заказ зарегистрирован в системе и передан поварам</div>
                </div>
            </div>
            <div class="step-card" id="st-step-2">
                <div class="step-icon">👨‍🍳</div>
                <div>
                    <div style="font-weight:900;font-size:15px">2. Готовится на кухне</div>
                    <div style="font-size:12px;color:var(--text-muted)">Повара крутят роллы, запекают и комплектуют заказ</div>
                </div>
            </div>
            <div class="step-card" id="st-step-3">
                <div class="step-icon">🚗</div>
                <div>
                    <div style="font-weight:900;font-size:15px">3. Готов / Курьер в пути</div>
                    <div style="font-size:12px;color:var(--text-muted)">Заказ упакован в термосумку и направляется к вам</div>
                </div>
            </div>
            <div class="step-card" id="st-step-4">
                <div class="step-icon">🎉</div>
                <div>
                    <div style="font-weight:900;font-size:15px">4. Заказ доставлен / выдан</div>
                    <div style="font-size:12px;color:var(--text-muted)">Приятного аппетита!</div>
                </div>
            </div>
        </div>

        <div style="background:var(--bg-panel);border:1px solid var(--border);border-radius:10px;padding:12px;margin-top:14px">
            <div style="font-size:13px;margin-bottom:6px"><b>Тип получения:</b> <span id="tr-del">{{ order.delivery_type }}</span></div>
            <div style="font-size:13px;margin-bottom:6px"><b>Адрес:</b> <span id="tr-addr">{{ order.address or 'Самовывоз' }}</span></div>
            <div style="font-size:13px;margin-bottom:10px"><b>Способ оплаты:</b> <span id="tr-pay">{{ order.payment_method }}</span></div>
            <div style="border-top:1px dashed var(--border);padding-top:8px">
                {% for it in items %}
                <div style="display:flex;justify-content:space-between;font-size:13px;margin:4px 0">
                    <span>{{ it.name }} × {{ it.qty }}</span>
                    <b>{{ it.price * it.qty }} ₽</b>
                </div>
                {% endfor %}
                <div style="display:flex;justify-content:space-between;font-size:18px;font-weight:900;color:var(--accent);margin-top:8px;border-top:1px solid var(--border);padding-top:8px">
                    <span>ИТОГО:</span>
                    <span>{{ order.total }} ₽</span>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
const ORDER_ID = {{ order.id }};
function refreshTracker() {
    fetch('/api/order_status/' + ORDER_ID).then(r=>r.json()).then(d => {
        if(!d.found) return;
        document.getElementById('st-main-title').innerText = d.status_title;
        document.getElementById('st-main-desc').innerText = d.status_desc;
        for(let i=1; i<=4; i++) {
            let el = document.getElementById('st-step-' + i);
            el.classList.remove('active', 'completed');
            if(i < d.step) el.classList.add('completed');
            else if(i === d.step) el.classList.add('active');
        }
    }).catch(()=>{});
}
refreshTracker();
setInterval(refreshTracker, 4000);
</script>
</body></html>
```

### ФАЙЛ: templates/warehouse.html
```html
<!DOCTYPE html><html lang="ru"><head><meta name="csrf-token" content="{{ csrf_token() }}"><script src="/static/security.js"></script><meta charset="UTF-8">
<title>Склад и Цех Заготовок PRO — {{ brand.brand_name }}</title>
<link rel="stylesheet" href="/static/pro_style.css">
<style>
body{margin:0;padding:25px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:10px}
h1{margin:0;color:var(--accent);font-size:26px}a{color:var(--accent);text-decoration:none;font-weight:bold}
.tabs{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.panel{display:none}.panel.active{display:block}
table{width:100%;border-collapse:collapse;margin-bottom:20px}
.btn{background:var(--accent);color:#fff;border:none;padding:8px 14px;border-radius:8px;cursor:pointer;font-weight:bold;font-size:13px}
.btn-danger{background:#ef4444;color:#fff}.btn-edit{background:#10b981;color:#fff}
.badge-prep{background:#3b82f6;color:#fff;padding:3px 8px;border-radius:6px;font-size:11px;margin-left:5px;font-weight:bold}
.badge-waste{background:rgba(245,158,11,0.18);color:#f59e0b;border:1px solid #f59e0b;padding:2px 6px;border-radius:6px;font-size:11px;font-weight:bold}
.prep-card{background:var(--bg-panel);border:1px solid var(--border);border-radius:16px;padding:20px;margin-bottom:20px}
.tare-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:var(--bg-card);padding:12px 16px;border-radius:12px;border:1px solid var(--border);margin-bottom:15px;position:sticky;top:10px;z-index:20}
.tare-btn{background:var(--bg-panel);color:var(--text-main);border:1px solid var(--border);padding:6px 12px;border-radius:8px;cursor:pointer;font-size:12px;font-weight:bold}
.tare-btn:hover{border-color:var(--accent);color:var(--accent)}
.inv-summary{display:flex;gap:20px;flex-wrap:wrap;align-items:center}
</style>
<script>if(localStorage.getItem('theme') === 'light') document.documentElement.classList.add('light-theme');</script>
<link rel="stylesheet" href="/static/ui.css">
</head><body>

<div class="topbar">
    <div>
        <h1>📦 Склад, Отходы и Цех Заготовок PRO</h1>
        <div style="color:var(--text-muted);font-size:14px;margin-top:4px">Капитал на складе: <b style="color:#10b981">{{ total_stock_value }} ₽</b></div>
    </div>
    <div style="display:flex;gap:15px"><a href="/autopilot" style="color:#10b981">🧠 AI Автопилот</a> | <a href="/admin">← В дашборд</a><a href="/">🖥️ В кассу</a></div>
</div>

<div class="tabs">
    <button class="tab-btn active" id="btn-tab-stock" onclick="showTab('tab-stock', this)">📦 1. Сырье, Заготовки и % Отхода</button>
    <button class="tab-btn" id="btn-tab-preps" onclick="showTab('tab-preps', this)">🍲 2. Цех Заготовок (ТТК П/Ф и Варка)</button>
    <button class="tab-btn" id="btn-tab-inv" onclick="showTab('tab-inv', this)">⚖️ 3. Умная Инвентаризация (Тара + П/Ф)</button>
    <button class="tab-btn" id="btn-tab-logs" onclick="showTab('tab-logs', this)">📜 4. Журнал операций</button>
    <button class="tab-btn" id="btn-tab-recipes" onclick="showTab('tab-recipes', this)">🍱 5. Техкарты блюд</button>
</div>

<!-- ВКЛАДКА 1: ОСТАТКИ И ПРОЦЕНТ ОТХОДА -->
<div id="tab-stock" class="panel active">

    <div class="stat-card" style="padding:18px;margin-bottom:20px;border:1px solid #3b82f6 !important">
        <h3 style="margin:0 0 10px;color:#3b82f6">🐟 Акт разделки тушки / сырья (Авто-расчет % отхода и оприходование филе и обрези)</h3>
        <form method="post" action="/admin/warehouse/butcher" style="display:flex;flex-wrap:wrap;gap:10px;align-items:end">
            <div>
                <label style="font-size:11px;color:var(--text-muted);display:block">Что разделываем (Брутто)</label>
                <select name="raw_id" required style="padding:9px;width:210px">
                    {% for i in ingredients %}<option value="{{ i.id }}">{{ i.name }} (ост: {{ i.stock|round(1) }} {{ i.unit }})</option>{% endfor %}
                </select>
            </div>
            <div>
                <label style="font-size:11px;color:var(--text-muted);display:block">Вес тушки до разделки</label>
                <input type="number" step="any" name="raw_weight" placeholder="Напр. 5200" required style="width:125px;padding:9px">
            </div>
            <div>
                <label style="font-size:11px;color:#10b981;display:block">Выход 1 (Чистое филе)</label>
                <select name="out1_id" style="padding:9px;width:185px">
                    <option value="0">-- Выберите П/Ф или позицию --</option>
                    {% for i in ingredients %}<option value="{{ i.id }}">{{ i.name }}</option>{% endfor %}
                </select>
            </div>
            <div>
                <label style="font-size:11px;color:#10b981;display:block">Вес выхода 1</label>
                <input type="number" step="any" name="out1_weight" placeholder="Напр. 3450" required style="width:105px;padding:9px">
            </div>
            <div>
                <label style="font-size:11px;color:#f59e0b;display:block">Выход 2 (Обрезь / Теша / Суп)</label>
                <select name="out2_id" style="padding:9px;width:185px">
                    <option value="0">-- Нет второго выхода --</option>
                    {% for i in ingredients %}<option value="{{ i.id }}">{{ i.name }}</option>{% endfor %}
                </select>
            </div>
            <div>
                <label style="font-size:11px;color:#f59e0b;display:block">Вес выхода 2</label>
                <input type="number" step="any" name="out2_weight" value="0" style="width:95px;padding:9px">
            </div>
            <button type="submit" class="btn" style="background:#3b82f6;padding:10px 16px">🔪 Провести разделку</button>
        </form>
    </div>

    <form method="post" action="/admin/ingredient/add" class="stat-card" style="display:flex;flex-wrap:wrap;gap:10px;padding:16px;align-items:end;margin-bottom:20px">
        <div><label style="font-size:11px;color:var(--text-muted);display:block">Наименование</label><input name="name" placeholder="Лосось / Огурец / Рис вареный П/Ф" required style="width:230px;padding:9px"></div>
        <div><label style="font-size:11px;color:var(--text-muted);display:block">Нач. остаток</label><input name="stock" type="number" step="any" value="0" style="width:85px;padding:9px"></div>
        <div><label style="font-size:11px;color:var(--text-muted);display:block">Ед. изм.</label><input name="unit" placeholder="г, мл, шт" required style="width:75px;padding:9px"></div>
        <div><label style="font-size:11px;color:var(--text-muted);display:block">Цена Брутто (за 1 ед)</label><input name="cost_price" type="number" step="any" value="0" style="width:120px;padding:9px"></div>
        <div><label style="font-size:11px;color:#f59e0b;display:block">✂️ % Отхода (чистка/разделка)</label><input name="waste_pct" type="number" step="any" min="0" max="95" value="0" placeholder="0%" style="width:140px;padding:9px"></div>
        <label style="font-size:13px;padding:9px;background:var(--bg-card);border-radius:8px;border:1px solid var(--border);cursor:pointer;display:flex;align-items:center;gap:6px">
            <input type="checkbox" name="is_prep" value="1"> 🍲 Это Заготовка (П/Ф)
        </label>
        <button type="submit" class="btn" style="padding:10px 18px">➕ Добавить на склад</button>
    </form>

    <table>
        <tr>
            <th>Позиция</th>
            <th>Остаток на складе</th>
            <th>Цена Брутто (Закуп)</th>
            <th>✂️ % Отхода</th>
            <th>🔥 Цена Нетто (В блюдо)</th>
            <th>Операция (Приход / Списание / Изм. отхода)</th>
            <th>Удал.</th>
        </tr>
        {% for i in ingredients %}
        {% set w = i.waste_pct or 0 %}
        {% set net_price = (i.cost_price / (1 - w/100)) if w < 95 and w > 0 else i.cost_price %}
        <tr>
            <td><b>{{ i.name }}</b> {% if i.is_prep %}<span class="badge-prep">🍲 П/Ф</span>{% endif %}</td>
            <td style="font-weight:bold;color:{% if i.stock <= 0 %}#ef4444{% else %}#10b981{% endif %}">{{ i.stock|round(2) }} {{ i.unit }}</td>
            <td>{{ i.cost_price|round(3) }} ₽/{{ i.unit }}</td>
            <td>{% if w > 0 %}<span class="badge-waste">Отход {{ w }}%</span>{% else %}<span style="color:var(--text-muted)">0%</span>{% endif %}</td>
            <td style="color:#f59e0b;font-weight:bold">{{ net_price|round(3) }} ₽/{{ i.unit }}</td>
            <td>
                <form method="post" action="/admin/ingredient/update/{{ i.id }}" style="display:flex;gap:5px;align-items:center;flex-wrap:wrap">
                    <select name="action" style="padding:6px">
                        <option value="add">➕ Приход</option>
                        <option value="writeoff">➖ Списать (Стафф/Брак)</option>
                        <option value="settings">⚙️ Сохранить цену/% отхода</option>
                    </select>
                    <input type="number" step="any" name="val" placeholder="Кол-во" style="width:75px;padding:6px">
                    <input type="number" step="any" name="cost_price" value="{{ i.cost_price }}" title="Цена закупа за 1 ед." style="width:70px;padding:6px">
                    <input type="number" step="any" name="waste_pct" value="{{ w }}" title="% отхода при чистке/разделке" placeholder="% отх" style="width:60px;padding:6px">
                    <input type="text" name="reason" placeholder="Комментарий (Стафф, накладная)" style="width:140px;padding:6px">
                    <button type="submit" class="btn btn-edit" style="padding:6px 12px">ОК</button>
                </form>
            </td>
            <td><form method="post" action="/admin/ingredient/delete/{{ i.id }}" onsubmit="return confirm('Удалить позицию?');"><button class="btn btn-danger" style="padding:6px 10px">🗑️</button></form></td>
        </tr>
        {% endfor %}
    </table>
</div>

<!-- ВКЛАДКА 2: ЦЕХ ЗАГОТОВОК (ТТК П/Ф И ПРИГОТОВЛЕНИЕ) -->
<div id="tab-preps" class="panel">
    <div class="stat-card" style="padding:15px;margin-bottom:20px;line-height:1.5">
        💡 <b>Как работает Цех Заготовок:</b> Любую позицию с галочкой <b>«🍲 П/Ф»</b> (например, <i>Рис вареный, Соус Спайси, Замес Краб, Тесто WOK и супы, Филе лосося</i>) можно собрать из сырья. Укажите, сколько сырья идет на 1 замес и какой получается <b>выход готовой заготовки</b> (с учетом ужарки, уварки, привара воды или отхода разделки). Программа сама вычислит себестоимость 1 грамма П/Ф!
    </div>

    {% if not preps %}
    <div class="stat-card" style="padding:30px;text-align:center;color:var(--text-muted)">
        У вас пока нет ни одной позиции с отметкой «🍲 Это Заготовка (П/Ф)».<br>Создайте её во вкладке «1. Сырье и Заготовки» (например: <b>Рис вареный П/Ф</b> в граммах).
    </div>
    {% endif %}

    {% for p in preps %}
    <div class="prep-card">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;border-bottom:1px solid var(--border);padding-bottom:12px;margin-bottom:15px">
            <div>
                <h2 style="margin:0;color:#3b82f6">🍲 {{ p.name }}</h2>
                <div style="font-size:13px;color:var(--text-muted);margin-top:4px">
                    В наличии на кухне: <b style="color:#10b981">{{ p.stock|round(2) }} {{ p.unit }}</b> |
                    Вес сырья в закладке: <b>{{ p.raw_weight }} {{ p.unit }}</b> →
                    Выход готового П/Ф: <b style="color:var(--accent)">{{ p.prep_yield }} {{ p.unit }}</b> |
                    Себестоимость П/Ф: <b style="color:#f59e0b">{{ p.cost_price|round(3) }} ₽/{{ p.unit }}</b>
                </div>
            </div>
            <form method="post" action="/admin/prep/produce/{{ p.id }}" style="display:flex;gap:8px;align-items:center;background:var(--bg-card);padding:10px 14px;border-radius:12px;border:1px solid var(--border)">
                <span style="font-size:13px;font-weight:bold">Сварить / Замесить партий:</span>
                <input type="number" step="any" name="batches" value="1" min="0.1" style="width:65px;padding:6px;text-align:center">
                <button type="submit" class="btn btn-edit">🔥 Приготовить П/Ф (+{{ p.prep_yield }} {{ p.unit }})</button>
            </form>
        </div>

        <form method="post" action="/admin/prep/save/{{ p.id }}">
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin-bottom:15px">
                {% set existing = {} %}
                {% for r in p.recipe %}{% set _ = existing.update({r.raw_id: r.amount}) %}{% endfor %}
                {% for raw in raw_ings %}
                <div style="background:var(--bg-card);padding:8px 12px;border-radius:10px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:13px">{{ raw.name }} <small style="color:var(--text-muted)">({{ raw.unit }}{% if raw.waste_pct %}, отх.{{ raw.waste_pct }}%{% endif %})</small></span>
                    <input type="number" step="any" name="raw_{{ raw.id }}" value="{{ existing.get(raw.id, '') }}" placeholder="0" style="width:75px;padding:5px;text-align:right">
                </div>
                {% endfor %}
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                <div style="display:flex;align-items:center;gap:10px">
                    <label style="font-size:14px;font-weight:bold;color:var(--accent)">⚖️ Выход готовой заготовки с 1 замеса ({{ p.unit }}):</label>
                    <input type="number" step="any" name="prep_yield" value="{{ p.prep_yield }}" required style="width:110px;padding:8px;font-weight:bold">
                    <span style="font-size:12px;color:var(--text-muted)">(учитывает привар воды у риса или уварку соуса)</span>
                </div>
                <button type="submit" class="btn">💾 Сохранить ТТК заготовки и пересчитать себестоимость</button>
            </div>
        </form>
    </div>
    {% endfor %}
</div>

<!-- ВКЛАДКА 3: УМНАЯ ИНВЕНТАРИЗАЦИЯ С ВЫЧЕТОМ ТАРЫ И СУММАТОРОМ -->
<div id="tab-inv" class="panel">
    <form method="post" action="/admin/warehouse/inventory">
        <div class="tare-bar">
            <div style="font-size:13px"><b>🧮 Калькулятор тары и сумматор:</b> кликните в поле веса (можно писать <code style="color:var(--accent)">1200+450+300</code>) и нажмите кнопку тары, чтобы вычесть вес посуды:</div>
            <button type="button" class="tare-btn" onclick="applyTare(50)">-50г (Соусник/Бут)</button>
            <button type="button" class="tare-btn" onclick="applyTare(180)">-180г (Контейнер)</button>
            <button type="button" class="tare-btn" onclick="applyTare(350)">-350г (GN 1/6)</button>
            <button type="button" class="tare-btn" onclick="applyTare(500)">-500г (GN 1/3)</button>
            <button type="button" class="tare-btn" onclick="applyTare(800)">-800г (GN 1/2)</button>
            <button type="button" class="tare-btn" onclick="applyTare(1200)">-1200г (Кастрюля/Таз)</button>
        </div>

        <div class="stat-card" style="padding:16px;margin-bottom:15px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:15px">
            <div class="inv-summary">
                <div>Излишки: <b id="inv-plus" style="color:#10b981">+0 ₽</b></div>
                <div>Недостача: <b id="inv-minus" style="color:#ef4444">0 ₽</b></div>
                <div>Итоговый баланс ревизии: <b id="inv-net" style="font-size:18px">0 ₽</b></div>
                <label style="background:var(--bg-card);padding:8px 12px;border-radius:8px;border:1px solid var(--border);cursor:pointer;font-size:13px;display:flex;align-items:center;gap:6px">
                    <input type="checkbox" name="decompose_preps" value="1">
                    🔄 <b>Разложить остатки П/Ф обратно в сырье</b> (если заготовки на столах не проводились через кнопку варки)
                </label>
            </div>
            <button type="submit" class="btn btn-edit" style="padding:12px 22px;font-size:15px">✅ Применить ревизию</button>
        </div>

        <table>
            <tr><th>Позиция</th><th>Тип</th><th>По программе</th><th>Факт с весов (можно через +)</th><th>Разница</th><th>Результат (₽)</th></tr>
            {% for i in ingredients %}
            <tr>
                <td><b>{{ i.name }}</b> ({{ i.unit }})</td>
                <td>{% if i.is_prep %}<span class="badge-prep">🍲 П/Ф Заготовка</span>{% else %}<span style="color:var(--text-muted);font-size:12px">Сырье</span>{% endif %}</td>
                <td id="sys-{{ i.id }}" data-stock="{{ i.stock }}" data-cost="{{ i.cost_price }}">{{ i.stock|round(2) }} {{ i.unit }}</td>
                <td>
                    <input type="text" id="inp-{{ i.id }}" name="fact_{{ i.id }}" placeholder="{{ i.stock|round(2) }} (напр. 1000+500)"
                           onfocus="lastFocusedInput=this"
                           oninput="evalAndCalc({{ i.id }}, this)"
                           onblur="finalizeExpr({{ i.id }}, this)"
                           style="width:190px;padding:8px;font-weight:bold">
                </td>
                <td id="diff-{{ i.id }}" style="font-weight:bold;color:var(--text-muted)">0</td>
                <td id="rub-{{ i.id }}" class="rub-cell" data-rub="0" style="font-weight:bold;color:var(--text-muted)">0 ₽</td>
            </tr>
            {% endfor %}
        </table>
    </form>
</div>

<!-- ВКЛАДКА 5: ТЕХКАРТЫ БЛЮД -->
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
<div id="tab-logs" class="panel">
    <table>
        <tr><th>Дата и время</th><th>Позиция</th><th>Операция</th><th>Изменение</th><th>Сумма (₽)</th><th>Детали / Причина</th><th>Сотрудник</th></tr>
        {% for l in logs %}
        <tr>
            <td style="color:var(--text-muted)">{{ l.created_at }}</td>
            <td><b>{{ l.ing_name }}</b></td>
            <td><span class="badge-prep" style="background:var(--bg-card);border:1px solid var(--border)">{{ l.op_type }}</span></td>
            <td style="font-weight:bold;color:{% if l.change_amount >= 0 %}#10b981{% else %}#ef4444{% endif %}">{% if l.change_amount > 0 %}+{% endif %}{{ l.change_amount|round(2) }}</td>
            <td style="font-weight:bold">{{ l.cost_impact }} ₽</td>
            <td style="color:var(--text-muted)">{{ l.reason }}</td>
            <td>{{ l.username }}</td>
        </tr>
        {% endfor %}
    </table>
</div>

<script>
let lastFocusedInput = null;

function showTab(id, btn){
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    btn.classList.add('active');
}

window.addEventListener('DOMContentLoaded', () => {
    if(location.hash === '#tab-preps') showTab('tab-preps', document.getElementById('btn-tab-preps'));
    if(location.hash === '#tab-logs') showTab('tab-logs', document.getElementById('btn-tab-logs'));
});

function parseMathExpr(str){
    if(!str || !str.trim()) return NaN;
    const cleaned = str.replace(/,/g, '.').replace(/[^0-9.+\-]/g, '');
    if(!cleaned) return NaN;
    try {
        const parts = cleaned.match(/[+\-]?[0-9.]+/g);
        if(!parts) return NaN;
        return parts.reduce((acc, v) => acc + (parseFloat(v) || 0), 0);
    } catch(e) { return NaN; }
}

function applyTare(tareGrams){
    if(!lastFocusedInput) return alert('Сначала кликните в ячейку с весом продукта!');
    const cur = parseMathExpr(lastFocusedInput.value);
    if(isNaN(cur)) return alert('Сначала введите вес брутто с весов в ячейку!');
    const net = Math.max(0, cur - tareGrams);
    lastFocusedInput.value = net;
    const id = parseInt(lastFocusedInput.id.replace('inp-', ''));
    evalAndCalc(id, lastFocusedInput);
    lastFocusedInput.focus();
}

function finalizeExpr(id, inp){
    const val = parseMathExpr(inp.value);
    if(!isNaN(val)) inp.value = Math.round(val * 1000) / 1000;
    evalAndCalc(id, inp);
}

function evalAndCalc(id, inp){
    const sysEl = document.getElementById('sys-'+id);
    const stock = parseFloat(sysEl.dataset.stock) || 0;
    const cost = parseFloat(sysEl.dataset.cost) || 0;
    const diffEl = document.getElementById('diff-'+id);
    const rubEl = document.getElementById('rub-'+id);
    const val = parseMathExpr(inp.value);
    if(isNaN(val)){
        diffEl.innerText='0'; rubEl.innerText='0 ₽'; rubEl.dataset.rub='0';
        diffEl.style.color='var(--text-muted)'; rubEl.style.color='var(--text-muted)';
        updateInvSummary(); return;
    }
    const diff = val - stock;
    const rub = diff * cost;
    rubEl.dataset.rub = rub;
    diffEl.innerText = (diff > 0 ? '+' : '') + diff.toFixed(2);
    rubEl.innerText = (rub > 0 ? '+' : '') + rub.toFixed(1) + ' ₽';
    const color = diff < -0.001 ? '#ef4444' : (diff > 0.001 ? '#10b981' : 'var(--text-muted)');
    diffEl.style.color = color; rubEl.style.color = color;
    updateInvSummary();
}

function updateInvSummary(){
    let plus = 0, minus = 0;
    document.querySelectorAll('.rub-cell').forEach(el => {
        const r = parseFloat(el.dataset.rub) || 0;
        if(r > 0) plus += r;
        if(r < 0) minus += r;
    });
    const net = plus + minus;
    document.getElementById('inv-plus').innerText = '+' + plus.toFixed(1) + ' ₽';
    document.getElementById('inv-minus').innerText = minus.toFixed(1) + ' ₽';
    const netEl = document.getElementById('inv-net');
    netEl.innerText = (net > 0 ? '+' : '') + net.toFixed(1) + ' ₽';
    netEl.style.color = net < 0 ? '#ef4444' : '#10b981';
}
</script></body></html>
```

