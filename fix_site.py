import sqlite3
import os

print("="*60)
print("1. ПРОВЕРКА БАЗЫ И ФОТО")
print("="*60)

try:
    conn = sqlite3.connect('sushi.db')
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, name, image FROM menu").fetchall()
    for r in rows:
        img = r['image']
        if img:
            # Убираем лишние пути, если они случайно записались
            img_clean = os.path.basename(img.replace('\\', '/'))
            if img_clean != img:
                conn.execute("UPDATE menu SET image=? WHERE id=?", (img_clean, r['id']))
            
            filepath = os.path.join('static', 'uploads', img_clean)
            if os.path.exists(filepath):
                print(f"✅ {r['name']}: файл {img_clean} найден на диске.")
            else:
                print(f"❌ {r['name']}: файл {img_clean} НЕ НАЙДЕН (возможно, удален).")
        else:
            print(f"📷 {r['name']}: фото не загружено.")
    conn.commit()
    conn.close()
except Exception as e:
    print("Ошибка базы:", e)

print("\n" + "="*60)
print("2. ПЕРЕЗАПИСЬ САЙТА (Исправляем сломанный HTML)")
print("="*60)

html = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>КРЕВЕТКА — Доставка</title>
<link rel="stylesheet" href="/static/pro_style.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
.site-hero { background: linear-gradient(135deg, #131b2e 0%, #24142c 100%); border-bottom: 1px solid var(--border); padding: 24px 18px; text-align: center; }
.cats-nav { max-width: 1280px; margin: 14px auto 0 auto; padding: 0 18px; display: flex; gap: 8px; overflow-x: auto; }
.cat-tab { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-main); padding: 10px 18px; border-radius: 10px; font-weight: 800; cursor: pointer; white-space: nowrap;}
.cat-tab.active { background: var(--accent); color: #fff; }
.site-grid { max-width: 1280px; margin: 0 auto; padding: 18px; display: grid; grid-template-columns: repeat(auto-fill, minmax(255px, 1fr)); gap: 18px; }
.site-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; display: flex; flex-direction: column; }
.card-img-wrap { width: 100%; height: 185px; position: relative; background: #101520; display: flex; align-items: center; justify-content: center; color: #4a5568; font-weight: 900; }
.card-img-wrap img { width: 100%; height: 100%; object-fit: cover; position: absolute; top: 0; left: 0; }
.card-cat-badge { position: absolute; top: 10px; left: 10px; background: rgba(11,15,23,0.85); color: var(--accent); padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: 900; z-index: 2; }
.card-body { padding: 14px 16px; display: flex; flex-direction: column; flex: 1; }
.drawer-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.75); display: none; justify-content: flex-end; z-index: 9999; }
.drawer-box { width: 100%; max-width: 500px; background: var(--bg-card); height: 100%; display: flex; flex-direction: column; padding: 18px; overflow-y: auto; }
.zone-chip { flex: 1; padding: 8px 4px; font-size: 11px; font-weight: 800; border: 1px solid var(--border); background: var(--bg-panel); border-radius: 8px; cursor: pointer; text-align: center; }
.zone-chip.active { background: var(--purple); color: #fff; }
.pay-chip { flex: 1; padding: 10px 6px; font-size: 13px; font-weight: 900; border: 1px solid var(--border); background: var(--bg-panel); border-radius: 8px; cursor: pointer; text-align: center; }
.pay-chip.active { background: var(--accent); color: #fff; }
#inta-map { width: 100%; height: 380px; border-radius: 12px; margin-top: 12px; background: #1e1e24; }
</style>
</head>
<body>
<div class="pro-topbar">
    <div class="pro-brand"><span>🦐 КРЕВЕТКА</span><span class="pro-badge">ДОСТАВКА</span></div>
    <div style="display:flex;gap:10px;align-items:center">
        <button class="btn btn-ghost" onclick="document.getElementById('map-wrapper').scrollIntoView({behavior:'smooth'})">🗺️ Карта</button>
        <button class="btn" id="cart-btn-top" onclick="openCart()">🛒 Корзина (<span id="cart-count">0</span>)</button>
    </div>
</div>

<div class="site-hero"><h1 style="margin:0;font-size:26px">Ресторан доставки «КРЕВЕТКА»</h1></div>

<div class="cats-nav">
    <button class="cat-tab active" onclick="filterCat('all', this)">🍱 Все блюда</button>
    {% for c in categories %}
    <button class="cat-tab" onclick="filterCat('{{ c.category }}', this)">{{ c.category }}</button>
    {% endfor %}
</div>

<div class="site-grid" id="menu-grid">
    {% for m in menu %}
    <div class="site-card" data-cat="{{ m.category }}">
        <div class="card-img-wrap">
            <span>📷 Нет фото</span>
            {% if m.image and m.image != 'None' and m.image != '' %}
                <img src="/static/uploads/{{ m.image }}" onerror="this.remove();">
            {% endif %}
            <span class="card-cat-badge">{{ m.category }}</span>
        </div>
        <div class="card-body">
            <div style="font-size:17px;font-weight:900;margin-bottom:6px;">{{ m.name }}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:8px;border-top:1px solid var(--border)">
                <span style="font-size:20px;font-weight:900;color:var(--accent)">{{ m.price }} ₽</span>
                <button class="btn add-btn" data-id="{{ m.id }}" data-name="{{ m.name|e }}" data-price="{{ m.price }}">+ В корзину</button>
            </div>
        </div>
    </div>
    {% endfor %}
</div>

<div id="map-wrapper" style="max-width:1280px; margin:20px auto; padding:0 18px;">
    <h2 style="margin:0;font-size:20px">🗺️ Карта зон доставки</h2>
    <div id="inta-map"></div>
</div>

<div class="drawer-backdrop" id="cart-drawer">
    <div class="drawer-box">
        <div style="display:flex;justify-content:space-between;margin-bottom:14px">
            <h2 style="margin:0;font-size:20px">🛒 Корзина</h2>
            <button class="btn btn-ghost" onclick="closeCart()">✕</button>
        </div>
        <div id="cart-items" style="margin-bottom:14px"></div>
        <div style="background:var(--bg-panel);padding:12px;border-radius:12px;margin-bottom:12px">
            <input type="tel" id="phone" placeholder="📞 Телефон *" style="width:100%;margin-bottom:8px;">
            <select id="del-type" onchange="onDelTypeChange()" style="width:100%;margin-bottom:8px;">
                <option value="самовывоз">🏃 Самовывоз (0 ₽)</option>
                <option value="доставка">🚗 Доставка</option>
            </select>
            <input type="text" id="address" placeholder="🏠 Адрес" style="width:100%;margin-bottom:8px;">
            <div style="display:flex;gap:4px;flex-wrap:wrap" id="zone-chips"></div>
        </div>
        <div style="display:flex;gap:6px;margin-bottom:14px">
            <div class="pay-chip active" id="pay-cash" onclick="setPay('cash')">💵 Наличные</div>
            <div class="pay-chip" id="pay-card" onclick="setPay('card')">💳 Карта</div>
            <div class="pay-chip" id="pay-sbp" onclick="setPay('sbp')">📱 СБП</div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:20px;font-weight:900;margin-bottom:14px;">
            <span>Итого:</span>
            <span id="total-price" style="color:var(--accent)">0 ₽</span>
        </div>
        <button class="btn" style="width:100%;padding:16px;" onclick="submitOrder()">✅ ОФОРМИТЬ</button>
    </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
    let cart = {};
    let currentPay = 'cash';
    let currentZone = null;
    let currentFee = 0;
    let zonesList = [];

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.add-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                let id = this.getAttribute('data-id');
                let name = this.getAttribute('data-name');
                let price = parseInt(this.getAttribute('data-price'));
                addToCart(id, name, price);
            });
        });
        setTimeout(initMap, 500);
    });

    function addToCart(id, name, price) {
        if (!cart[id]) cart[id] = { id, name, price, qty: 0 };
        cart[id].qty++;
        updateBadge();
        document.getElementById('cart-btn-top').style.background = '#30d158';
        setTimeout(() => document.getElementById('cart-btn-top').style.background = '', 300);
    }

    function updateBadge() {
        let count = Object.values(cart).reduce((sum, item) => sum + item.qty, 0);
        document.getElementById('cart-count').innerText = count;
    }

    function openCart() { document.getElementById('cart-drawer').style.display = 'flex'; renderCart(); }
    function closeCart() { document.getElementById('cart-drawer').style.display = 'none'; }

    function renderCart() {
        let html = '';
        let subtotal = 0;
        for (let id in cart) {
            let item = cart[id];
            subtotal += item.price * item.qty;
            html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)">
                <div><b>${item.name}</b><br><span style="font-size:12px;color:var(--text-muted)">${item.price} ₽ × ${item.qty}</span></div>
                <div style="display:flex;gap:6px;align-items:center">
                    <button class="btn btn-red" style="padding:4px 10px" onclick="changeQty('${id}', -1)">-</button>
                    <b>${item.qty}</b>
                    <button class="btn btn-green" style="padding:4px 10px" onclick="changeQty('${id}', 1)">+</button>
                </div>
            </div>`;
        }
        document.getElementById('cart-items').innerHTML = html || '<div style="color:var(--text-muted);text-align:center;padding:20px;">Корзина пуста</div>';
        let delType = document.getElementById('del-type').value;
        let total = subtotal + (delType === 'доставка' ? currentFee : 0);
        document.getElementById('total-price').innerText = total + ' ₽';
    }

    function changeQty(id, delta) {
        if (!cart[id]) return;
        cart[id].qty += delta;
        if (cart[id].qty <= 0) delete cart[id];
        updateBadge();
        renderCart();
    }

    function setPay(method) {
        currentPay = method;
        ['cash', 'card', 'sbp'].forEach(m => document.getElementById('pay-' + m).classList.toggle('active', m === method));
    }

    function onDelTypeChange() {
        let type = document.getElementById('del-type').value;
        if (type === 'самовывоз') {
            currentFee = 0;
            currentZone = null;
            document.querySelectorAll('.zone-chip').forEach(el => el.classList.remove('active'));
        }
        renderCart();
    }

    function submitOrder() {
        let items = Object.values(cart).map(i => ({ id: i.id, name: i.name, qty: i.qty, price: i.price }));
        if (!items.length) return alert('Корзина пуста!');
        let phone = document.getElementById('phone').value.trim();
        if (!phone) return alert('Укажите телефон!');
        
        let delType = document.getElementById('del-type').value;
        let addr = document.getElementById('address').value.trim();
        if (delType === 'доставка' && !addr) return alert('Укажите адрес!');
        if (delType === 'доставка' && !currentZone) return alert('Выберите зону на карте или в списке!');

        if (delType === 'доставка' && currentFee > 0) {
            items.push({ id: 99901, name: `Доставка (${currentZone})`, qty: 1, price: currentFee });
        }

        fetch('/api/public_order', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                items, phone, delivery_type: delType,
                address: delType === 'доставка' ? addr : 'Самовывоз',
                zone: delType === 'доставка' ? currentZone : '',
                comment: document.getElementById('s-comment').value.trim(),
                payment_method: currentPay
            })
        }).then(r => r.json()).then(d => {
            if (d.success) {
                window.location.href = '/track/' + d.order_id;
            } else {
                alert('Ошибка: ' + (d.error || 'Не удалось отправить'));
            }
        }).catch(() => alert('Ошибка соединения с сервером!'));
    }

    function filterCat(cat, btn) {
        document.querySelectorAll('.cat-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.site-card').forEach(c => {
            c.style.display = (cat === 'all' || c.dataset.cat === cat) ? 'flex' : 'none';
        });
    }

    function initMap() {
        if (typeof L === 'undefined') {
            document.getElementById('inta-map').innerHTML = '<div style="padding:20px;text-align:center;color:#888;">Карта недоступна</div>';
            return;
        }
        
        try {
            let map = L.map('inta-map').setView([66.039, 60.131], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

            fetch('/api/zones').then(r => r.json()).then(zones => {
                zonesList = zones;
                let chipsHtml = '';
                zones.forEach(z => {
                    if (z.polygon_data) {
                        try {
                            let poly = L.polygon(JSON.parse(z.polygon_data), { color: '#3b82f6', fillOpacity: 0.28 }).addTo(map);
                            poly.on('click', () => selectZone(z));
                        } catch(e) {}
                    }
                    chipsHtml += `<div class="zone-chip" id="zone-${z.id}" onclick="selectZoneById(${z.id})">${z.name} ${z.price}₽</div>`;
                });
                document.getElementById('zone-chips').innerHTML = chipsHtml;
            });
        } catch(e) { console.log("Ошибка карты:", e); }
    }

    function selectZoneById(id) {
        let z = zonesList.find(x => x.id === id);
        if (z) selectZone(z);
    }

    function selectZone(z) {
        currentZone = z.name;
        currentFee = z.price;
        document.getElementById('del-type').value = 'доставка';
        document.querySelectorAll('.zone-chip').forEach(el => el.classList.remove('active'));
        let el = document.getElementById('zone-' + z.id);
        if (el) el.classList.add('active');
        renderCart();
    }
</script>
</body></html>
"""
with open('templates/public_site.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("✅ templates/public_site.html успешно перезаписан!")