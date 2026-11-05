import os

# Ищем папку templates в системе
templates_dir = None
for root, dirs, files in os.walk("/"):
    if "templates" in dirs and not any(x in root for x in ["/usr", "/lib", "/proc", "/sys"]):
        templates_dir = os.path.join(root, "templates")
        break

if templates_dir:
    os.makedirs(templates_dir, exist_ok=True)
    login_html_path = os.path.join(templates_dir, "login.html")
    
    # Создаем чистую форму входа, которая гарантированно не вызывает ошибки 400
    login_content = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Вход в систему — КРЕВЕТКА Pro</title>
    <link rel="stylesheet" href="/static/pro_style.css">
</head>
<body style="display:flex;align-items:center;justify-content:center;height:100vh;background:var(--bg-main, #0b0f17);color:var(--text-main, #f8fafc);font-family:sans-serif;">
    <div style="background:var(--bg-card, #151c28);border:1px solid var(--border, #263147);padding:30px;border-radius:16px;width:100%;max-width:380px;box-shadow:0 10px 25px rgba(0,0,0,0.3);">
        <h2 style="margin-top:0;text-align:center;color:var(--accent, #ff6b00);">🦐 КРЕВЕТКА Pro</h2>
        <form method="POST" action="/login">
            <div style="margin-bottom:14px;">
                <label style="display:block;font-size:12px;font-weight:800;margin-bottom:6px;color:var(--text-muted, #94a3b8);">ЛОГИН</label>
                <input type="text" name="username" required style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border, #263147);background:var(--bg-main, #0b0f17);color:#fff;box-sizing:border-box;">
            </div>
            <div style="margin-bottom:20px;">
                <label style="display:block;font-size:12px;font-weight:800;margin-bottom:6px;color:var(--text-muted, #94a3b8);">ПАРОЛЬ</label>
                <input type="password" name="password" required style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border, #263147);background:var(--bg-main, #0b0f17);color:#fff;box-sizing:border-box;">
            </div>
            <button type="submit" style="width:100%;padding:12px;background:var(--accent, #ff6b00);color:#fff;border:none;border-radius:8px;font-weight:900;cursor:pointer;">ВОЙТИ</button>
        </form>
    </div>
</body>
</html>
"""
    with open(login_html_path, "w", encoding="utf-8") as f:
        f.write(login_content)
    print("✅ Создан чистый шаблон login.html в:", login_html_path)
else:
    print("⚠️ Папка templates не найдена.")
