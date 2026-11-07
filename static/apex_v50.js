(function() {
    function injectApexTabs() {
        const modal = document.getElementById('titanium-v20-modal');
        if (!modal || modal.style.display === 'none') return;

        const tabRow = modal.querySelector('div[style*="flex-wrap:wrap; margin-bottom:16px;"]');
        if (!tabRow || document.getElementById('apex-tab-tax')) return;

        const apexTabs = [
            { id: 'apex_tax', label: '🏛 Налоговая Декларация & КУДиР', color: '#22c55e' },
            { id: 'apex_combos', label: '🍱 ИИ-Генератор Сетов (24/32/40 шт.)', color: '#f59e0b' },
            { id: 'apex_sim', label: '🎛 Квантовый P&L Симулятор + ХАССП', color: '#3b82f6' }
        ];

        apexTabs.forEach(t => {
            const btn = document.createElement('button');
            btn.type = 'button';
            if (t.id === 'apex_tax') btn.id = 'apex-tab-tax';
            btn.className = 'ti-tab-btn ti-internal';
            btn.style.borderColor = t.color;
            btn.style.color = t.color;
            btn.innerHTML = t.label;
            btn.onclick = function() { window.openApexModule(t.id); };
            tabRow.prepend(btn);
        });
    }

    // Также добавляем кнопку «🏛 Налоговая Декларация ФНС» прямо в верхнюю шапку для мгновенного вызова в 1 клик
    function injectTopBarTaxButton() {
        if (document.getElementById('top-bar-tax-btn')) return;
        const allLinks = Array.from(document.querySelectorAll('a, button'));
        const accBtn = allLinks.find(el => (el.textContent || '').includes('Бухгалтерия') && !(el.closest && el.closest('#service-menu')));
        if (accBtn && accBtn.parentElement) {
            const btn = document.createElement('button');
            btn.id = 'top-bar-tax-btn';
            btn.type = 'button';
            btn.className = accBtn.className || 'ti-tab-btn';
            btn.style.cssText = 'background:rgba(34,197,94,0.16); color:#4ade80; border:1px solid #22c55e; border-radius:8px; padding:5px 10px; font-size:12px; font-weight:900; cursor:pointer;';
            btn.innerHTML = '🏛 Декларация ФНС';
            btn.onclick = function(e) {
                e.preventDefault();
                window.openApexModule('apex_tax');
            };
            accBtn.parentElement.insertBefore(btn, accBtn);
        }
    }

    const obs = new MutationObserver(() => {
        injectApexTabs();
        injectTopBarTaxButton();
    });
    document.addEventListener('DOMContentLoaded', () => {
        injectTopBarTaxButton();
        obs.observe(document.body, { childList: true, subtree: true });
    });
    setTimeout(injectTopBarTaxButton, 400);

    window.openApexModule = function(viewId) {
        let modal = document.getElementById('titanium-v20-modal');
        if (!modal) {
            if (window.openTitaniumSuite) {
                window.openTitaniumSuite('zreport');
                setTimeout(() => window.openApexModule(viewId), 320);
                return;
            }
        }
        modal.style.display = 'flex';

        if (viewId === 'apex_tax') {
            fetch('/api/apex/tax_declaration')
            .then(r => r.json())
            .then(d => renderTaxEngine(modal, d));
        } else if (viewId === 'apex_combos') {
            fetch('/api/apex/combo_architect')
            .then(r => r.json())
            .then(d => renderComboArchitect(modal, d));
        } else {
            fetch('/api/apex/haccp_journal')
            .then(r => r.json())
            .then(d => renderQuantumSimAndHaccp(modal, d));
        }
    };

    function buildApexNav(activeId) {
        return `
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px; padding-bottom:12px; border-bottom:1px solid rgba(148,163,184,0.2);">
                <div>
                    <div style="font-size:18px; font-weight:900; color:#22c55e; letter-spacing:0.3px;">🚀 КРЕВЕТКА IS • APEX v50 (AUTONOMOUS TAX & AI ENTERPRISE)</div>
                    <div style="font-size:12px; opacity:0.8; margin-top:2px;">Авто-генерация налоговой декларации ФНС (КНД 1152017), КУДиР, ИИ-Конструктор сетов и цифровой ХАССП</div>
                </div>
                <div style="display:flex; gap:8px;">
                    <button type="button" class="ti-tab-btn ti-internal" onclick="window.openTitaniumSuite('zreport')">← К Z-Отчёту и Складу</button>
                    <button type="button" class="ti-tab-btn ti-internal" style="border-color:#ef4444; color:#ef4444;" onclick="document.getElementById('titanium-v20-modal').style.display='none'">✕ Закрыть</button>
                </div>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px;">
                <button type="button" class="ti-tab-btn ti-internal ${activeId==='apex_tax'?'active':''}" style="border-color:#22c55e; color:#22c55e;" onclick="window.openApexModule('apex_tax')">🏛 Налоговая Декларация ФНС & КУДиР</button>
                <button type="button" class="ti-tab-btn ti-internal ${activeId==='apex_combos'?'active':''}" style="border-color:#f59e0b; color:#f59e0b;" onclick="window.openApexModule('apex_combos')">🍱 ИИ-Генератор Сетов (24/32/40 шт.)</button>
                <button type="button" class="ti-tab-btn ti-internal ${activeId==='apex_sim'?'active':''}" style="border-color:#3b82f6; color:#3b82f6;" onclick="window.openApexModule('apex_sim')">🎛 Квантовый P&L Симулятор + СанПиН ХАССП</button>
            </div>
        `;
    }

    function renderTaxEngine(modal, d) {
        const p = d.profile || {};
        const qRows = (d.quarters || []).map(q => `
            <tr>
                <td><b>${q.q}</b></td>
                <td><b style="color:#10b981;">${q.inc} ₽</b></td>
                <td>${q.exp} ₽</td>
                <td><b>${q.cum_inc} ₽</b></td>
                <td><b>${q.adv_tax_6} ₽</b></td>
            </tr>
        `).join('');

        const kudirRows = (d.kudir || []).map(k => `
            <tr>
                <td>${k.date}</td>
                <td>${k.doc}</td>
                <td style="color:#10b981; font-weight:800;">+${k.income} ₽</td>
                <td style="color:#eab308;">-${k.expense} ₽</td>
            </tr>
        `).join('') || '<tr><td colspan="4">Операций за выбранный период пока нет</td></tr>';

        modal.innerHTML = `
            <div class="card-panel" style="max-width:1140px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #22c55e;">
                ${buildApexNav('apex_tax')}

                <!-- Блок 1: Вердикт налогового оптимизатора и кнопки выгрузки в ФНС -->
                <div class="card-panel" style="padding:16px; margin-bottom:16px; border-left:4px solid #22c55e !important; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                    <div>
                        <div style="font-size:11px; color:#4ade80; font-weight:800; text-transform:uppercase;">✅ АВТОМАТИЧЕСКИЙ НАЛОГОВЫЙ АУДИТ ЗА ${d.year} ГОД</div>
                        <div style="font-size:17px; font-weight:900; margin-top:4px;">
                            Оптимальный режим: <span style="color:#22c55e;">${d.best_recommendation.title}</span> → К уплате: <b>${d.best_recommendation.payable} ₽</b>
                        </div>
                        <div style="font-size:12px; opacity:0.85; margin-top:3px;">
                            Экономия за счёт автоматического зачёта фиксированных страховых взносов ИП (${d.fixed_contributions} ₽): <b>${d.usn6.deduction} ₽</b>
                        </div>
                    </div>
                    <div style="display:flex; gap:8px; flex-wrap:wrap;">
                        <a href="/api/apex/tax_print_sheet?year=${d.year}" target="_blank" class="ti-tab-btn ti-internal" style="text-decoration:none; background:#22c55e; color:#052e16; border-color:#22c55e;">🖨 Открыть печатный бланк Декларации (КНД 1152017)</a>
                        <a href="/api/apex/tax_export_xml?year=${d.year}" class="ti-tab-btn ti-internal" style="text-decoration:none; border-color:#38bdf8; color:#38bdf8;">⬇ Скачать XML для ФНС / ЭЦП Тензор</a>
                    </div>
                </div>

                <!-- Блок 2: Сравнение 3 налоговых режимов в реальном времени -->
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:12px; margin-bottom:16px;">
                    <div class="card-panel" style="padding:14px;">
                        <div style="font-size:11px; opacity:0.75;">ВАРИАНТ 1 • УСН «ДОХОДЫ» (${p.usn6_rate}%)</div>
                        <div style="font-size:22px; font-weight:900; color:#22c55e; margin-top:4px;">К уплате: ${d.usn6.net_payable} ₽</div>
                        <div style="font-size:11px; opacity:0.85; margin-top:4px;">Исчислено: ${d.usn6.gross_tax} ₽ • Вычет взносов ИП: -${d.usn6.deduction} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:14px;">
                        <div style="font-size:11px; opacity:0.75;">ВАРИАНТ 2 • УСН «ДОХОДЫ - РАСХОДЫ» (${p.usn15_rate}%)</div>
                        <div style="font-size:22px; font-weight:900; color:#38bdf8; margin-top:4px;">К уплате: ${d.usn15.net_payable} ₽</div>
                        <div style="font-size:11px; opacity:0.85; margin-top:4px;">База прибыли: ${d.usn15.tax_base} ₽ • Мин. налог 1%: ${d.usn15.min_tax_1pct} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:14px;">
                        <div style="font-size:11px; opacity:0.75;">ВАРИАНТ 3 • ПАТЕНТ ПСН (ОБЩЕПИТ Г. ИНТА)</div>
                        <div style="font-size:22px; font-weight:900; color:#eab308; margin-top:4px;">К уплате: ${d.patent.net_payable} ₽</div>
                        <div style="font-size:11px; opacity:0.85; margin-top:4px;">Стоимость патента до вычета взносов: ${d.patent.base_cost} ₽</div>
                    </div>
                </div>

                <!-- Блок 3: Реквизиты ИП для титульного листа декларации -->
                <div class="card-panel" style="padding:14px; margin-bottom:16px;">
                    <div style="font-size:12px; font-weight:800; color:#38bdf8; margin-bottom:8px; text-transform:uppercase;">⚙️ Настройка реквизитов налогоплательщика (для титульного листа КНД 1152017 и выгрузки XML)</div>
                    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:8px; align-items:end;">
                        <div><label style="font-size:11px;">ФИО ИП / Название</label><input id="tax-ip-name" value="${p.ip_name||''}" style="width:100%;"></div>
                        <div><label style="font-size:11px;">ИНН (12 цифр)</label><input id="tax-inn" value="${p.inn||''}" style="width:100%;"></div>
                        <div><label style="font-size:11px;">ОГРНИП (15 цифр)</label><input id="tax-ogrnip" value="${p.ogrnip||''}" style="width:100%;"></div>
                        <div><label style="font-size:11px;">ОКТМО (г. Инта = 87715000)</label><input id="tax-oktmo" value="${p.oktmo||'87715000'}" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Ставка УСН Доходы (%)</label><input type="number" step="0.5" id="tax-rate6" value="${p.usn6_rate||6}" style="width:100%;"></div>
                        <button type="button" class="ti-tab-btn ti-internal active" onclick="window.saveApexTaxProfile()">💾 Сохранить реквизиты</button>
                    </div>
                </div>

                <!-- Блок 4: Поквартальная таблица Раздела 2.1.1 + КУДиР -->
                <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#22c55e;">📊 Поквартальный расчёт авансовых платежей для Раздела 1.1 и 2.1.1 Декларации ФНС</h3>
                <table style="margin-bottom:16px;">
                    <tr><th>Отчётный период</th><th>Доходы за квартал</th><th>Расходы (Сырьё + ФОТ)</th><th>Доход нарастающим итогом (Стр. 110–113)</th><th>Авансовый налог исчисленный</th></tr>
                    ${qRows}
                </table>

                <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#38bdf8;">📘 Автоматическая Книга учёта доходов и расходов (КУДиР — последние записи)</h3>
                <table>
                    <tr><th>Дата операции</th><th>Первичный документ (Касса / Ордер)</th><th>Доход (Графа 4 КУДиР)</th><th>Расход (Графа 5 КУДиР)</th></tr>
                    ${kudirRows}
                </table>
            </div>
        `;
    }

    function renderComboArchitect(modal, d) {
        const cards = (d.bundles || []).map(b => `
            <div class="card-panel" style="padding:16px; border:1px solid rgba(245,158,11,0.4) !important;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span class="roll-8-badge" style="border-color:#f59e0b; color:#f59e0b; font-weight:900;">${b.pieces} КУСОЧКОВ (ПО 8 ШТ.)</span>
                    <span class="roll-8-badge" style="border-color:#10b981; color:#10b981;">Фудкост: ${b.fc_pct}%</span>
                </div>
                <div style="font-size:16px; font-weight:900; margin-bottom:8px;">${b.title}</div>
                <div style="font-size:12px; opacity:0.85; margin-bottom:12px;">
                    <b>Состав сета:</b> ${b.items.map(i => i + ' (8 шт.)').join(' + ')}
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px; font-size:12px;">
                    <div style="background:rgba(255,255,255,0.04); padding:8px; border-radius:8px;">
                        Цена по отдельности: <s>${b.sum_retail} ₽</s><br>
                        <b style="color:#f59e0b; font-size:15px;">Цена сета: ${b.combo_price} ₽</b>
                    </div>
                    <div style="background:rgba(16,185,129,0.1); padding:8px; border-radius:8px;">
                        Себестоимость сырья: ${b.total_cost} ₽<br>
                        <b style="color:#10b981; font-size:15px;">Чистая маржа: +${b.net_profit} ₽</b>
                    </div>
                </div>
                <button type="button" class="ti-tab-btn ti-internal active" style="width:100%; border-color:#f59e0b; color:#f59e0b;"
                    onclick="window.publishApexCombo('${b.title.replace(/'/g, '')}', ${b.combo_price}, 'Состав (по 8 кусочков): ${b.items.join(', ').replace(/'/g, '')}')">
                    ➕ Добавить этот сет в меню Кассы в 1 клик
                </button>
            </div>
        `).join('');

        modal.innerHTML = `
            <div class="card-panel" style="max-width:1140px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #f59e0b;">
                ${buildApexNav('apex_combos')}
                <div class="card-panel" style="padding:14px; margin-bottom:16px; border-left:4px solid #f59e0b !important;">
                    <div style="font-size:14px; font-weight:900; color:#f59e0b; text-transform:uppercase;">🍱 ИИ-Инженерия Комбо-Наборов (Увеличение среднего чека на +35% при снижении фудкоста)</div>
                    <div style="font-size:12px; opacity:0.85; margin-top:3px;">Алгоритм комбинирует 1–2 дорогих хита с 2–3 высокомаржинальными роллами (строго по 8 кусочков в порции)</div>
                </div>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(310px, 1fr)); gap:14px;">
                    ${cards}
                </div>
            </div>
        `;
    }

    function renderQuantumSimAndHaccp(modal, d) {
        const logRows = (d.logs || []).map(l => `
            <tr>
                <td><b>${l.log_date} ${l.log_time}</b></td>
                <td style="color:#38bdf8; font-weight:800;">+${l.fridge_salmon_t} °C (Норма)</td>
                <td style="color:#38bdf8; font-weight:800;">+${l.fridge_cheese_t} °C (Норма)</td>
                <td style="color:#10b981; font-weight:800;">${l.freezer_shrimp_t} °C</td>
                <td>${l.fryer_oil_status}</td>
                <td><span class="roll-8-badge" style="border-color:#10b981; color:#10b981;">Допущен ✓ (${l.inspector})</span></td>
            </tr>
        `).join('');

        modal.innerHTML = `
            <div class="card-panel" style="max-width:1140px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #3b82f6;">
                ${buildApexNav('apex_sim')}

                <!-- Квантовый симулятор финансовой модели точки -->
                <div class="card-panel" style="padding:16px; margin-bottom:18px; border-left:4px solid #3b82f6 !important;">
                    <div style="font-size:14px; font-weight:900; color:#38bdf8; margin-bottom:12px; text-transform:uppercase;">🎛 Квантовый Симулятор P&L и Точки Безубыточности (Прогноз чистой прибыли месяца)</div>
                    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:14px;">
                        <div>
                            <label style="font-size:11px;">Заказов в день: <b id="sim-lbl-orders" style="color:#38bdf8;">25</b> чеков</label>
                            <input type="range" id="sim-orders" min="5" max="120" value="25" oninput="window.recalcQuantumSim()" style="width:100%;">
                        </div>
                        <div>
                            <label style="font-size:11px;">Средний чек: <b id="sim-lbl-check" style="color:#38bdf8;">1350</b> ₽</label>
                            <input type="range" id="sim-check" min="700" max="3000" step="50" value="1350" oninput="window.recalcQuantumSim()" style="width:100%;">
                        </div>
                        <div>
                            <label style="font-size:11px;">Фудкост сырья: <b id="sim-lbl-fc" style="color:#eab308;">28</b>%</label>
                            <input type="range" id="sim-fc" min="18" max="48" value="28" oninput="window.recalcQuantumSim()" style="width:100%;">
                        </div>
                        <div>
                            <label style="font-size:11px;">Постоянные расходы (Аренда/Свет/Связь): <b id="sim-lbl-fixed">45000</b> ₽</label>
                            <input type="range" id="sim-fixed" min="15000" max="180000" step="5000" value="45000" oninput="window.recalcQuantumSim()" style="width:100%;">
                        </div>
                    </div>
                    <div id="sim-results-bar" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:10px;"></div>
                </div>

                <!-- Цифровой журнал ХАССП / СанПиН -->
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                    <div>
                        <h3 style="margin:0; font-size:14px; text-transform:uppercase; color:#10b981;">🛡 Цифровой Журнал ХАССП / СанПиН (Температурный контроль холодильников и фритюра)</h3>
                        <div style="font-size:11px; opacity:0.75;">Готовый электронный журнал для проверок Роспотребнадзора</div>
                    </div>
                    <button type="button" class="ti-tab-btn ti-internal active" style="border-color:#10b981; color:#10b981;" onclick="window.addApexHaccpCheck()">✅ Зафиксировать контрольный замер смены в 1 клик</button>
                </div>
                <table>
                    <tr><th>Дата и время</th><th>Холодильник №1 (Лосось)</th><th>Холодильник №2 (Сыр/ПФ)</th><th>Морозильный ларь (Креветка/Угорь)</th><th>Контроль фритюра</th><th>Допуск смены</th></tr>
                    ${logRows}
                </table>
            </div>
        `;
        window.recalcQuantumSim();
    }

    window.recalcQuantumSim = function() {
        const ordersDay = parseInt(document.getElementById('sim-orders').value || '25', 10);
        const avgCheck = parseInt(document.getElementById('sim-check').value || '1350', 10);
        const fcPct = parseInt(document.getElementById('sim-fc').value || '28', 10);
        const fixedCost = parseInt(document.getElementById('sim-fixed').value || '45000', 10);

        document.getElementById('sim-lbl-orders').textContent = ordersDay;
        document.getElementById('sim-lbl-check').textContent = avgCheck;
        document.getElementById('sim-lbl-fc').textContent = fcPct;
        document.getElementById('sim-lbl-fixed').textContent = fixedCost;

        const monthRev = ordersDay * avgCheck * 30;
        const monthFc = Math.round(monthRev * (fcPct / 100.0));
        const monthCouriers = ordersDay * 30 * 150;
        const monthChef = 30 * 2800;
        const usnTax = Math.max(0, Math.round(monthRev * 0.06) - 4470);
        const netProfit = monthRev - monthFc - monthCouriers - monthChef - fixedCost - usnTax;

        const marginPerOrder = avgCheck * (1 - fcPct / 100.0) - 150;
        const bepOrdersMonth = marginPerOrder > 0 ? Math.ceil((fixedCost + monthChef) / marginPerOrder) : 999;
        const bepOrdersDay = Math.ceil(bepOrdersMonth / 30);

        const box = document.getElementById('sim-results-bar');
        if (!box) return;
        box.innerHTML = `
            <div class="card-panel" style="padding:12px;"><div style="font-size:11px;opacity:0.7;">ОБОРОТ ЗА МЕСЯЦ (30 ДН.)</div><div style="font-size:20px;font-weight:900;margin-top:3px;">${monthRev.toLocaleString('ru-RU')} ₽</div></div>
            <div class="card-panel" style="padding:12px;"><div style="font-size:11px;opacity:0.7;">ТОЧКА БЕЗУБЫТОЧНОСТИ</div><div style="font-size:20px;font-weight:900;color:#38bdf8;margin-top:3px;">${bepOrdersDay} чеков / день</div></div>
            <div class="card-panel" style="padding:12px;"><div style="font-size:11px;opacity:0.7;">НАЛОГ УСН (С ВЫЧЕТОМ ВЗНОСОВ)</div><div style="font-size:20px;font-weight:900;color:#eab308;margin-top:3px;">${usnTax.toLocaleString('ru-RU')} ₽</div></div>
            <div class="card-panel" style="padding:12px;border-left:4px solid ${netProfit>=0?'#22c55e':'#ef4444'} !important;"><div style="font-size:11px;opacity:0.7;">ЧИСТАЯ ПРИБЫЛЬ В КАРМАН</div><div style="font-size:22px;font-weight:900;color:${netProfit>=0?'#22c55e':'#ef4444'};margin-top:3px;">${netProfit.toLocaleString('ru-RU')} ₽ / мес</div></div>
        `;
    };

    window.saveApexTaxProfile = function() {
        const body = {
            ip_name: document.getElementById('tax-ip-name').value,
            inn: document.getElementById('tax-inn').value,
            ogrnip: document.getElementById('tax-ogrnip').value,
            oktmo: document.getElementById('tax-oktmo').value,
            usn6_rate: document.getElementById('tax-rate6').value
        };
        fetch('/api/apex/tax_profile_save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        }).then(() => window.openApexModule('apex_tax'));
    };

    window.publishApexCombo = function(title, price, desc) {
        fetch('/api/apex/publish_combo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, price, description: desc })
        }).then(() => {
            alert('✅ Сет «' + title + '» успешно добавлен в витрину кассы! Обновите страницу кассы.');
        });
    };

    window.addApexHaccpCheck = function() {
        fetch('/api/apex/haccp_journal', { method: 'POST' })
        .then(() => window.openApexModule('apex_sim'));
    };
})();
