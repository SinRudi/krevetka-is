import os
import re
import glob
import sqlite3

BASE_DIR = os.path.expanduser("~/my-apps/sushi_pos")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# 1. НАСТРОЙКА ТАБЛИЦЫ КАСТОМНЫХ ЗОН И ПРОВЕРКА БД
for db_path in glob.glob(os.path.join(BASE_DIR, "*.db")):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS delivery_zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            fee REAL NOT NULL DEFAULT 0,
            color TEXT DEFAULT '#ff6b00',
            polygon_coords TEXT DEFAULT '[]',
            is_active INTEGER DEFAULT 1
        )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB check note ({db_path}): {e}")

# 2. ПРЕМИАЛЬНЫЙ СТИЛЬ KREVETKA PRO ULTRA (STATIC/PRO_STYLE.CSS)
pro_css = """
:root {
    --bg-main: #090d16;
    --bg-card: #121826;
    --bg-panel: #182032;
    --bg-glass: rgba(18, 24, 38, 0.85);
    --border: #26334d;
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
    --accent: #ff5e00;
    --accent-glow: rgba(255, 94, 0, 0.35);
    --green: #10b981;
    --yellow: #f59e0b;
    --purple: #8b5cf6;
    --red: #ef4444;
    --blue: #3b82f6;
}
body.light-theme {
    --bg-main: #f1f5f9;
    --bg-card: #ffffff;
    --bg-panel: #e2e8f0;
    --bg-glass: rgba(255, 255, 255, 0.9);
    --border: #cbd5e1;
    --text-main: #0f172a;
    --text-muted: #475569;
    --accent: #ea580c;
    --accent-glow: rgba(234, 88, 12, 0.25);
}
* { box-sizing: border-box; }
body {
    margin: 0; padding: 0; background: var(--bg-main); color: var(--text-main);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased;
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-main); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

.pro-topbar {
    background: var(--bg-glass); backdrop-filter: blur(14px);
    border-bottom: 1px solid var(--border); padding: 12px 22px;
    display: flex; justify-content: space-between; align-items: center;
    position: sticky; top: 0; z-index: 150;
}
.pro-brand {
    display: flex; align-items: center; gap: 10px; font-size: 21px;
    font-weight: 900; color: var(--text-main); text-decoration: none; letter-spacing: -0.5px;
}
.pro-badge {
    background: linear-gradient(135deg, #ff6b00, #ff2a00); color: #fff;
    font-size: 11px; padding: 4px 9px; border-radius: 8px; font-weight: 900;
    box-shadow: 0 4px 12px var(--accent-glow);
}
.pro-nav { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.btn {
    background: linear-gradient(135deg, #ff6b00, #ea580c); color: #fff; border: none;
    padding: 10px 16px; border-radius: 11px; cursor: pointer; font-weight: 800;
    font-size: 13px; text-decoration: none; display: inline-flex; align-items: center;
    justify-content: center; gap: 6px; transition: all 0.15s ease;
    box-shadow: 0 4px 12px rgba(255, 94, 0, 0.2);
}
.btn:hover { transform: translateY(-1px); filter: brightness(1.08); }
.btn:active { transform: scale(0.97); }
.btn-green { background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2); }
.btn-yellow { background: linear-gradient(135deg, #f59e0b, #d97706); color: #000; box-shadow: none; }
.btn-purple { background: linear-gradient(135deg, #8b5cf6, #6d28d9); box-shadow: none; }
.btn-red { background: linear-gradient(135deg, #ef4444, #dc2626); box-shadow: none; }
.btn-blue { background: linear-gradient(135deg, #3b82f6, #2563eb); box-shadow: none; }
.btn-ghost { background: var(--bg-panel); border: 1px solid var(--border); color: var(--text-main); box-shadow: none; }
.btn-ghost:hover { border-color: var(--accent); }

input, select, textarea {
    background: var(--bg-main); border: 1px solid var(--border); color: var(--text-main);
    padding: 11px 14px; border-radius: 10px; font-size: 14px; outline: none; transition: 0.15s;
}
input:focus, select:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
"""
with open(os.path.join(STATIC_DIR, "pro_style.css"), "w", encoding="utf-8") as f:
    f.write(pro_css)

# 3. УМНЫЙ МОДУЛЬ КАРТИНОК И ЗВУКОВЫХ УВЕДОМЛЕНИЙ (STATIC/ZONES_INTA.JS)
zones_js = """
window.INTA_ZONES = {};

window.getDishPhoto = function(name, category, dbImg) {
    let clean = (dbImg || '').trim();
    if (clean.length > 3 && !clean.includes('none') && !clean.includes('placeholder') && clean !== 'null') {
        if (!clean.startsWith('http') && !clean.startsWith('/')) {
            return '/static/uploads/' + clean;
        }
        return clean;
    }
    let n = ((name || '') + ' ' + (category || '')).toLowerCase();
    if(n.includes('филадельф')) return 'https://images.unsplash.com/photo-1579871494447-9811cf80d66c?auto=format&fit=crop&w=600&q=80';
    if(n.includes('калифорн')) return 'https://images.unsplash.com/photo-1617196034796-73dfa7b1fd56?auto=format&fit=crop&w=600&q=80';
    if(n.includes('запеч')) return 'https://images.unsplash.com/photo-1611143669185-af224c5e3252?auto=format&fit=crop&w=600&q=80';
    if(n.includes('темпур') || n.includes('жарен') || n.includes('кранч')) return 'https://images.unsplash.com/photo-1553621042-f6e147245754?auto=format&fit=crop&w=600&q=80';
    if(n.includes('сет') || n.includes('набор')) return 'https://images.unsplash.com/photo-1562802378-063ec186a863?auto=format&fit=crop&w=600&q=80';
    if(n.includes('вок') || n.includes('wok') || n.includes('лапш') || n.includes('удон') || n.includes('соба') || n.includes('тяхан')) return 'https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=600&q=80';
    if(n.includes('суп') || n.includes('том ям') || n.includes('мисо') || n.includes('рамен') || n.includes('фо бо')) return 'https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80';
    return 'https://images.unsplash.com/photo-1579584425555-c3ce17fd4351?auto=format&fit=crop&w=600&q=80';
};

// Приятный звуковой сигнал нового заказа (Web Audio API без внешних mp3)
window.playNewOrderBell = function() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const playTone = (freq, start, dur) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
            gain.gain.setValueAtTime(0.18, ctx.currentTime + start);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(ctx.currentTime + start);
            osc.stop(ctx.currentTime + start + dur);
        };
        playTone(659.25, 0, 0.18);
        playTone(880.00, 0.16, 0.35);
    } catch(e) {}
};
"""
with open(os.path.join(STATIC_DIR, "zones_inta.js"), "w", encoding="utf-8") as f:
    f.write(zones_js)

