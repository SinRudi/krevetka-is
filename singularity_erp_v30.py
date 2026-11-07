import os
import sqlite3
from datetime import datetime, timedelta
from flask import request, session, jsonify, Response


def register_singularity_v30(app, g):
    get_db = g["get_db"]

    @app.after_request
    def inject_singularity_js(response):
        if response.content_type and response.content_type.startswith("text/html"):
            try:
                html = response.get_data(as_text=True)
                tag = '<script src="/static/singularity_v30.js?v=3001" defer></script>'
                if "singularity_v30.js" not in html and "</body>" in html:
                    html = html.replace("</body>", tag + "</body>", 1)
                    response.set_data(html)
            except Exception:
                pass
        return response

    # === 1. АНТИ-ИНФЛЯЦИОННЫЙ ЩИТ МАРЖИ + АВТО-ПРАЙСИНГ ===
    @app.route("/api/singularity/margin_shield")
    def api_singularity_margin_shield():
        db = get_db()
        target_fc = float(request.args.get("target_fc", 28.0) or 28.0)

        menu_rows = db.execute(
            "SELECT id, name, category, price FROM menu ORDER BY category, name"
        ).fetchall()
        ing_rows = db.execute(
            "SELECT id, name, unit, cost_price, stock FROM ingredients ORDER BY name"
        ).fetchall()

        shield_items = []
        loss_alerts = 0

        for m in menu_rows:
            recs = db.execute(
                """
                SELECT r.amount, i.name as ing_name, i.cost_price, i.unit
                FROM recipes r
                JOIN ingredients i ON r.ingredient_id = i.id
                WHERE r.menu_id = ?
                """,
                (m["id"],)
            ).fetchall()

            cost = 0.0
            for rc in recs:
                cost += float(rc["amount"] or 0) * float(rc["cost_price"] or 0)
            cost = round(cost, 1)

            price = int(m["price"] or 0)
            current_fc = round((cost / price * 100.0), 1) if price > 0 else 0.0
            # Округление рекомендуемой цены до красивых 10 рублей
            ideal_price = int(round((cost / (target_fc / 100.0)) / 10.0) * 10) if cost > 0 else price
            diff_price = ideal_price - price

            status = "OK"
            if cost > 0 and current_fc > target_fc + 4.0:
                status = "DANGER"
                loss_alerts += 1
            elif cost > 0 and current_fc > target_fc:
                status = "WARN"

            shield_items.append({
                "id": m["id"],
                "name": m["name"],
                "category": m["category"],
                "price": price,
                "cost": cost,
                "current_fc": current_fc,
                "ideal_price": ideal_price,
                "diff_price": diff_price,
                "margin_rub": int(round(price - cost)),
                "status": status
            })

        return jsonify({
            "target_fc": target_fc,
            "loss_alerts": loss_alerts,
            "items": shield_items,
            "ingredients": [dict(i) for i in ing_rows]
        })

    @app.route("/api/singularity/update_ing_cost", methods=["POST"])
    def api_singularity_update_ing_cost():
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Доступ запрещён"}), 403
        data = request.get_json(force=True, silent=True) or {}
        ing_id = int(data.get("ingredient_id", 0) or 0)
        new_cost = float(data.get("cost_price", 0) or 0)
        if ing_id > 0 and new_cost >= 0:
            db = get_db()
            db.execute("UPDATE ingredients SET cost_price=? WHERE id=?", (new_cost, ing_id))
            db.commit()
        return jsonify({"success": True})

    @app.route("/api/singularity/apply_auto_prices", methods=["POST"])
    def api_singularity_apply_auto_prices():
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Доступ запрещён"}), 403

        data = request.get_json(force=True, silent=True) or {}
        target_fc = float(data.get("target_fc", 28.0) or 28.0)
        only_danger = bool(data.get("only_danger", True))

        db = get_db()
        menu_rows = db.execute("SELECT id, price FROM menu").fetchall()
        updated_cnt = 0

        for m in menu_rows:
            recs = db.execute(
                """
                SELECT r.amount, i.cost_price
                FROM recipes r
                JOIN ingredients i ON r.ingredient_id = i.id
                WHERE r.menu_id = ?
                """,
                (m["id"],)
            ).fetchall()
            cost = sum(float(r["amount"] or 0) * float(r["cost_price"] or 0) for r in recs)
            if cost <= 0:
                continue
            price = int(m["price"] or 0)
            cur_fc = (cost / price * 100.0) if price > 0 else 100.0
            if only_danger and cur_fc <= target_fc + 2.0:
                continue

            new_price = int(round((cost / (target_fc / 100.0)) / 10.0) * 10)
            if new_price > price:
                db.execute("UPDATE menu SET price=? WHERE id=?", (new_price, m["id"]))
                updated_cnt += 1

        db.commit()
        return jsonify({"success": True, "updated_count": updated_cnt})

    # === 2. RFM-РАДАР УДЕРЖАНИЯ ГОСТЕЙ + ПРЕДИКТИВНЫЙ ПЛАН ЗАГОТОВОК + БАТЧИНГ КУРЬЕРОВ ===
    @app.route("/api/singularity/monopoly_intel")
    def api_singularity_monopoly_intel():
        db = get_db()
        now = datetime.now()

        # А. RFM-анализ клиентской базы по телефонам из заказов
        rows = db.execute(
            """
            SELECT phone, MAX(address) as last_addr, COUNT(*) as orders_cnt,
                   SUM(total) as ltv, MAX(created_at) as last_order_at
            FROM orders
            WHERE status != 'cancelled' AND phone IS NOT NULL AND length(trim(phone)) >= 6
            GROUP BY phone
            ORDER BY ltv DESC
            """
        ).fetchall()

        rfm_clients = []
        sleeping_vips = 0
        for r in rows:
            last_str = (r["last_order_at"] or "")[:10]
            try:
                dt_last = datetime.strptime(last_str, "%Y-%m-%d")
                days_silent = max(0, (now - dt_last).days)
            except Exception:
                days_silent = 0

            cnt = int(r["orders_cnt"] or 1)
            ltv = int(r["ltv"] or 0)

            if days_silent >= 14 and (cnt >= 2 or ltv >= 2000):
                segment = "🔥 РИСК ОТТОКА VIP"
                seg_color = "#ef4444"
                sleeping_vips += 1
            elif cnt >= 3 or ltv >= 3500:
                segment = "👑 ЧЕМПИОН (Лояльный)"
                seg_color = "#10b981"
            elif days_silent >= 21:
                segment = "💤 Спящий гость"
                seg_color = "#eab308"
            else:
                segment = "✨ Активный гость"
                seg_color = "#38bdf8"

            clean_phone = "".join(ch for ch in (r["phone"] or "") if ch.isdigit())
            if clean_phone.startswith("8") and len(clean_phone) == 11:
                clean_phone = "7" + clean_phone[1:]

            rfm_clients.append({
                "phone": r["phone"],
                "wa_phone": clean_phone,
                "address": r["last_addr"] or "г. Инта",
                "orders_cnt": cnt,
                "ltv": ltv,
                "days_silent": days_silent,
                "segment": segment,
                "color": seg_color
            })

        # Б. Предиктивный расчёт утренних заготовок для смены 4/1 (с учётом пятницы/выходных)
        weekday = now.weekday()  # 4=Пт, 5=Сб, 6=Вс
        is_peak_day = weekday in (4, 5, 6)
        day_multiplier = 1.45 if is_peak_day else 1.0

        since_14 = (now - timedelta(days=14)).strftime("%Y-%m-%d")
        recent_orders = db.execute(
            "SELECT COUNT(*) as c FROM orders WHERE status!='cancelled' AND date(created_at)>=?",
            (since_14,)
        ).fetchone()["c"]
        avg_daily_orders = max(12.0, (float(recent_orders or 0) / 14.0)) * day_multiplier
        est_rolls_portions = int(round(avg_daily_orders * 2.6))

        # На 1 порцию ролла (8 кусочков): ~115 г готового суши-риса, ~45 г лосося, ~35 г творожного сыра
        prep_forecast = [
            {
                "station": "Рисоварка (Утро)",
                "item": "Суши-Рис готовый (заправленный Мицукан)",
                "recommended_kg": round(est_rolls_portions * 0.115, 1),
                "raw_note": f"Сухого зерна: ~{round(est_rolls_portions * 0.115 * 0.46, 1)} кг (на {est_rolls_portions} порц. роллов по 8 шт.)"
            },
            {
                "station": "Рыбный цех",
                "item": "Филе Лосося (чистая нарезка на Филадельфию)",
                "recommended_kg": round(est_rolls_portions * 0.042, 1),
                "raw_note": "С учётом коэффициента разделки тушки (отход 24%)"
            },
            {
                "station": "Холодный цех",
                "item": "Крем-чиз (Сыр творожный в кондитерских мешках)",
                "recommended_kg": round(est_rolls_portions * 0.036, 1),
                "raw_note": f"Фасовка по мешкам по 0.8 кг ({max(2, int(round(est_rolls_portions * 0.036 / 0.8)))} шт.)"
            },
            {
                "station": "Горячий цех (Запечённые)",
                "item": "Замес шапочек «Лава» и «Спайси»",
                "recommended_kg": round(est_rolls_portions * 0.022, 1),
                "raw_note": "На базе икры масаго, майонеза и соуса кимчи"
            }
        ]

        # В. Умная маршрутизация и связка рейсов курьеров по районам Инты
        active_deliv = db.execute(
            """
            SELECT id, address, total, status, created_at
            FROM orders
            WHERE status IN ('new', 'cooking', 'ready') AND lower(COALESCE(delivery_type,'доставка')) != 'самовывоз'
            ORDER BY id ASC
            """
        ).fetchall()

        clusters = {
            "Маршрут #1 • Центр / Город": [],
            "Маршрут #2 • Западный район": [],
            "Маршрут #3 • Южный / Сельхоз": [],
            "Маршрут #4 • Верхняя Инта / Станция": []
        }

        for od in active_deliv:
            addr = (od["address"] or "").lower()
            if any(w in addr for w in ("верхн", "станц", "вокзал", "депо")):
                k = "Маршрут #4 • Верхняя Инта / Станция"
            elif any(w in addr for w in ("южн", "сельхоз", "кирова", "чайковск")):
                k = "Маршрут #3 • Южный / Сельхоз"
            elif any(w in addr for w in ("запад", "заречн", "геолог", "шахт")):
                k = "Маршрут #2 • Западный район"
            else:
                k = "Маршрут #1 • Центр / Город"

            clusters[k].append({
                "id": od["id"],
                "address": od["address"] or "Адрес не указан",
                "total": int(od["total"] or 0),
                "status": od["status"]
            })

        route_bundles = [{"route_name": k, "orders": v, "count": len(v)} for k, v in clusters.items()]

        return jsonify({
            "is_peak_day": is_peak_day,
            "est_daily_orders": int(round(avg_daily_orders)),
            "est_rolls_portions": est_rolls_portions,
            "sleeping_vips_count": sleeping_vips,
            "rfm_clients": rfm_clients[:25],
            "prep_forecast": prep_forecast,
            "route_bundles": route_bundles
        })

    # === 3. ЖИВОЙ ТРЕКЕР ЗАКАЗА ДЛЯ ГОСТЯ (/live/<order_id>) ===
    @app.route("/live/<int:order_id>")
    def route_live_order_tracker(order_id):
        db = get_db()
        o = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            return Response("Заказ не найден", status=404)

        items = db.execute("SELECT name, qty FROM order_items WHERE order_id=?", (order_id,)).fetchall()
        items_html = "".join(
            f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.08);'>"
            f"<span>{it['name']} (8 шт.)</span><b>× {it['qty']}</b></div>"
            for it in items
        )

        st = (o["status"] or "new").lower()
        step = 1 if st == "new" else (2 if st == "cooking" else (3 if st == "ready" else 4))

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Трекер заказа #{order_id} • КРЕВЕТКА</title>
<meta http-equiv="refresh" content="8">
<style>
  body {{ margin:0; background:#090b10; color:#f8fafc; font-family:system-ui,sans-serif; padding:20px; }}
  .box {{ max-width:480px; margin:0 auto; background:#131722; border:1px solid rgba(255,105,0,0.35); border-radius:16px; padding:22px; box-shadow:0 12px 32px rgba(0,0,0,0.5); }}
  .step {{ display:flex; align-items:center; gap:12px; padding:10px 12px; border-radius:10px; margin-bottom:8px; font-weight:700; font-size:14px; }}
  .done {{ background:rgba(16,185,129,0.16); border:1px solid #10b981; color:#34d399; }}
  .wait {{ background:rgba(255,255,255,0.04); color:#64748b; }}
</style>
</head>
<body>
  <div class="box">
    <div style="font-size:12px; color:#ff6900; font-weight:800; text-transform:uppercase;">🍤 Служба доставки «КРЕВЕТКА» • г. Инта</div>
    <h2 style="margin:6px 0 16px;">Заказ #{order_id} в реальном времени</h2>
    <div class="step {'done' if step>=1 else 'wait'}">1. ✅ Заказ принят кассой и передан на экран шефа</div>
    <div class="step {'done' if step>=2 else 'wait'}">2. 🔪 Повар крутит роллы (строгий стандарт 8 кусочков)</div>
    <div class="step {'done' if step>=3 else 'wait'}">3. 🔥 Упаковка в термобокс и комплектация соусами</div>
    <div class="step {'done' if step>=4 else 'wait'}">4. 🛵 Курьер мчится к вам ({o['address'] or 'Самовывоз'})</div>
    <h4 style="margin:18px 0 8px; color:#38bdf8;">Состав вашего заказа:</h4>
    {items_html}
    <div style="margin-top:14px; display:flex; justify-content:space-between; font-size:18px; font-weight:900;">
      <span>К оплате:</span><span style="color:#10b981;">{o['total']} ₽</span>
    </div>
  </div>
</body>
</html>"""
        return Response(html, mimetype="text/html")
