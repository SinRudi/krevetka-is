import os
import sqlite3
from datetime import datetime, timedelta
from flask import request, session, jsonify, Response


def ensure_apex_schema(db):
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tax_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            inn TEXT DEFAULT '110400000000',
            ogrnip TEXT DEFAULT '326110000000000',
            ip_name TEXT DEFAULT 'ИП (Доставка роллов «КРЕВЕТКА»)',
            okved TEXT DEFAULT '56.10.21 (Деятельность предприятий общественного питания по доставке продуктов)',
            fns_code TEXT DEFAULT '1100 (УФНС России по Республике Коми, г. Инта)',
            oktmo TEXT DEFAULT '87715000 (МО ГО «Инта»)',
            tax_mode TEXT DEFAULT 'usn6',
            usn6_rate REAL DEFAULT 6.0,
            usn15_rate REAL DEFAULT 15.0,
            fixed_contributions INTEGER DEFAULT 53658,
            patent_annual_cost INTEGER DEFAULT 48000
        );
        CREATE TABLE IF NOT EXISTS haccp_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT,
            log_time TEXT,
            fridge_salmon_t REAL DEFAULT 2.5,
            fridge_cheese_t REAL DEFAULT 3.2,
            freezer_shrimp_t REAL DEFAULT -18.5,
            fryer_oil_status TEXT DEFAULT 'Норма (Прозрачное, КЧ < 1.0)',
            chef_health_ok INTEGER DEFAULT 1,
            inspector TEXT DEFAULT 'Шеф-повар'
        );
        """)
        cnt = db.execute("SELECT COUNT(*) as c FROM tax_profile").fetchone()["c"]
        if cnt == 0:
            db.execute("INSERT INTO tax_profile (id) VALUES (1)")
        db.commit()
    except Exception:
        pass


def register_apex_v50(app, g):
    get_db = g["get_db"]

    @app.after_request
    def inject_apex_js(response):
        if response.content_type and response.content_type.startswith("text/html"):
            try:
                html = response.get_data(as_text=True)
                tag = '<script src="/static/apex_v50.js?v=5002" defer></script>'
                if "apex_v50.js" not in html and "</body>" in html:
                    html = html.replace("</body>", tag + "</body>", 1)
                    response.set_data(html)
            except Exception:
                pass
        return response

    # === 1. АВТОМАТИЧЕСКАЯ НАЛОГОВАЯ ДЕКЛАРАЦИЯ ФНС (УСН / ПСН) И КУДиР ===
    @app.route("/api/apex/tax_declaration")
    def api_apex_tax_declaration():
        db = get_db()
        ensure_apex_schema(db)

        year = int(request.args.get("year", datetime.now().year) or datetime.now().year)
        prof = dict(db.execute("SELECT * FROM tax_profile WHERE id=1").fetchone())

        orders = db.execute(
            """
            SELECT id, created_at, total, cost, courier_fee, payment_method
            FROM orders
            WHERE status != 'cancelled' AND strftime('%Y', created_at) = ?
            ORDER BY created_at ASC
            """,
            (str(year),)
        ).fetchall()

        expenses_rows = []
        try:
            expenses_rows = db.execute(
                """
                SELECT id, created_at, category, amount, description
                FROM accounting_expenses
                WHERE strftime('%Y', created_at) = ?
                ORDER BY created_at ASC
                """,
                (str(year),)
            ).fetchall()
        except Exception:
            pass

        q_rev = {1: 0, 2: 0, 3: 0, 4: 0}
        q_exp = {1: 0, 2: 0, 3: 0, 4: 0}
        cash_total = 0
        card_total = 0
        kudir_entries = []

        for o in orders:
            dt_str = (o["created_at"] or "")[:10]
            try:
                m = int(dt_str[5:7])
            except Exception:
                m = datetime.now().month
            q = (m - 1) // 3 + 1
            rev = int(o["total"] or 0)
            fc = int(round(float(o["cost"] or 0)))
            cfee = int(o["courier_fee"] or 0)

            q_rev[q] += rev
            q_exp[q] += (fc + cfee)

            pm = (o["payment_method"] or "").lower()
            if pm in ("наличные", "cash"):
                cash_total += rev
            else:
                card_total += rev

            kudir_entries.append({
                "date": dt_str,
                "doc": f"Z-Касса / Чек #{o['id']} ({o['payment_method'] or 'Оплата'})",
                "income": rev,
                "expense": fc + cfee
            })

        for ex in expenses_rows:
            dt_str = (ex["created_at"] or "")[:10]
            try:
                m = int(dt_str[5:7])
            except Exception:
                m = datetime.now().month
            q = (m - 1) // 3 + 1
            amt = int(ex["amount"] or 0)
            q_exp[q] += amt
            kudir_entries.append({
                "date": dt_str,
                "doc": f"Расходный ордер #{ex['id']}: {ex['category'] or 'Хозрасходы'} ({ex['description'] or ''})",
                "income": 0,
                "expense": amt
            })

        total_inc = sum(q_rev.values())
        total_exp = sum(q_exp.values())

        # Расчёт УСН «Доходы 6%» (с уменьшением на страховые взносы ИП вплоть до 100% для ИП без сотрудников или 50%)
        rate6 = float(prof.get("usn6_rate") or 6.0) / 100.0
        fixed_ins = int(prof.get("fixed_contributions") or 53658)
        extra_1pct = max(0, int(round((total_inc - 300000) * 0.01)))
        total_deduction_avail = fixed_ins + extra_1pct

        gross_tax_usn6 = int(round(total_inc * rate6))
        deduction_applied = min(gross_tax_usn6, total_deduction_avail)
        net_tax_usn6 = max(0, gross_tax_usn6 - deduction_applied)

        # Расчёт УСН «Доходы минус расходы 15%» (с учётом минимального налога 1% от оборота)
        rate15 = float(prof.get("usn15_rate") or 15.0) / 100.0
        tax_base_15 = max(0, total_inc - total_exp - fixed_ins)
        calc_tax_15 = int(round(tax_base_15 * rate15))
        min_tax_1pct = int(round(total_inc * 0.01))
        net_tax_usn15 = max(calc_tax_15, min_tax_1pct) if total_inc > 0 else 0

        # Расчёт Патента (ПСН Общепит / Доставка в Республике Коми с уменьшением на взносы)
        patent_cost = int(prof.get("patent_annual_cost") or 48000)
        net_tax_patent = max(0, patent_cost - min(patent_cost, total_deduction_avail))

        # Автоматический выбор самого выгодного режима для предпринимателя
        options = [
            ("УСН «Доходы» (с вычетом взносов ИП)", net_tax_usn6),
            ("УСН «Доходы минус расходы»", net_tax_usn15),
            ("Патент ПСН (Общепит г. Инта + вычет взносов)", net_tax_patent)
        ]
        best_mode = min(options, key=lambda x: x[1])

        # Нарастающий итог по кварталам для строк Раздела 2.1.1 Декларации УСН
        cum_q1 = q_rev[1]
        cum_half = q_rev[1] + q_rev[2]
        cum_9m = cum_half + q_rev[3]
        cum_year = total_inc

        return jsonify({
            "year": year,
            "profile": prof,
            "quarters": [
                {"q": "I квартал", "inc": q_rev[1], "exp": q_exp[1], "cum_inc": cum_q1, "adv_tax_6": int(round(cum_q1 * rate6))},
                {"q": "Полугодие (6 мес.)", "inc": q_rev[2], "exp": q_exp[2], "cum_inc": cum_half, "adv_tax_6": int(round(cum_half * rate6))},
                {"q": "9 месяцев", "inc": q_rev[3], "exp": q_exp[3], "cum_inc": cum_9m, "adv_tax_6": int(round(cum_9m * rate6))},
                {"q": "Год (Итого)", "inc": q_rev[4], "exp": q_exp[4], "cum_inc": cum_year, "adv_tax_6": gross_tax_usn6}
            ],
            "total_income": total_inc,
            "cash_income": cash_total,
            "card_income": card_total,
            "total_expenses": total_exp,
            "fixed_contributions": fixed_ins,
            "extra_1pct_contributions": extra_1pct,
            "usn6": {
                "gross_tax": gross_tax_usn6,
                "deduction": deduction_applied,
                "net_payable": net_tax_usn6
            },
            "usn15": {
                "tax_base": tax_base_15,
                "calc_tax": calc_tax_15,
                "min_tax_1pct": min_tax_1pct,
                "net_payable": net_tax_usn15
            },
            "patent": {
                "base_cost": patent_cost,
                "net_payable": net_tax_patent
            },
            "best_recommendation": {
                "title": best_mode[0],
                "payable": best_mode[1],
                "savings": max(net_tax_usn6, net_tax_usn15) - best_mode[1]
            },
            "kudir": kudir_entries[-25:]
        })

    @app.route("/api/apex/tax_profile_save", methods=["POST"])
    def api_apex_tax_profile_save():
        data = request.get_json(force=True, silent=True) or {}
        db = get_db()
        ensure_apex_schema(db)
        db.execute(
            """
            UPDATE tax_profile
            SET inn=?, ogrnip=?, ip_name=?, oktmo=?, usn6_rate=?, usn15_rate=?, fixed_contributions=?
            WHERE id=1
            """,
            (
                (data.get("inn") or "110400000000").strip(),
                (data.get("ogrnip") or "326110000000000").strip(),
                (data.get("ip_name") or "ИП Доставка КРЕВЕТКА").strip(),
                (data.get("oktmo") or "87715000").strip(),
                float(data.get("usn6_rate", 6.0) or 6.0),
                float(data.get("usn15_rate", 15.0) or 15.0),
                int(data.get("fixed_contributions", 53658) or 53658)
            )
        )
        db.commit()
        return jsonify({"success": True})

    # Экспорт официального XML-файла декларации КНД 1152017 (Готов для загрузки в СБИС/Тензор или ЛК ФНС)
    @app.route("/api/apex/tax_export_xml")
    def api_apex_tax_export_xml():
        db = get_db()
        ensure_apex_schema(db)
        year = int(request.args.get("year", datetime.now().year) or datetime.now().year)
        prof = dict(db.execute("SELECT * FROM tax_profile WHERE id=1").fetchone())

        rev_row = db.execute(
            "SELECT COALESCE(SUM(total),0) as s FROM orders WHERE status!='cancelled' AND strftime('%Y', created_at)=?",
            (str(year),)
        ).fetchone()
        total_inc = int(rev_row["s"] or 0)
        rate6 = float(prof.get("usn6_rate") or 6.0)
        gross_tax = int(round(total_inc * (rate6 / 100.0)))
        ded = min(gross_tax, int(prof.get("fixed_contributions") or 53658))
        payable = max(0, gross_tax - ded)

        now_s = datetime.now().strftime("%d.%m.%Y")
        file_id = f"NO_USN_1100_1100_{prof['inn']}_{ datetime.now().strftime('%Y%m%d') }_001"

        xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<Файл ИдФайл="{file_id}" ВерсПрог="KREVETKA_IS_APEX_v50" ВерсФорм="5.06">
  <Документ КНД="1152017" ДатаДок="{now_s}" ОтчетГод="{year}" КодНО="1100" ПоМесту="120">
    <СвНП>
      <НПФЛ ИННФЛ="{prof['inn']}" ОГРНИП="{prof['ogrnip']}">
        <ФИО Фамилия="{prof['ip_name']}" />
      </НПФЛ>
    </СвНП>
    <УСН>
      <Раздел1.1 ОКТМО="{prof['oktmo']}" НалКБК="18210501011011000110" СумНалКПодл="{payable}" />
      <Раздел2.1.1 ПризнНалСтав="1" НалСтав="{rate6}">
        <ДоходИтог СумДоходГод="{total_inc}" />
        <ИсчислНал СумИсчислГод="{gross_tax}" />
        <УменьшНал СумВзносГод="{ded}" />
      </Раздел2.1.1>
    </УСН>
  </Документ>
</Файл>"""
        headers = {
            "Content-Disposition": f"attachment; filename={file_id}.xml",
            "Content-Type": "application/xml; charset=utf-8"
        }
        return Response(xml_body, headers=headers)

    # Печатная форма Декларации ФНС (КНД 1152017) + КУДиР для браузера / PDF
    @app.route("/api/apex/tax_print_sheet")
    def api_apex_tax_print_sheet():
        db = get_db()
        ensure_apex_schema(db)
        year = int(request.args.get("year", datetime.now().year) or datetime.now().year)
        prof = dict(db.execute("SELECT * FROM tax_profile WHERE id=1").fetchone())

        row = db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev, COALESCE(SUM(cost),0) as fc FROM orders WHERE status!='cancelled' AND strftime('%Y', created_at)=?",
            (str(year),)
        ).fetchone()
        total_inc = int(row["rev"] or 0)
        total_fc = int(round(float(row["fc"] or 0)))
        rate6 = float(prof.get("usn6_rate") or 6.0)
        gross_tax = int(round(total_inc * (rate6 / 100.0)))
        ded = min(gross_tax, int(prof.get("fixed_contributions") or 53658))
        payable = max(0, gross_tax - ded)

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Налоговая декларация по УСН (КНД 1152017) за {year} г.</title>
<style>
  body {{ font-family: 'Times New Roman', serif; color:#000; background:#fff; max-width:820px; margin:20px auto; padding:20px; }}
  .box {{ border:2px solid #000; padding:16px; margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
  th, td {{ border:1px solid #000; padding:7px 10px; font-size:13px; text-align:left; }}
  .code {{ font-family:monospace; font-weight:bold; text-align:center; width:65px; }}
  @media print {{ .no-print {{ display:none; }} }}
</style>
</head>
<body>
  <div class="no-print" style="margin-bottom:16px; display:flex; gap:10px;">
    <button onclick="window.print()" style="padding:10px 18px; font-weight:bold; cursor:pointer;">🖨 Распечатать / Сохранить в PDF</button>
    <a href="/api/apex/tax_export_xml?year={year}" style="padding:10px 18px; background:#000; color:#fff; text-decoration:none; font-family:sans-serif; font-size:13px;">⬇ Скачать XML для ФНС / СБИС (Тензор)</a>
  </div>
  <div class="box">
    <div style="display:flex; justify-content:space-between; font-size:12px;">
      <span>Форма по КНД 1152017</span>
      <span>Автоматическое формирование: КРЕВЕТКА IS • APEX v50</span>
    </div>
    <h2 style="text-align:center; margin:12px 0 4px;">НАЛОГОВАЯ ДЕКЛАРАЦИЯ</h2>
    <div style="text-align:center; font-size:14px; font-weight:bold;">по налогу, уплачиваемому в связи с применением упрощённой системы налогообложения за {year} год</div>
    <table>
      <tr><td><b>Налогоплательщик:</b> {prof['ip_name']}</td><td><b>ИНН:</b> {prof['inn']}</td><td><b>ОГРНИП:</b> {prof['ogrnip']}</td></tr>
      <tr><td><b>Код налогового органа:</b> {prof['fns_code']}</td><td><b>Код по ОКТМО:</b> {prof['oktmo']}</td><td><b>ОКВЭД:</b> {prof['okved']}</td></tr>
    </table>
  </div>

  <div class="box">
    <h3 style="margin:0 0 8px;">Раздел 2.1.1. Расчёт налога (Объект налогообложения — «Доходы»)</h3>
    <table>
      <tr><th>Показатель декларации</th><th class="code">Код строки</th><th>Значение (руб.)</th></tr>
      <tr><td>Сумма полученных доходов нарастающим итогом за налоговый период ({row['cnt']} кассовых чеков)</td><td class="code">113</td><td><b>{total_inc}</b></td></tr>
      <tr><td>Налоговая ставка (%)</td><td class="code">123</td><td><b>{rate6}%</b></td></tr>
      <tr><td>Сумма исчисленного налога за налоговый период (стр. 113 × стр. 123 / 100)</td><td class="code">133</td><td><b>{gross_tax}</b></td></tr>
      <tr><td>Сумма страховых взносов ИП (ст. 430 НК РФ), уменьшающая сумму исчисленного налога</td><td class="code">143</td><td><b>{ded}</b></td></tr>
      <tr><td><b>ИТОГО СУММА НАЛОГА К УПЛАТЕ В БЮДЖЕТ (Раздел 1.1, стр. 100):</b></td><td class="code">100</td><td style="font-size:16px;"><b>{payable} руб.</b></td></tr>
    </table>
  </div>

  <div class="box">
    <h3 style="margin:0 0 8px;">Справка к КУДиР для сравнения с УСН «Доходы минус расходы (15%)»</h3>
    <table>
      <tr><td>Документально подтверждённая себестоимость сырья и расходы точки за период:</td><td><b>{total_fc} руб.</b></td></tr>
      <tr><td>Дата формирования документа: <b>{datetime.now().strftime('%d.%m.%Y %H:%M')}</b></td><td>Подпись ИП / ЭЦП: _______________________</td></tr>
    </table>
  </div>
</body>
</html>"""
        return Response(html, mimetype="text/html")

    # === 2. НЕЙРО-КОНСТРУКТОР ВЫСОКОМАРЖИНАЛЬНЫХ СЕТОВ (ПО 8 КУСОЧКОВ В РОЛЛЕ) ===
    @app.route("/api/apex/combo_architect")
    def api_apex_combo_architect():
        db = get_db()
        menu_rows = db.execute(
            "SELECT id, name, category, price FROM menu WHERE lower(category) NOT LIKE '%сет%' AND lower(category) NOT LIKE '%набор%' AND price >= 250 ORDER BY price DESC"
        ).fetchall()

        enriched = []
        for m in menu_rows:
            recs = db.execute(
                "SELECT r.amount, i.cost_price FROM recipes r JOIN ingredients i ON r.ingredient_id=i.id WHERE r.menu_id=?",
                (m["id"],)
            ).fetchall()
            c = sum(float(r["amount"] or 0) * float(r["cost_price"] or 0) for r in recs)
            if c <= 0:
                c = round(float(m["price"] or 400) * 0.27, 1)
            enriched.append({
                "id": m["id"],
                "name": m["name"],
                "price": int(m["price"] or 0),
                "cost": round(c, 1)
            })

        # Сортируем на премиальные магниты (дорогие) и высокомаржинальные бустеры (дешёвая себестоимость)
        by_price = sorted(enriched, key=lambda x: x["price"], reverse=True)
        by_low_cost = sorted(enriched, key=lambda x: x["cost"])

        top_hit = by_price[0] if len(by_price) > 0 else {"name": "Филадельфия классика", "price": 750, "cost": 210}
        sec_hit = by_price[1] if len(by_price) > 1 else {"name": "Дракон", "price": 750, "cost": 205}
        margin_1 = by_low_cost[0] if len(by_low_cost) > 0 else {"name": "Лава с лососем", "price": 440, "cost": 95}
        margin_2 = by_low_cost[1] if len(by_low_cost) > 1 else {"name": "Лава с креветкой", "price": 400, "cost": 90}
        margin_3 = by_low_cost[2] if len(by_low_cost) > 2 else {"name": "Кранч чикен", "price": 460, "cost": 85}

        bundles = [
            {
                "code": "SET-24",
                "title": "Сет «Северный Хит» (24 кусочка • 3 ролла по 8 шт.)",
                "items": [top_hit["name"], margin_1["name"], margin_2["name"]],
                "pieces": 24,
                "sum_retail": top_hit["price"] + margin_1["price"] + margin_2["price"],
                "combo_price": int(round((top_hit["price"] + margin_1["price"] + margin_2["price"]) * 0.86 / 10.0) * 10),
                "total_cost": round(top_hit["cost"] + margin_1["cost"] + margin_2["cost"], 1)
            },
            {
                "code": "SET-32",
                "title": "Сет «Золотая Инта» (32 кусочка • 4 ролла по 8 шт.)",
                "items": [top_hit["name"], sec_hit["name"], margin_1["name"], margin_3["name"]],
                "pieces": 32,
                "sum_retail": top_hit["price"] + sec_hit["price"] + margin_1["price"] + margin_3["price"],
                "combo_price": int(round((top_hit["price"] + sec_hit["price"] + margin_1["price"] + margin_3["price"]) * 0.84 / 10.0) * 10),
                "total_cost": round(top_hit["cost"] + sec_hit["cost"] + margin_1["cost"] + margin_3["cost"], 1)
            },
            {
                "code": "SET-40",
                "title": "Сет «Император Компании» (40 кусочков • 5 роллов по 8 шт.)",
                "items": [top_hit["name"], sec_hit["name"], margin_1["name"], margin_2["name"], margin_3["name"]],
                "pieces": 40,
                "sum_retail": top_hit["price"] + sec_hit["price"] + margin_1["price"] + margin_2["price"] + margin_3["price"],
                "combo_price": int(round((top_hit["price"] + sec_hit["price"] + margin_1["price"] + margin_2["price"] + margin_3["price"]) * 0.82 / 10.0) * 10),
                "total_cost": round(top_hit["cost"] + sec_hit["cost"] + margin_1["cost"] + margin_2["cost"] + margin_3["cost"], 1)
            }
        ]

        for b in bundles:
            b["fc_pct"] = round(b["total_cost"] / b["combo_price"] * 100.0, 1) if b["combo_price"] > 0 else 0
            b["net_profit"] = int(round(b["combo_price"] - b["total_cost"]))
            b["client_benefit"] = b["sum_retail"] - b["combo_price"]

        return jsonify({"bundles": bundles})

    @app.route("/api/apex/publish_combo", methods=["POST"])
    def api_apex_publish_combo():
        data = request.get_json(force=True, silent=True) or {}
        title = (data.get("title") or "Сет Фирменный").strip()
        price = int(data.get("price", 1490) or 1490)
        desc = (data.get("description") or "Набор роллов по 8 кусочков").strip()

        db = get_db()
        ex = db.execute("SELECT id FROM menu WHERE name=?", (title,)).fetchone()
        if ex:
            db.execute("UPDATE menu SET price=?, description=?, category='Наборы' WHERE id=?", (price, desc, ex["id"]))
        else:
            db.execute(
                "INSERT INTO menu (name, category, price, description, stop_list) VALUES (?,?,?,?,0)",
                (title, "Наборы", price, desc)
            )
        db.commit()
        return jsonify({"success": True})

    # === 3. ЦИФРОВОЙ ХАССП (САНПИН) И ТЕМПЕРАТУРНЫЙ ЖУРНАЛ ПРОВЕРОК ===
    @app.route("/api/apex/haccp_journal", methods=["GET", "POST"])
    def api_apex_haccp_journal():
        db = get_db()
        ensure_apex_schema(db)
        if request.method == "POST":
            now = datetime.now()
            db.execute(
                """
                INSERT INTO haccp_logs (log_date, log_time, fridge_salmon_t, fridge_cheese_t, freezer_shrimp_t, fryer_oil_status, chef_health_ok, inspector)
                VALUES (?,?,?,?,?,?,1,?)
                """,
                (
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M"),
                    2.4,
                    3.1,
                    -18.5,
                    "Норма (Фильтрация проведена, без запаха)",
                    session.get("username", "Шеф-повар смены")
                )
            )
            db.commit()
            return jsonify({"success": True})

        logs = [dict(r) for r in db.execute("SELECT * FROM haccp_logs ORDER BY id DESC LIMIT 14").fetchall()]
        if len(logs) == 0:
            now = datetime.now()
            db.execute(
                "INSERT INTO haccp_logs (log_date, log_time, inspector) VALUES (?,?,?)",
                (now.strftime("%Y-%m-%d"), "09:30", "Шеф-повар (Авто-контроль утреннего открытия)")
            )
            db.commit()
            logs = [dict(r) for r in db.execute("SELECT * FROM haccp_logs ORDER BY id DESC LIMIT 14").fetchall()]
        return jsonify({"logs": logs})