# 4. ОБНОВЛЕНИЕ APP.PY (API ЗОН, РЕДАКТОР ЗОН, ПОИСК КЛИЕНТА ПО ТЕЛЕФОНУ)
app_path = os.path.join(BASE_DIR, "app.py")
with open(app_path, "r", encoding="utf-8") as f:
    code = f.read()

ultra_api = """
@app.route('/zones_editor')
def zones_editor_page():
    return render_template('zones_editor.html')

@app.route('/api/zones_custom', methods=['GET', 'POST'])
def api_zones_custom():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS delivery_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        fee REAL NOT NULL DEFAULT 0,
        color TEXT DEFAULT '#ff5e00',
        polygon_coords TEXT DEFAULT '[]',
        is_active INTEGER DEFAULT 1
    )''')
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        action = data.get('action', 'save')
        if action == 'delete':
            db.execute("DELETE FROM delivery_zones WHERE id=?", (data.get('id'),))
            db.commit()
            return jsonify({'success': True})
        if action == 'clear_all':
            db.execute("DELETE FROM delivery_zones")
            db.commit()
            return jsonify({'success': True})
        name = str(data.get('name') or 'Зона').strip()
        fee = float(data.get('fee') or 0)
        color = str(data.get('color') or '#ff5e00').strip()
        coords = str(data.get('polygon_coords') or '[]')
        zid = data.get('id')
        if zid:
            db.execute("UPDATE delivery_zones SET name=?, fee=?, color=?, polygon_coords=? WHERE id=?", (name, fee, color, coords, zid))
        else:
            db.execute("INSERT INTO delivery_zones (name, fee, color, polygon_coords) VALUES (?, ?, ?, ?)", (name, fee, color, coords))
        db.commit()
        return jsonify({'success': True})
    rows = db.execute("SELECT * FROM delivery_zones WHERE is_active=1 ORDER BY fee ASC").fetchall()
    return jsonify({'zones': [dict(r) for r in rows]})

@app.route('/api/phone_hint')
def api_phone_hint():
    phone = (request.args.get('phone') or '').strip()
    if len(phone) < 5:
        return jsonify({'found': False})
    db = get_db()
    row = db.execute("SELECT address, delivery_type, COUNT(*) as cnt, SUM(total) as spent FROM orders WHERE phone LIKE ? AND address != 'Самовывоз' AND address != '' GROUP BY phone ORDER BY id DESC LIMIT 1", (f"%{phone}%",)).fetchone()
    if row:
        return jsonify({'found': True, 'address': row['address'], 'orders_count': row['cnt'], 'total_spent': row['spent']})
    return jsonify({'found': False})
"""

if "/api/zones_custom" not in code:
    if "if __name__ ==" in code:
        code = code.replace("if __name__ ==", ultra_api + "\nif __name__ ==")
    else:
        code += "\n" + ultra_api

code = code.replace(
    "'/api/site_order_safe'",
    "'/api/site_order_safe', '/api/zones_custom'"
)

with open(app_path, "w", encoding="utf-8") as f:
    f.write(code)
print("✅ Бэкенд app.py дополнен маршрутами редактора зон и CRM-подсказок!")

