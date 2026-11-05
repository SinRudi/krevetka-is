import os

app_path = os.path.expanduser("~/my-apps/sushi_pos/app.py")

with open(app_path, "r", encoding="utf-8") as f:
    code = f.read()

# Исправляем неправильное объявление декоратора с несколькими путями в одном вызове
bad_dec = "@app.route('/api/site_order_safe', '/api/zones_custom', methods=['POST'])"
good_dec = """@app.route('/api/site_order_safe', methods=['POST'])
@app.route('/api/zones_custom', methods=['POST'])"""

if bad_dec in code:
    code = code.replace(bad_dec, good_dec)
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ Синтаксис маршрутов в app.py исправлен!")
else:
    print("⚠️ Строка не найдена, проверяем альтернативный вариант...")
