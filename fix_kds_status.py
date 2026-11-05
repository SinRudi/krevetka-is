import os
import re

app_path = os.path.expanduser("~/my-apps/sushi_pos/app.py")

with open(app_path, "r", encoding="utf-8") as f:
    code = f.read()

# Проверяем, есть ли уже обработчик /api/set_status/
if "/api/set_status/" not in code:
    status_route = """
@app.route('/api/set_status/<int:order_id>', methods=['POST'])
def api_set_order_status(order_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
        new_status = data.get('status') or 'cooking'
        db = get_db()
        db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
        try:
            db.execute("INSERT INTO order_status_history (order_id, status) VALUES (?, ?)", (order_id, new_status))
        except Exception:
            pass
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
"""
    if "if __name__ ==" in code:
        code = code.replace("if __name__ ==", status_route + "\nif __name__ ==")
    else:
        code += "\n" + status_route

with open(app_path, "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Маршрут смены статуса добавлен в app.py!")