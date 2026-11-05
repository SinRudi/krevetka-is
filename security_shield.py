import os
import hmac
import hashlib
import secrets
from datetime import datetime
from flask import request, session, redirect, url_for, jsonify


def log_sec_event(get_db, event_type, details=""):
    try:
        db = get_db()
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()
        user = session.get("username", "anonymous")
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "INSERT INTO security_audit_log (created_at, event_type, username, ip_addr, details) VALUES (?,?,?,?,?)",
            (now_s, event_type, user, ip, details[:250])
        )
        db.commit()
    except Exception:
        pass


def validate_order_items(data, get_db):
    """Reject malformed carts and client-supplied prices/names not in the active menu."""
    if not isinstance(data, dict):
        return "Некорректные данные заказа"

    items = data.get("items")
    if not isinstance(items, list) or not items or len(items) > 50:
        return "В заказе должно быть от 1 до 50 позиций"

    db = get_db()
    for item in items:
        if not isinstance(item, dict):
            return "Некорректная позиция заказа"

        raw_id = item.get("id", item.get("menu_id"))
        raw_qty = item.get("qty", 1)
        raw_price = item.get("price")
        name = item.get("name")
        mods = item.get("mods", "")

        # Accept integer IDs and digit strings for compatibility, but reject bools/floats.
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)) or not str(raw_id).isdigit():
            return "Некорректный товар в заказе"
        if isinstance(raw_qty, bool) or not isinstance(raw_qty, (int, str)) or not str(raw_qty).isdigit():
            return "Количество должно быть целым числом от 1 до 99"
        if not 1 <= int(raw_qty) <= 99:
            return "Количество должно быть целым числом от 1 до 99"
        if isinstance(raw_price, bool) or not isinstance(raw_price, (int, str)) or not str(raw_price).isdigit():
            return "Некорректная цена товара"
        if not isinstance(name, str) or len(name) > 200:
            return "Некорректное название товара"
        if not isinstance(mods, str) or len(mods) > 300:
            return "Комментарий к позиции слишком длинный"

        menu_item = db.execute(
            "SELECT name, price FROM menu WHERE id=? AND available=1",
            (int(raw_id),)
        ).fetchone()
        if not menu_item:
            return "Одна из позиций больше недоступна — обновите меню"
        if int(raw_price) != int(menu_item["price"] or 0) or name != menu_item["name"]:
            return "Цена или название товара изменились — обновите меню и повторите заказ"

    return None


