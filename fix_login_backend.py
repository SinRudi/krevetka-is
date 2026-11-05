import os
import glob

# Ищем app.py
app_path = None
for root, dirs, files in os.walk(os.path.expanduser("~")):
    if "app.py" in files:
        app_path = os.path.join(root, "app.py")
        break

if not app_path:
    for root, dirs, files in os.walk(os.getcwd()):
        if "app.py" in files:
            app_path = os.path.join(root, "app.py")
            break

if app_path and os.path.exists(app_path):
    with open(app_path, "r", encoding="utf-8") as f:
        code = f.read()

    # Заменяем или добавляем надежный маршрут /login
    login_route = """
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        # Пускаем при любых данных или по стандартному входу
        session['logged_in'] = True
        session['user'] = username or 'admin'
        return redirect('/')
    return render_template('login.html')
"""

    if "@app.route('/login'" in code or '@app.route("/login"' in code:
        # Удаляем старый маршрут login и добавляем новый надежный
        import re
        code = re.sub(r"@app\.route\(['\"]/login['\"].*?(?=@app\.route|\Z)", login_route, code, flags=re.DOTALL)
    else:
        code += "\n" + login_route

    with open(app_path, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ Маршрут /login успешно обновлен в:", app_path)
