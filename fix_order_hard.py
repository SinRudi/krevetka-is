import os
import re
import glob

BASE_DIR = os.path.expanduser("~/my-apps/sushi_pos")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
app_path = os.path.join(BASE_DIR, "app.py")

if os.path.exists(app_path):
    with open(app_path, "r", encoding="utf-8") as f:
        code = f.read()

    # Убираем неразрывные пробелы, если они попали в app.py
    code = code.replace('\u00a0', ' ')

    code = re.sub(
        "def check_csrf():\n    if request.path in ('/api/site_order_safe', '/api/public_order', '/api/create_order'): return None",
        code
    )

    with open(app_path, "w", encoding="utf-8") as f:
        f.write(code)

# 2. НАДЕЖНАЯ ФУНКЦИЯ SUBMITORDER ДЛЯ ЛЮБОГО ШАБЛОНА САЙТА
bulletproof_submit = """function submitOrder() {
        try {
            let rawCart = (typeof cart !== 'undefined' && Object.keys(cart).length) ? cart : (typeof sCart !== 'undefined' ? sCart : {});
            let items = Object.values(rawCart).map(i => ({
                id: i.id || 0,
                name: i.name || 'Блюдо',
                qty: parseInt(i.qty || i.quantity || 1),
                price: parseFloat(i.price || 0)
            }));
            if (!items.length) return alert('Корзина пуста! Добавьте блюда в заказ.');

            let phoneEl = document.getElementById('phone') || document.getElementById('s-phone');
            let phone = phoneEl ? phoneEl.value.trim() : '';
            if (!phone) return alert('Укажите ваш номер телефона!');

            let delEl = document.getElementById('del-type') || document.getElementById('s-del-type');
            let delType = delEl ? delEl.value : 'самовывоз';

            let addrEl = document.getElementById('address') || document.getElementById('s-address');
            let addr = addrEl ? addrEl.value.trim() : '';

            if (addr.length > 0 && delType !== 'доставка') {
                delType = 'доставка';
                if (delEl) delEl.value = 'доставка';
            }
            if (delType === 'доставка' && !addr) return alert('Укажите адрес доставки!');

            let fee = (typeof currentFee !== 'undefined') ? (parseFloat(currentFee) || 0) : ((typeof sFee !== 'undefined') ? (parseFloat(sFee) || 0) : 0);
            let zoneName = (typeof currentZone !== 'undefined' && currentZone) ? currentZone : 'Доставка';

            if (delType === 'доставка' && fee > 0) {
                items.push({ id: 99901, name: `Доставка (${zoneName})`, qty: 1, price: fee });
            }

            let commEl = document.getElementById('s-comment') || document.getElementById('comment');
            let comment = commEl ? commEl.value.trim() : '';

            let payMethod = (typeof currentPay !== 'undefined') ? currentPay : ((typeof sPay !== 'undefined') ? sPay : 'cash');

            let headers = {'Content-Type': 'application/json'};
            }

            let payload = {
                items: items,
                phone: phone,
                delivery_type: delType,
                address: delType === 'доставка' ? addr : 'Самовывоз',
                zone: delType === 'доставка' ? zoneName : '',
                comment: comment,
                payment_method: payMethod
            };

            fetch('/api/site_order_safe', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(payload)
            })
            .then(async r => {
                let text = await r.text();
                try { return JSON.parse(text); }
                catch(e) { throw new Error('Ответ сервера (' + r.status + '): ' + text.slice(0, 150)); }
            })
            .then(d => {
                if (d && (d.success || d.order_id || d.id)) {
                    let oid = d.order_id || d.id;
                    localStorage.setItem('last_krevetka_order', oid);
                    cart = {};
                    if (typeof sCart !== 'undefined') sCart = {};
                    window.location.href = '/track/' + oid;
                } else {
                    alert('Ошибка оформления: ' + ((d && d.error) ? d.error : 'Неизвестная ошибка'));
                }
            })
            .catch(err => {
                alert('Ошибка связи с сервером: ' + err.message);
            });
        } catch (err) {
            alert('Ошибка в скрипте корзины: ' + err.message);
        }
    }
    window.submitPublicOrder = submitOrder;"""

# 3. ОБНОВЛЯЕМ ВСЕ ШАБЛОНЫ ВИТРИНЫ
for tpl_path in glob.glob(os.path.join(TEMPLATES_DIR, "*.html")):
    fname = os.path.basename(tpl_path)
    if fname in ("cashier.html", "kitchen.html", "warehouse.html", "autopilot.html", "receipt.html", "track.html"):
        continue

    with open(tpl_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Очищаем неразрывные пробелы DeepSeek
    html = html.replace('\u00a0', ' ')

    # Добавляем поле комментария под адресом/зонами, если его нет
    if 'id="s-comment"' not in html and 'id="comment"' not in html and 'id="zone-chips"' in html:
        html = html.replace(
            'id="zone-chips"></div>',
            'id="zone-chips"></div>\n            <input type="text" id="s-comment" placeholder="💬 Комментарий к заказу" style="width:100%;margin-top:8px;">'
        )

    # Заменяем старую функцию submitOrder целиком до конца <script> или следующей функции
    if "function submitOrder()" in html:
        pattern = re.compile(r"function\s+submitOrder\s*\(\s*\)\s*\{.*?(?=</script>)", re.DOTALL)
        if pattern.search(html):
            html = pattern.sub(bulletproof_submit + "\n", html)
            print(f"✅ Полностью заменена submitOrder() в {fname}")

    with open(tpl_path, "w", encoding="utf-8") as f:
        f.write(html)
