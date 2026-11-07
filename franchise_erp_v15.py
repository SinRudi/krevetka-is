import os
import sqlite3
from datetime import datetime, timedelta
from flask import request, session, jsonify, Response


def ensure_franchise_schema(db):
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS franchise_branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            city TEXT,
            concept TEXT DEFAULT 'Суши + Бургеры',
            royalty_pct REAL DEFAULT 5.0,
            marketing_pct REAL DEFAULT 1.5,
            sla_target_min INTEGER DEFAULT 38,
            is_flagship INTEGER DEFAULT 0
        );
        """)
        cnt = db.execute("SELECT COUNT(*) as c FROM franchise_branches").fetchone()["c"]
        if cnt == 0:
            db.execute("""
                INSERT INTO franchise_branches (code, name, city, concept, royalty_pct, marketing_pct, sla_target_min, is_flagship)
                VALUES
                ('INTA-01', 'Флагманская точка «Креветка»', 'г. Инта (Центр)', 'Роллы (8 шт.) + Бургеры', 0.0, 0.0, 35, 1),
                ('FR-KOMI-02', 'Партнёрская точка #2 (Тест сети)', 'Респ. Коми (Партнёр)', 'Роллы (8 шт.) + Бургеры', 5.0, 1.5, 40, 0)
            """)
        db.commit()
    except Exception:
        pass


def register_franchise_v15(app, g):
    get_db = g["get_db"]

    @app.after_request
    def inject_franchise_ui(response):
        if response.content_type and response.content_type.startswith("text/html"):
            try:
                html = response.get_data(as_text=True)
                assets = (
                    '<link rel="stylesheet" href="/static/franchise_v15.css?v=1500">'
                    '<script src="/static/franchise_v15.js?v=1500" defer></script>'
                )
                if "franchise_v15.js" not in html and "</body>" in html:
                    html = html.replace("</body>", assets + "</body>", 1)
                    response.set_data(html)
            except Exception:
                pass
        return response

    @app.route("/api/franchise/overview")
    def api_franchise_overview():
        db = get_db()
        ensure_franchise_schema(db)

        days = int(request.args.get("days", 30) or 30)
        since_s = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        today_s = datetime.now().strftime("%Y-%m-%d")

        stat = db.execute("""
            SELECT COUNT(*) as cnt,
                   COALESCE(SUM(total), 0) as rev,
                   COALESCE(SUM(cost), 0) as fc,
                   COALESCE(SUM(courier_fee), 0) as cfee
            FROM orders
            WHERE status != 'cancelled' AND date(created_at) >= ?
        """, (since_s,)).fetchone()

        today_stat = db.execute("""
            SELECT COUNT(*) as cnt, COALESCE(SUM(total), 0) as rev
            FROM orders
            WHERE status != 'cancelled' AND date(created_at) = ?
        """, (today_s,)).fetchone()

        rev = int(stat["rev"] or 0)
        cnt = int(stat["cnt"] or 0)
        fc = int(round(float(stat["fc"] or 0)))
        cfee = int(stat["cfee"] or 0)
        avg_check = int(round(rev / cnt)) if cnt > 0 else 0

        # Проверяем соблюдение стандарта 8 кусочков и наличие бургерных позиций
        menu_rows = db.execute("SELECT id, name, category, price FROM menu").fetchall()
        rolls_8pcs_ok = sum(1 for m in menu_rows if "10" not in (m["name"] or ""))
        burger_items = sum(1 for m in menu_rows if "бургер" in (m["category"] or "").lower() or "бургер" in (m["name"] or "").lower())

        branches = db.execute("SELECT * FROM franchise_branches ORDER BY is_flagship DESC, id ASC").fetchall()
        branch_list = []
        for b in branches:
            if b["is_flagship"]:
                b_rev = rev
                b_orders = cnt
                b_royalty = 0
                b_status = "ФЛАГМАН (Эталон сети)"
            else:
                # Прогнозная модель партнёрской точки на базе метрик флагмана
                b_rev = int(round(rev * 0.85)) if rev > 0 else 420000
                b_orders = int(round(cnt * 0.85)) if cnt > 0 else 380
                b_royalty = int(round(b_rev * ((float(b["royalty_pct"]) + float(b["marketing_pct"])) / 100.0)))
                b_status = f"Роялти {b['royalty_pct']}% + Маркетинг {b['marketing_pct']}%"

            branch_list.append({
                "code": b["code"],
                "name": b["name"],
                "city": b["city"],
                "concept": b["concept"],
                "orders": b_orders,
                "revenue": b_rev,
                "royalty_due": b_royalty,
                "sla_target": b["sla_target_min"],
                "status": b_status,
                "is_flagship": bool(b["is_flagship"])
            })

        return jsonify({
            "days": days,
            "flagship_revenue": rev,
            "flagship_orders": cnt,
            "today_revenue": int(today_stat["rev"] or 0),
            "today_orders": int(today_stat["cnt"] or 0),
            "avg_check": avg_check,
            "food_cost": fc,
            "courier_cost": cfee,
            "menu_total": len(menu_rows),
            "rolls_8pcs_compliant": rolls_8pcs_ok,
            "burger_items_count": burger_items,
            "branches": branch_list
        })

    @app.route("/api/franchise/add_burger_preset", methods=["POST"])
    def api_franchise_add_burger_preset():
        if session.get("role") not in ("admin", "cashier"):
            return jsonify({"error": "Только для администратора"}), 403

        db = get_db()
        presets = [
            ("Смэш-Бургер «Двойной Чеддер»", "Бургеры", 490, "Две сочные говяжьи котлеты smash, булочка бриошь, двойной чеддер, маринованный огурец, фирменный соус"),
            ("Криспи Бургер «Креветка & Спайси»", "Бургеры", 540, "Тигровые креветки в темпуре, свежий айсберг, соус спайси-манго, булочка бриошь"),
            ("Трюфельный Бургер BBQ", "Бургеры", 520, "Мраморная говядина, бекон на гриле, карамелизированный лук, трюфельный айоли"),
            ("Картофель Фри с пармезаном", "Закуски", 210, "Хрустящий картофель фри, тёртый пармезан, чесночное масло")
        ]
        added = 0
        for name, cat, price, desc in presets:
            ex = db.execute("SELECT id FROM menu WHERE name=?", (name,)).fetchone()
            if not ex:
                db.execute(
                    "INSERT INTO menu (name, category, price, description, stop_list) VALUES (?,?,?,?,0)",
                    (name, cat, price, desc)
                )
                added += 1
        db.commit()
        return jsonify({"success": True, "added": added})

    @app.route("/api/tv_orders")
    def api_tv_orders():
        db = get_db()
        rows = db.execute("""
            SELECT id, status, created_at
            FROM orders
            WHERE status IN ('new', 'cooking', 'ready')
            ORDER BY id DESC LIMIT 24
        """).fetchall()
        cooking = [r["id"] for r in rows if r["status"] in ("new", "cooking")]
        ready = [r["id"] for r in rows if r["status"] == "ready"]
        return jsonify({"cooking": cooking, "ready": ready})

    @app.route("/tv_board")
    def route_tv_board():
        html = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Табло Готовности • КРЕВЕТКА IS</title>
<style>
  body { margin:0; background:#07090e; color:#f8fafc; font-family:system-ui,-apple-system,sans-serif; overflow:hidden; }
  .tv-header { display:flex; justify-content:space-between; align-items:center; padding:18px 36px; background:#0f131d; border-bottom:2px solid #ff6900; }
  .tv-brand { font-size:28px; font-weight:900; letter-spacing:1px; color:#ff6900; }
  .tv-clock { font-size:26px; font-weight:800; color:#38bdf8; }
  .tv-grid { display:grid; grid-template-columns:1fr 1fr; height:calc(100vh - 80px); }
  .tv-col { padding:28px 36px; border-right:1px solid rgba(255,255,255,0.08); }
  .tv-col-title { font-size:26px; font-weight:900; text-transform:uppercase; margin-bottom:24px; display:flex; align-items:center; gap:12px; }
  .num-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:16px; }
  .num-card { font-size:44px; font-weight:900; text-align:center; padding:22px 10px; border-radius:16px; }
  .card-cook { background:rgba(234,179,8,0.12); border:2px solid #eab308; color:#fde047; }
  .card-ready { background:rgba(22,163,74,0.18); border:3px solid #22c55e; color:#4ade80; box-shadow:0 0 25px rgba(34,197,94,0.35); animation:pulse 1.8s infinite; }
  @keyframes pulse { 0%,100%{transform:scale(1);} 50%{transform:scale(1.03);} }
</style>
</head>
<body>
  <div class="tv-header">
    <div class="tv-brand">🍤 КРЕВЕТКА • ТАБЛО ЗАКАЗОВ (РОЛЛЫ 8 ШТ. & БУРГЕРЫ)</div>
    <div class="tv-clock" id="tv-time">--:--</div>
  </div>
  <div class="tv-grid">
    <div class="tv-col">
      <div class="tv-col-title" style="color:#eab308;">🔥 ГОТОВИТСЯ НА КУХНЕ</div>
      <div class="num-grid" id="col-cooking"></div>
    </div>
    <div class="tv-col">
      <div class="tv-col-title" style="color:#22c55e;">✅ ГОТОВО К ВЫДАЧЕ</div>
      <div class="num-grid" id="col-ready"></div>
    </div>
  </div>
<script>
  let knownReady = new Set();
  function beepReady() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(1174, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.25, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(); osc.stop(ctx.currentTime + 0.6);
    } catch(e){}
  }
  function refreshBoard() {
    const now = new Date();
    document.getElementById('tv-time').textContent = now.toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
    fetch('/api/tv_orders').then(r=>r.json()).then(d=>{
      document.getElementById('col-cooking').innerHTML = (d.cooking||[]).map(id=>`<div class="num-card card-cook">#${id}</div>`).join('');
      document.getElementById('col-ready').innerHTML = (d.ready||[]).map(id=>`<div class="num-card card-ready">#${id}</div>`).join('');
      (d.ready||[]).forEach(id=>{
        if(!knownReady.has(id)) { knownReady.add(id); beepReady(); }
      });
    }).catch(()=>{});
  }
  refreshBoard();
  setInterval(refreshBoard, 3000);
</script>
</body>
</html>"""
        return Response(html, mimetype="text/html")