def init_security_shield(app, get_db):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    secret_file = os.path.join(base_dir, ".sushi_secret")
    if os.path.exists(secret_file):
        with open(secret_file, "r", encoding="utf-8") as f:
            sk = f.read().strip()
    else:
        sk = secrets.token_hex(32)
        with open(secret_file, "w", encoding="utf-8") as f:
            f.write(sk)
        os.chmod(secret_file, 0o600)

    app.config["SECRET_KEY"] = sk
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PROPAGATE_EXCEPTIONS"] = False

    def get_csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(24)
        return session["_csrf_token"]

    app.jinja_env.globals["csrf_token"] = get_csrf_token

    def is_external_tunnel_request():
        host = (request.host or "").lower()
        fwd = request.headers.get("X-Forwarded-For", "").strip()
        if ".lhr.life" in host or ".ngrok" in host or fwd:
            return True
        return False

    @app.before_request
    def enforce_rbac_and_csrf():
        path = request.path or "/"
        if path.startswith("/static/") or path in ("/manifest.json", "/sw.js", "/favicon.ico"):
            return None

        # 1. 4G-ФАЙРВОЛ: блокируем доступ к /admin, /accounting снаружи через туннель
        if is_external_tunnel_request():
            allowed_ext = (
                "/site", "/track", "/rate", "/login", "/logout", "/courier",
                "/api/public_order", "/api/check_promo", "/api/detect_zone",
                "/api/orders", "/api/set_status/", "/api/current_role", "/api/staff_shift/close_my"
            )
            if not any(path == p or path.startswith(p) for p in allowed_ext):
                log_sec_event(get_db, "4G_FIREWALL_BLOCK", f"Blocked external access to {path}")
                return "🔒 Доступ к управлению и финансам разрешён только внутри локальной Wi-Fi сети точки.", 403

        # 2. РОЛЕВОЙ КОНТРОЛЬ (RBAC)
        role = session.get("role")
        uid = session.get("user_id")

        if uid and role == "courier":
            courier_allowed = (
                "/courier", "/login", "/logout",
                "/api/orders", "/api/set_status/", "/api/current_role", "/api/staff_shift/close_my"
            )
            if not any(path == p or path.startswith(p) for p in courier_allowed):
                if path.startswith("/api/"):
                    return jsonify({"error": "Доступ запрещён для роли Курьер"}), 403
                return redirect(url_for("courier"))

        if uid and role == "kitchen":
            kitchen_allowed = (
                "/kitchen", "/login", "/logout",
                "/api/orders", "/api/set_status/", "/api/current_role",
                "/api/erp/live_metrics", "/api/staff_shift/close_my"
            )
            if not any(path == p or path.startswith(p) for p in kitchen_allowed):
                if path.startswith("/api/"):
                    return jsonify({"error": "Доступ запрещён для роли Повар"}), 403
                return redirect(url_for("kitchen"))

        if uid and role == "cashier":
            if path.startswith("/accounting") or path.startswith("/analytics") or path.startswith("/api/accounting"):
                if not session.get("can_view_finance"):
                    return "Доступ к финансовому контуру закрыт администратором", 403
            if path.startswith("/admin/users") or path.startswith("/admin/zone_rate") or path.startswith("/admin/backup_db"):
                return "Управление штатом и базой доступно только Администратору", 403

        # Validate item identity and price from the database, never trust the browser's cart values.
        if request.method == "POST" and path in ("/api/public_order", "/api/create_order"):
            payload = request.get_json(silent=True)
            validation_error = validate_order_items(payload, get_db)
            if validation_error:
                return jsonify({"success": False, "error": validation_error}), 400

        # 3. СТРОГАЯ ПРОВЕРКА CSRF-ТОКЕНА НА ИЗМЕНЯЮЩИХ ЗАПРОСАХ
        if request.method in ("POST", "PUT", "DELETE"):
            if path in ("/api/public_order", "/api/check_promo", "/login"):
                origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
                if origin and (request.host not in origin):
                    log_sec_event(get_db, "CSRF_ORIGIN_BLOCK", f"Origin mismatch on {path}")
                    return jsonify({"error": "Origin mismatch"}), 403
                return None

            expected_token = session.get("_csrf_token")
            sent_token = (
                request.headers.get("X-CSRF-Token")
                or request.form.get("_csrf_token")
                or request.form.get("csrf_token")
            )
            if not expected_token or not sent_token or not hmac.compare_digest(str(expected_token), str(sent_token)):
                log_sec_event(get_db, "CSRF_BLOCK", f"Missing or invalid CSRF token on {path}")
                return jsonify({"error": "Запрос отклонён защитой CSRF (обновите страницу)"}), 403

        return None

    @app.after_request
    def apply_security_headers_and_csrf(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self';"

        if response.content_type and response.content_type.startswith("text/html"):
            try:
                token = get_csrf_token()
                html = response.get_data(as_text=True)
                csrf_snippet = (
                    f'<meta name="csrf-token" content="{token}">'
                    '<script>(function(){'
                    f'const token="{token}";'
                    'const origFetch=window.fetch;'
                    'window.fetch=function(url,opts){opts=opts||{};opts.headers=opts.headers||{};'
                    'if(!(opts.headers instanceof Headers)){opts.headers["X-CSRF-Token"]=token;}'
                    'return origFetch(url,opts);};'
                    'function injectForms(){document.querySelectorAll("form").forEach(function(f){'
                    'if(!f.querySelector(\'input[name="_csrf_token"]\')){'
                    'const i=document.createElement("input");i.type="hidden";i.name="_csrf_token";i.value=token;f.appendChild(i);'
                    '}});}'
                    'document.addEventListener("DOMContentLoaded",injectForms);'
                    'setTimeout(injectForms,500);'
                    '})();</script>'
                )
                if 'name="csrf-token"' not in html and "</head>" in html:
                    html = html.replace("</head>", csrf_snippet + "</head>", 1)
                    response.set_data(html)
            except Exception:
                pass
        return response

    @app.errorhandler(404)
    def handle_404(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Маршрут не найден"}), 404
        return "Страница не найдена (404). <a href='/'>Вернуться на главную</a>", 404

    @app.errorhandler(500)
    def handle_500(e):
        log_sec_event(get_db, "SERVER_ERROR_500", f"Path: {request.path}")
        if request.path.startswith("/api/"):
            return jsonify({"error": "Внутренняя ошибка сервера"}), 500
        return "Внутренняя ошибка операции (500). <a href='/'>Обновить</a>", 500
