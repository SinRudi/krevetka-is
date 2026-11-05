import os
import re

BASE_DIR = os.path.expanduser("~/my-apps/sushi_pos")
app_path = os.path.join(BASE_DIR, "app.py")
kitchen_path = os.path.join(BASE_DIR, "templates", "kitchen.html")

if os.path.exists(app_path):
    with open(app_path, "r", encoding="utf-8") as f:
        code = f.read()

    code = code.replace("'/api/create_order'", "'/api/create_order', '/api/set_status'")
    
    # Удаляем старый эндпоинт set_status, если он был задан некорректно
    code = re.sub(r"@app\.route\('/api/set_status/.*?def\s+\w+\(.*?\):.*?(?=@app\.route|\Z)", "", code, flags=re.DOTALL)

    status_route = """
@app.route('/api/set_status/<int:order_id>', methods=['POST', 'GET'])
def api_set_order_status(order_id):
    try:
        data = request.get_json(force=True, silent=True) or request.form.to_dict() or {}
        new_status = data.get('status') or request.args.get('status') or 'cooking'
        db = get_db()
        db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
        try:
            db.execute("INSERT INTO order_status_history (order_id, status) VALUES (?, ?)", (order_id, new_status))
        except Exception:
            pass
        db.commit()
        return jsonify({'success': True, 'status': new_status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
"""
    code += "\n" + status_route
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ Эндпоинт смены статуса успешно обновлен в app.py")

# 2. Обновляем kitchen.html с обработкой ошибок и гарантированным обновлением KDS
if os.path.exists(kitchen_path):
    with open(kitchen_path, "r", encoding="utf-8") as f:
        k_html = f.read()

    old_fn = re.search(r"function\s+setOrderStatus\s*\(.*?\}.*?\}", k_html, re.DOTALL)
    new_fn = """function setOrderStatus(id, st) {
    fetch('/api/set_status/' + id, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: st})
    })
    .then(async r => {
        let text = await r.text();
        try { return JSON.parse(text); }
        catch(e) { throw new Error('Ошибка сервера: ' + text.slice(0, 100)); }
    })
    .then(d => {
        if (d && d.success) {
            loadKds();
        } else {
            alert('Не удалось обновить статус: ' + (d.error || 'ошибка'));
        }
    })
    .catch(err => {
        alert('Ошибка связи с сервером: ' + err.message);
    });
}"""

    if old_fn:
        k_html = k_html.replace(old_fn.group(0), new_fn)
    else:
        k_html += f"<script>{new_fn}</script>"

    with open(kitchen_path, "w", encoding="utf-8") as f:
        f.write(k_html)
    print("✅ Функция setOrderStatus обновлена в kitchen.html")