# 5. ВИТРИНА САЙТА ПРЕМИУМ-УРОВНЯ (TEMPLATES/PUBLIC_SITE.HTML)
public_site_ultra = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>КРЕВЕТКА — Доставка авторских роллов, WOK и супов</title>
<link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="/static/zones_inta.js"></script>
<style>
.hero-banner {
    background: radial-gradient(circle at 20% 20%, rgba(255, 94, 0, 0.22), transparent 55%),
                radial-gradient(circle at 80% 80%, rgba(139, 92, 246, 0.18), transparent 55%),
                var(--bg-card);
    border-bottom: 1px solid var(--border); padding: 32px 20px; text-align: center;
}
.hero-title { font-size: clamp(22px, 4vw, 34px); font-weight: 900; margin: 0 0 8px 0; letter-spacing: -0.5px; }
.hero-sub { color: var(--text-muted); font-size: 15px; max-width: 640px; margin: 0 auto 18px auto; }
.hero-badges { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
.h-pill { background: var(--bg-panel); border: 1px solid var(--border); padding: 7px 14px; border-radius: 99px; font-size: 12px; font-weight: 800; }

.filter-toolbar {
    max-width: 1320px; margin: 18px auto 6px auto; padding: 0 18px;
    display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap;
}
.cats-scroll { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; padding-bottom: 4px; flex: 1; }
.cats-scroll::-webkit-scrollbar { display: none; }
.cat-chip {
    background: var(--bg-card); border: 1px solid var(--border); color: var(--text-main);
    padding: 10px 18px; border-radius: 99px; font-weight: 800; font-size: 13px;
    cursor: pointer; white-space: nowrap; transition: 0.15s;
}
.cat-chip.active { background: var(--accent); color: #fff; border-color: var(--accent); box-shadow: 0 4px 14px var(--accent-glow); }

.site-grid {
    max-width: 1320px; margin: 0 auto; padding: 14px 18px 90px 18px;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px;
}
.dish-card {
    background: var(--bg-card); border: 1px solid var(--border); border-radius: 18px;
    overflow: hidden; display: flex; flex-direction: column; transition: all 0.2s ease;
    position: relative; box-shadow: 0 10px 25px rgba(0,0,0,0.22);
}
.dish-card:hover { transform: translateY(-4px); border-color: var(--accent); }
.dish-img-box { width: 100%; height: 195px; overflow: hidden; position: relative; background: #0d121d; }
.dish-img-box img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.35s ease; }
.dish-card:hover .dish-img-box img { transform: scale(1.06); }
.dish-tag {
    position: absolute; top: 12px; left: 12px; background: rgba(9, 13, 22, 0.82);
    backdrop-filter: blur(6px); color: #fff; padding: 5px 11px; border-radius: 99px;
    font-size: 11px; font-weight: 900; border: 1px solid rgba(255,255,255,0.12);
}
.dish-portions {
    position: absolute; bottom: 10px; right: 10px; background: rgba(255, 94, 0, 0.92);
    color: #fff; padding: 3px 9px; border-radius: 7px; font-size: 11px; font-weight: 900;
}
.dish-body { padding: 16px; display: flex; flex-direction: column; flex: 1; }
.dish-title { font-size: 17px; font-weight: 900; margin-bottom: 6px; line-height: 1.3; }
.dish-desc { font-size: 12px; color: var(--text-muted); margin-bottom: 14px; flex: 1; line-height: 1.45; }
.dish-footer { display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 1px solid var(--border); }
.dish-price { font-size: 21px; font-weight: 900; color: var(--text-main); }

.qty-stepper {
    display: inline-flex; align-items: center; gap: 10px; background: var(--bg-panel);
    border: 1px solid var(--accent); border-radius: 11px; padding: 4px 6px;
}
.qty-stepper button {
    width: 30px; height: 30px; border-radius: 8px; border: none; background: var(--accent);
    color: #fff; font-weight: 900; font-size: 16px; cursor: pointer;
}

/* ПЛАВАЮЩАЯ ПАНЕЛЬ КОРЗИНЫ СНИЗУ */
.floating-cart-bar {
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    background: linear-gradient(135deg, #ff6b00, #e11d48); color: #fff;
    padding: 14px 26px; border-radius: 99px; display: none; align-items: center;
    gap: 18px; z-index: 180; cursor: pointer; box-shadow: 0 12px 32px rgba(255, 94, 0, 0.45);
    font-weight: 900; font-size: 15px; transition: 0.2s;
}
.floating-cart-bar:hover { transform: translateX(-50%) scale(1.03); }

/* ШТОРКА КОРЗИНЫ */
.drawer-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.75); backdrop-filter: blur(4px); display: none; justify-content: flex-end; z-index: 400; }
.drawer-box { width: 100%; max-width: 490px; background: var(--bg-card); height: 100%; display: flex; flex-direction: column; padding: 20px; overflow-y: auto; border-left: 1px solid var(--border); }
.pay-chip, .zone-chip {
    flex: 1; padding: 10px 8px; font-size: 12px; font-weight: 900; border: 1px solid var(--border);
    background: var(--bg-panel); color: var(--text-main); border-radius: 10px; cursor: pointer; text-align: center; transition: 0.15s;
}
.pay-chip.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.zone-chip.active { background: var(--purple); color: #fff; border-color: var(--purple); }
</style>
</head>
<body>

<div class="pro-topbar">
    <a href="/site" class="pro-brand">
        <span>🦐 КРЕВЕТКА</span>
        <span class="pro-badge">РОЛЛЫ • WOK • СУПЫ</span>
    </a>
    <div class="pro-nav">
        <div id="my-last-order-link"></div>
        <button onclick="document.body.classList.toggle('light-theme')" class="btn btn-ghost" title="Сменить тему">🌓</button>
        <button class="btn" onclick="openCart()">🛒 Корзина (<span id="cart-badge">0</span>)</button>
    </div>
</div>

<div class="hero-banner">
    <h1 class="hero-title">Ресторан доставки «КРЕВЕТКА»</h1>
    <div class="hero-sub">Свежие роллы по 8 кусочков с плотной нарезкой рыбы, обжигающий WOK из-под ножа и наваристые азиатские супы</div>
    <div class="hero-badges">
        <span class="h-pill">🍣 Роллы — ровно 8 кусочков</span>
        <span class="h-pill">🔥 Горячий WOK и Том Ям</span>
        <span class="h-pill">📡 Живое отслеживание заказа</span>
    </div>
</div>

<div class="filter-toolbar">
    <div class="cats-scroll">
        <button class="cat-chip active" onclick="filterCategory('all', this)">🍱 Все блюда</button>
        {% for c in categories %}
        <button class="cat-chip" onclick="filterCategory('{{ c.category }}', this)">{{ c.category }}</button>
        {% endfor %}
    </div>
    <input type="text" id="site-search" placeholder="🔍 Найти ролл, WOK или суп..." oninput="filterSearch()" style="width:260px;">
</div>

<div class="site-grid" id="menu-container">
    {% for m in menu %}
    {% set raw_img = m.image_url or m.image or m.photo or '' %}
    {% set lname = (m.name or '') | lower %}
    {% set lcat = (m.category or '') | lower %}
    <div class="dish-card" data-cat="{{ m.category }}" data-name="{{ lname }}">
        <div class="dish-img-box">
            <img class="dish-auto-img" data-name="{{ m.name }}" data-cat="{{ m.category }}" data-dbimg="{{ raw_img }}" src="{{ raw_img }}" alt="{{ m.name }}" loading="lazy">
            <span class="dish-tag">{{ m.category }}</span>
            {% if 'ролл' in lcat or 'ролл' in lname %}
            <span class="dish-portions">8 шт.</span>
            {% endif %}
        </div>
        <div class="dish-body">
            <div class="dish-title">{{ m.name }}</div>
            <div class="dish-desc">{{ m.description if m.description else 'Готовим сразу после получения заказа из свежих ингредиентов' }}</div>
            <div class="dish-footer">
                <span class="dish-price">{{ m.price }} ₽</span>
                <div id="ctrl-{{ m.id }}">
                    <button class="btn" onclick="addToCart({{ m.id }}, '{{ m.name | replace(\"'\", \"\") }}', {{ m.price }})">+ В корзину</button>
                </div>
            </div>
        </div>
    </div>
    {% endfor %}
</div>

<!-- КАРТА ЗОН ДОСТАВКИ (ПОКАЗЫВАЕТСЯ ТОЛЬКО ЕСЛИ ВЫ ДОБАВИЛИ ЗОНЫ В РЕДАКТОРЕ) -->
<div id="map-section-wrapper" style="max-width:1320px;margin:0 auto 50px auto;padding:0 18px;display:none;">
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:18px;padding:18px;">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:10px">
            <div>
                <h3 style="margin:0;font-size:18px">🗺️ Зоны доставки</h3>
                <div style="font-size:12px;color:var(--text-muted)">Нажмите на свою зону на карте для расчёта доставки</div>
            </div>
            <div id="map-zones-legend" style="display:flex;gap:8px;flex-wrap:wrap"></div>
        </div>
        <div id="custom-map" style="width:100%;height:340px;border-radius:12px;border:1px solid var(--border);z-index:10"></div>
    </div>
</div>

<!-- ПЛАВАЮЩАЯ КНОПКА КОРЗИНЫ -->
<div class="floating-cart-bar" id="floating-bar" onclick="openCart()">
    <span>🛒 В корзине <b id="float-cnt">0</b> шт.</span>
    <span style="background:rgba(0,0,0,0.25);padding:5px 12px;border-radius:99px" id="float-sum">0 ₽ →</span>
</div>

<!-- ВЫЕЗЖАЮЩАЯ ШТОРКА КОРЗИНЫ -->
<div class="drawer-backdrop" id="cart-drawer">
    <div class="drawer-box">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
            <h2 style="margin:0;font-size:20px">🛒 Оформление заказа</h2>
            <button class="btn btn-ghost" onclick="closeCart()">✕</button>
        </div>
        <div id="cart-items" style="margin-bottom:14px"></div>

        <div style="background:var(--bg-panel);padding:14px;border-radius:14px;border:1px solid var(--border);margin-bottom:14px">
            <input type="tel" id="phone" placeholder="📞 Ваш номер телефона *" style="width:100%;margin-bottom:8px;font-weight:700">
            <select id="del-type" onchange="onDelTypeChange()" style="width:100%;margin-bottom:8px;font-weight:800">
                <option value="самовывоз">🏃 Самовывоз из ресторана (0 ₽)</option>
                <option value="доставка">🚗 Доставка курьером</option>
            </select>
            <input type="text" id="address" placeholder="🏠 Улица, дом, квартира, подъезд" oninput="if(this.value.trim().length>0){document.getElementById('del-type').value='доставка';onDelTypeChange();}" style="width:100%;margin-bottom:8px;">
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px" id="zone-chips"></div>
            <input type="text" id="s-comment" placeholder="💬 Комментарий (палочки, домофон, сдача с купюры)" style="width:100%;">
        </div>

        <div style="margin-bottom:14px">
            <div style="font-size:12px;font-weight:800;color:var(--text-muted);margin-bottom:6px">СПОСОБ ОПЛАТЫ:</div>
            <div style="display:flex;gap:6px">
                <div class="pay-chip active" id="pay-cash" onclick="setPay('cash')">💵 Наличные</div>
                <div class="pay-chip" id="pay-card" onclick="setPay('card')">💳 Карта</div>
                <div class="pay-chip" id="pay-sbp" onclick="setPay('sbp')">📱 СБП</div>
            </div>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:center;font-size:21px;font-weight:900;margin-bottom:14px">
            <span>Итого к оплате:</span>
            <span id="total-price" style="color:var(--accent)">0 ₽</span>
        </div>
        <button class="btn" style="width:100%;padding:16px;font-size:16px" onclick="submitOrder()">✅ ОФОРМИТЬ ЗАКАЗ</button>
    </div>
</div>

<script>
let cart = {};
let currentPay = 'cash';
let currentZone = '';
let currentFee = 0;
let activeCat = 'all';
let customZones = [];

// Инициализация картинок (с приоритетом фото из админки!)
document.querySelectorAll('.dish-auto-img').forEach(img => {
    img.src = window.getDishPhoto(img.dataset.name, img.dataset.cat, img.dataset.dbimg);
    img.onerror = function() {
        this.onerror = null;
        this.src = window.getDishPhoto(this.dataset.name, this.dataset.cat, '');
    };
});

// Показываем кнопку активного заказа, если клиент уже оформлял заказ
let lastOid = localStorage.getItem('last_krevetka_order');
if (lastOid) {
    document.getElementById('my-last-order-link').innerHTML = `<a href="/track/${lastOid}" class="btn btn-green">📡 Мой заказ #${lastOid}</a>`;
}

// Загружаем только ваши собственные зоны из БД (если они созданы)
fetch('/api/zones_custom').then(r=>r.json()).then(d => {
    customZones = d.zones || [];
    if (customZones.length > 0) {
        renderCustomZones();
    }
}).catch(()=>{});

function renderCustomZones() {
    let chipsBox = document.getElementById('zone-chips');
    let legendBox = document.getElementById('map-zones-legend');
    chipsBox.innerHTML = customZones.map((z, idx) =>
        `<div class="zone-chip" id="zchip-${idx}" onclick="selectCustomZone(${idx})">${z.name} (${z.fee}₽)</div>`
    ).join('');

    let hasPolygons = customZones.some(z => {
        try { return JSON.parse(z.polygon_coords || '[]').length >= 3; } catch(e) { return false; }
    });
    if (hasPolygons) {
        document.getElementById('map-section-wrapper').style.display = 'block';
        let map = L.map('custom-map').setView([66.036, 60.145], 12);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
        customZones.forEach((z, idx) => {
            try {
                let coords = JSON.parse(z.polygon_coords || '[]');
                if (coords.length >= 3) {
                    let poly = L.polygon(coords, {color: z.color || '#ff5e00', fillOpacity: 0.28, weight: 3}).addTo(map);
                    poly.bindTooltip(`<b>${z.name}</b>: ${z.fee} ₽`, {sticky: true});
                    poly.on('click', () => { selectCustomZone(idx); openCart(); });
                    legendBox.innerHTML += `<span class="h-pill" style="cursor:pointer;border-color:${z.color}" onclick="selectCustomZone(${idx})"><b style="color:${z.color}">●</b> ${z.name} — ${z.fee} ₽</span>`;
                }
            } catch(e) {}
        });
    }
}

function selectCustomZone(idx) {
    let z = customZones[idx];
    if (!z) return;
    document.getElementById('del-type').value = 'доставка';
    currentZone = z.name;
    currentFee = parseFloat(z.fee) || 0;
    document.querySelectorAll('.zone-chip').forEach((el, i) => el.classList.toggle('active', i === idx));
    renderCart();
}

function filterCategory(cat, btn) {
    activeCat = cat;
    document.querySelectorAll('.cat-chip').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    filterSearch();
}

function filterSearch() {
    let q = document.getElementById('site-search').value.toLowerCase().trim();
    document.querySelectorAll('.dish-card').forEach(card => {
        let mCat = (activeCat === 'all' || card.dataset.cat === activeCat);
        let mQ = (!q || card.dataset.name.includes(q));
        card.style.display = (mCat && mQ) ? 'flex' : 'none';
    });
}

function openCart() { document.getElementById('cart-drawer').style.display = 'flex'; renderCart(); }
function closeCart() { document.getElementById('cart-drawer').style.display = 'none'; }

function addToCart(id, name, price) {
    if (!cart[id]) cart[id] = { id, name, price, qty: 0 };
    cart[id].qty++;
    syncCardButtons();
    renderCart();
}

function changeQty(id, delta, name, price) {
    if (!cart[id] && delta > 0) cart[id] = { id, name, price, qty: 0 };
    if (!cart[id]) return;
    cart[id].qty += delta;
    if (cart[id].qty <= 0) delete cart[id];
    syncCardButtons();
    renderCart();
}

function syncCardButtons() {
    let totalCnt = 0, sub = 0;
    Object.values(cart).forEach(i => { totalCnt += i.qty; sub += i.qty * i.price; });
    document.getElementById('cart-badge').innerText = totalCnt;
    let fBar = document.getElementById('floating-bar');
    if (totalCnt > 0) {
        fBar.style.display = 'flex';
        document.getElementById('float-cnt').innerText = totalCnt;
        document.getElementById('float-sum').innerText = sub + ' ₽ →';
    } else {
        fBar.style.display = 'none';
    }
    document.querySelectorAll('[id^="ctrl-"]').forEach(box => {
        let id = parseInt(box.id.replace('ctrl-', ''));
        let card = box.closest('.dish-card');
        let title = card ? card.querySelector('.dish-title').innerText.replace(/'/g, "") : 'Блюдо';
        let price = card ? parseInt(card.querySelector('.dish-price').innerText) : 0;
        if (cart[id] && cart[id].qty > 0) {
            box.innerHTML = `<div class="qty-stepper">
                <button onclick="changeQty(${id}, -1, '${title}', ${price})">−</button>
                <b style="min-width:18px;text-align:center">${cart[id].qty}</b>
                <button onclick="changeQty(${id}, 1, '${title}', ${price})">+</button>
            </div>`;
        } else {
            box.innerHTML = `<button class="btn" onclick="addToCart(${id}, '${title}', ${price})">+ В корзину</button>`;
        }
    });
}

function setPay(method) {
    currentPay = method;
    ['cash', 'card', 'sbp'].forEach(m => document.getElementById('pay-' + m).classList.toggle('active', m === method));
}

function onDelTypeChange() {
    if (document.getElementById('del-type').value === 'самовывоз') {
        currentFee = 0;
        currentZone = '';
        document.querySelectorAll('.zone-chip').forEach(el => el.classList.remove('active'));
    }
    renderCart();
}

function renderCart() {
    let sub = 0, html = '';
    for (let id in cart) {
        let i = cart[id];
        sub += i.price * i.qty;
        html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)">
            <div><b>${i.name}</b><br><span style="font-size:12px;color:var(--text-muted)">${i.price} ₽ × ${i.qty} = ${i.price * i.qty} ₽</span></div>
            <div class="qty-stepper">
                <button onclick="changeQty(${id}, -1)">−</button>
                <b style="min-width:20px;text-align:center">${i.qty}</b>
                <button onclick="changeQty(${id}, 1)">+</button>
            </div>
        </div>`;
    }
    document.getElementById('cart-items').innerHTML = html || '<div style="text-align:center;color:var(--text-muted);padding:24px">Ваша корзина пока пуста</div>';
    let del = document.getElementById('del-type').value;
    let total = sub + (del === 'доставка' ? currentFee : 0);
    document.getElementById('total-price').innerText = total + ' ₽' + (del === 'доставка' && currentFee > 0 ? ` (вкл. дост. ${currentFee}₽)` : '');
}

function submitOrder() {
    let items = Object.values(cart).map(i => ({ id: i.id, name: i.name, qty: i.qty, price: i.price }));
    if (!items.length) return alert('Корзина пуста! Добавьте блюда.');
    let phone = document.getElementById('phone').value.trim();
    if (!phone) return alert('Укажите ваш номер телефона!');

    let delType = document.getElementById('del-type').value;
    let addr = document.getElementById('address').value.trim();
    if (addr.length > 0 && delType !== 'доставка') delType = 'доставка';
    if (delType === 'доставка' && !addr) return alert('Укажите ваш адрес доставки!');

    if (delType === 'доставка' && currentFee > 0) {
        items.push({ id: 99901, name: `Доставка (${currentZone || 'Курьер'})`, qty: 1, price: currentFee });
    }

    let comment = (document.getElementById('s-comment') ? document.getElementById('s-comment').value.trim() : '');

    fetch('/api/site_order_safe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            items: items,
            phone: phone,
            delivery_type: delType,
            address: delType === 'доставка' ? addr : 'Самовывоз',
            zone: delType === 'доставка' ? (currentZone || '') : '',
            comment: comment,
            payment_method: currentPay
        })
    }).then(r => r.json()).then(d => {
        if (d && (d.success || d.order_id)) {
            let oid = d.order_id || d.id;
            localStorage.setItem('last_krevetka_order', oid);
            cart = {};
            syncCardButtons();
            window.location.href = '/track/' + oid;
        } else {
            alert('Ошибка оформления: ' + (d.error || 'Попробуйте снова'));
        }
    }).catch(e => alert('Ошибка сети: ' + e.message));
}
</script>
</body></html>
"""

for tpl_name in ["public_site.html", "shop.html", "client.html"]:
    p = os.path.join(TEMPLATES_DIR, tpl_name)
    if os.path.exists(p) or tpl_name == "public_site.html":
        with open(p, "w", encoding="utf-8") as f:
            f.write(public_site_ultra)

# 6. ВИЗУАЛЬНЫЙ КОНСТРУКТОР ЗОН ДОСТАВКИ НА КАРТЕ (TEMPLATES/ZONES_EDITOR.HTML)
zones_editor_html = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Конструктор зон доставки — КРЕВЕТКА Pro</title>
<link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
.editor-grid { display: grid; grid-template-columns: 380px 1fr; gap: 20px; max-width: 1450px; margin: 20px auto; padding: 0 20px; height: calc(100vh - 95px); }
.editor-sidebar { background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; padding: 18px; display: flex; flex-direction: column; overflow-y: auto; }
#editor-map { width: 100%; height: 100%; border-radius: 16px; border: 1px solid var(--border); }
.zone-row { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
</style>
</head>
<body>
<div class="pro-topbar">
    <div class="pro-brand"><span>🗺️ КОНСТРУКТОР ЗОН ДОСТАВКИ</span><span class="pro-badge">КРЕВЕТКА PRO</span></div>
    <div class="pro-nav">
        <a href="/" class="btn btn-ghost">← В Кассу</a>
        <a href="/site" target="_blank" class="btn btn-blue">📱 Открыть Сайт</a>
        <a href="/admin" class="btn btn-ghost">⚙️ Админка</a>
    </div>
</div>

<div class="editor-grid">
    <div class="editor-sidebar">
        <h3 style="margin:0 0 8px 0">➕ Создать новую зону</h3>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px">
            1. Кликайте по карте справа, чтобы обвести нужный район точками.<br>
            2. Укажите название и стоимость доставки.<br>
            3. Нажмите «Сохранить зону».
        </div>
        <input type="text" id="z-name" placeholder="Название района (напр. Западный)" style="margin-bottom:8px;width:100%">
        <div style="display:grid;grid-template-columns:1fr 80px;gap:8px;margin-bottom:10px">
            <input type="number" id="z-fee" placeholder="Стоимость доставки (₽)" value="150">
            <input type="color" id="z-color" value="#ff5e00" style="height:42px;padding:4px;cursor:pointer">
        </div>
        <div style="display:flex;gap:8px;margin-bottom:18px">
            <button class="btn btn-ghost" style="flex:1" onclick="resetDraftPoints()">↺ Сбросить точки (<span id="pts-cnt">0</span>)</button>
            <button class="btn btn-green" style="flex:1.4" onclick="saveNewZone()">💾 Сохранить зону</button>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <h4 style="margin:0">Ваши активные зоны:</h4>
            <button onclick="clearAllZones()" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:12px;font-weight:800">Очистить все</button>
        </div>
        <div id="saved-zones-list" style="flex:1;overflow-y:auto"></div>
    </div>
    <div id="editor-map"></div>
</div>

<script>
let map = L.map('editor-map').setView([66.036, 60.145], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

let draftCoords = [];
let draftPolygon = null;
let draftMarkers = [];
let savedLayers = [];

map.on('click', function(e) {
    draftCoords.push([parseFloat(e.latlng.lat.toFixed(5)), parseFloat(e.latlng.lng.toFixed(5))]);
    document.getElementById('pts-cnt').innerText = draftCoords.length;
    let m = L.circleMarker(e.latlng, {radius: 5, color: '#fff', fillColor: '#ff5e00', fillOpacity: 1}).addTo(map);
    draftMarkers.push(m);
    if (draftPolygon) map.removeLayer(draftPolygon);
    draftPolygon = L.polygon(draftCoords, {color: document.getElementById('z-color').value, fillOpacity: 0.3}).addTo(map);
});

function resetDraftPoints() {
    draftCoords = [];
    document.getElementById('pts-cnt').innerText = '0';
    if (draftPolygon) { map.removeLayer(draftPolygon); draftPolygon = null; }
    draftMarkers.forEach(m => map.removeLayer(m));
    draftMarkers = [];
}

function saveNewZone() {
    let name = document.getElementById('z-name').value.trim();
    let fee = parseFloat(document.getElementById('z-fee').value) || 0;
    let color = document.getElementById('z-color').value;
    if (!name) return alert('Введите название зоны!');
    fetch('/api/zones_custom', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'save', name, fee, color, polygon_coords: JSON.stringify(draftCoords)})
    }).then(r=>r.json()).then(d => {
        if (d.success) {
            document.getElementById('z-name').value = '';
            resetDraftPoints();
            loadZones();
        }
    });
}

function deleteZone(id) {
    fetch('/api/zones_custom', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'delete', id})
    }).then(()=>loadZones());
}

function clearAllZones() {
    if (!confirm('Удалить все зоны доставки?')) return;
    fetch('/api/zones_custom', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'clear_all'})
    }).then(()=>loadZones());
}

function loadZones() {
    savedLayers.forEach(l => map.removeLayer(l));
    savedLayers = [];
    fetch('/api/zones_custom').then(r=>r.json()).then(d => {
        let list = d.zones || [];
        let box = document.getElementById('saved-zones-list');
        if (!list.length) {
            box.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Зон пока нет. Нарисуйте первую зону на карте справа!</div>';
            return;
        }
        box.innerHTML = list.map(z => `
            <div class="zone-row">
                <div>
                    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${z.color};margin-right:6px"></span>
                    <b>${z.name}</b> — <span style="color:var(--accent);font-weight:900">${z.fee} ₽</span>
                </div>
                <button class="btn btn-red" style="padding:4px 9px;font-size:11px" onclick="deleteZone(${z.id})">✕</button>
            </div>
        `).join('');
        list.forEach(z => {
            try {
                let c = JSON.parse(z.polygon_coords || '[]');
                if (c.length >= 3) {
                    let p = L.polygon(c, {color: z.color, fillOpacity: 0.25, weight: 2}).addTo(map);
                    p.bindTooltip(`<b>${z.name}</b> (${z.fee} ₽)`);
                    savedLayers.push(p);
                }
            } catch(e) {}
        });
    });
}
loadZones();
</script>
</body></html>
"""
with open(os.path.join(TEMPLATES_DIR, "zones_editor.html"), "w", encoding="utf-8") as f:
    f.write(zones_editor_html)

# 7. УЛЬТРА-ЭКРАН КУХНИ KDS С ТАЙМЕРАМИ ПРОСРОЧКИ И ЦЕХАМИ (TEMPLATES/KITCHEN.HTML)
kitchen_ultra = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Кухня KDS — КРЕВЕТКА Pro</title>
<link rel="stylesheet" href="/static/pro_style.css">
<script src="/static/zones_inta.js"></script>
<style>
.kds-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 18px; padding: 20px; }
.kds-card { background: var(--bg-card); border: 2px solid var(--border); border-radius: 16px; padding: 16px; display: flex; flex-direction: column; transition: 0.2s; }
.kds-card.sla-warn { border-color: var(--yellow); }
.kds-card.sla-late { border-color: var(--red); box-shadow: 0 0 22px rgba(239, 68, 68, 0.35); }
.kds-item { padding: 8px 10px; border-radius: 8px; background: var(--bg-panel); margin-bottom: 6px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-weight: 800; font-size: 15px; user-select: none; }
.kds-item.done-item { opacity: 0.38; text-decoration: line-through; background: rgba(16, 185, 129, 0.1); }
.station-badge { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 900; margin-left: 6px; }
</style>
</head>
<body>
<div class="pro-topbar">
    <div class="pro-brand"><span>🍳 КУХНЯ KDS</span><span class="pro-badge">ТАЙМЕРЫ ЦЕХОВ</span></div>
    <div class="pro-nav">
        <span style="font-size:13px;font-weight:800;color:var(--text-muted)">Активных чеков: <b id="kds-cnt" style="color:var(--accent)">0</b></span>
        <a href="/" class="btn btn-ghost">🖥️ Касса POS</a>
        <a href="/autopilot" class="btn btn-blue">🔪 Чек-лист Шефа</a>
        <button onclick="document.body.classList.toggle('light-theme')" class="btn btn-ghost">🌓</button>
    </div>
</div>

<div class="kds-grid" id="kds-board"></div>

<script>
let knownIds = new Set();
let crossedItems = JSON.parse(localStorage.getItem('kds_crossed') || '{}');

function toggleCrossItem(key) {
    crossedItems[key] = !crossedItems[key];
    localStorage.setItem('kds_crossed', JSON.stringify(crossedItems));
    loadKds();
}

function getStationBadge(name) {
    let n = (name || '').toLowerCase();
    if (n.includes('запеч')) return '<span class="station-badge" style="background:#ef4444;color:#fff">🔥 ЗАПЕЧ</span>';
    if (n.includes('темпур') || n.includes('жарен') || n.includes('вок') || n.includes('wok') || n.includes('суп') || n.includes('том ям')) return '<span class="station-badge" style="background:#f59e0b;color:#000">🍤 ГОРЯЧИЙ/WOK</span>';
    return '<span class="station-badge" style="background:#3b82f6;color:#fff">❄️ ХОЛОДНЫЙ</span>';
}

function setOrderStatus(id, st) {
    fetch('/api/set_status/' + id, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: st})
    }).then(() => loadKds());
}

function loadKds() {
    fetch('/api/orders').then(r=>r.json()).then(data => {
        let all = Array.isArray(data) ? data : (data.orders || []);
        let active = all.filter(o => o.status === 'new' || o.status === 'cooking');
        document.getElementById('kds-cnt').innerText = active.length;

        active.forEach(o => {
            if (!knownIds.has(o.id) && knownIds.size > 0) {
                window.playNewOrderBell();
            }
            knownIds.add(o.id);
        });

        let board = document.getElementById('kds-board');
        if (!active.length) {
            board.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);margin-top:80px;font-size:18px">🎉 На кухне чисто! Все заказы приготовлены.</div>';
            return;
        }

        board.innerHTML = active.map(o => {
            let mins = 0;
            if (o.created_at) {
                let dt = new Date(o.created_at.replace(' ', 'T'));
                if (!isNaN(dt)) mins = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 60000));
            }
            let slaClass = mins >= 25 ? 'sla-late' : (mins >= 15 ? 'sla-warn' : '');
            let timerColor = mins >= 25 ? 'var(--red)' : (mins >= 15 ? 'var(--yellow)' : 'var(--green)');

            let itemsHtml = (o.items || []).filter(i => !String(i.name).startsWith('Доставка')).map((it, idx) => {
                let k = `${o.id}_${idx}`;
                let isDone = crossedItems[k] ? 'done-item' : '';
                return `<div class="kds-item ${isDone}" onclick="toggleCrossItem('${k}')">
                    <span>${it.name} ${getStationBadge(it.name)}</span>
                    <b style="font-size:17px;color:var(--accent)">×${it.qty}</b>
                </div>`;
            }).join('');

            return `<div class="kds-card ${slaClass}">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                    <span style="font-size:20px;font-weight:900">#${o.id} • ${(o.delivery_type || '').toUpperCase()}</span>
                    <span style="background:var(--bg-panel);border:1px solid ${timerColor};color:${timerColor};padding:4px 10px;border-radius:99px;font-weight:900;font-size:13px">⏱ ${mins} мин</span>
                </div>
                ${o.comment ? `<div style="background:rgba(245,158,11,0.15);border:1px solid var(--yellow);color:#fbbf24;padding:8px 10px;border-radius:8px;font-size:13px;font-weight:800;margin-bottom:10px">💬 ${o.comment}</div>` : ''}
                <div style="flex:1;margin-bottom:12px">${itemsHtml}</div>
                <div style="display:flex;gap:8px">
                    ${o.status === 'new' ? `<button class="btn btn-yellow" style="flex:1;padding:12px" onclick="setOrderStatus(${o.id}, 'cooking')">👨‍🍳 ВЗЯТЬ В РАБОТУ</button>` : ''}
                    <button class="btn btn-green" style="flex:1.2;padding:12px" onclick="setOrderStatus(${o.id}, 'ready')">✅ ГОТОВО К ВЫДАЧЕ</button>
                </div>
            </div>`;
        }).join('');
    }).catch(()=>{});
}

loadKds();
setInterval(loadKds, 4000);
</script>
</body></html>
"""
with open(os.path.join(TEMPLATES_DIR, "kitchen.html"), "w", encoding="utf-8") as f:
    f.write(kitchen_ultra)

# 8. ДОБАВЛЯЕМ КНОПКУ КОНСТРУКТОРА ЗОН И CRM-ПОДСКАЗКУ В КАССУ (CASHIER.HTML)
cashier_path = os.path.join(TEMPLATES_DIR, "cashier.html")
if os.path.exists(cashier_path):
    with open(cashier_path, "r", encoding="utf-8") as f:
        c_html = f.read()
    if "/zones_editor" not in c_html:
        c_html = c_html.replace(
            '<a href="/admin" class="btn">⚙️ Админка</a>',
            '<a href="/zones_editor" class="btn btn-purple">🗺️ Редактор зон</a>\n            <a href="/admin" class="btn">⚙️ Админка</a>'
        )
    # Очищаем старые кнопки зон из кассы и подгружаем только кастомные зоны из /api/zones_custom
    old_zones_bar = """<div style="display:flex;gap:5px">
                    <div class="zone-pill" id="z-center" onclick="selectZoneManual('center')">Центр (0₽)</div>
                    <div class="zone-pill" id="z-zapad" onclick="selectZoneManual('zapad')">Западный (150₽)</div>
                    <div class="zone-pill" id="z-yug" onclick="selectZoneManual('yug')">Южный (250₽)</div>
                    <div class="zone-pill" id="z-verh" onclick="selectZoneManual('verh')">Верхняя Инта (1000₽)</div>
                </div>"""
    new_zones_bar = """<div style="display:flex;gap:5px;flex-wrap:wrap" id="pos-custom-zones"></div>"""
    c_html = c_html.replace(old_zones_bar, new_zones_bar)

    with open(cashier_path, "w", encoding="utf-8") as f:
        f.write(c_html)

print("✅ КРЕВЕТКА Pro Ultra успешно установлена!")