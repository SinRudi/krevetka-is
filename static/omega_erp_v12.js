(function() {
    function escHtml(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
    let lastOmegaData = null;

    // Перехватываем клик по ЛЮБОЙ кнопке со словами "Z-отчёт" / "Z отчёт" / "Z-Отчет" на любой странице
    document.addEventListener('click', function(e) {
        const el = e.target.closest('button, a, .quick-chip, [onclick]');
        if (!el) return;
        if (el.id === 'omega-close-btn' || el.classList.contains('omega-internal-btn')) return;

        const txt = (el.innerText || el.textContent || '').toLowerCase();
        const oc = (el.getAttribute('onclick') || '').toLowerCase();
        if (
            txt.includes('z-отч') ||
            txt.includes('z отч') ||
            txt.includes('z-отчет') ||
            oc.includes('zreport') ||
            oc.includes('openultracentermodal')
        ) {
            e.preventDefault();
            e.stopPropagation();
            if (oc.includes("'recipes'")) {
                window.openOmegaHub('recipes');
            } else {
                window.openOmegaHub('zreport');
            }
        }
    }, true);

    // Горячая клавиша F9 для мгновенного открытия Z-Отчёта
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F9') {
            e.preventDefault();
            window.openOmegaHub('zreport');
        }
    });

    // Совместимость со старым вызовом
    window.openUltraCenterModal = function(tab) {
        window.openOmegaHub(tab || 'zreport');
    };

    window.openOmegaHub = function(activeTab) {
        activeTab = activeTab || 'zreport';
        let modal = document.getElementById('omega-v12-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'omega-v12-modal';
            modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.82); z-index:99999; display:flex; align-items:center; justify-content:center; padding:14px; backdrop-filter:blur(4px);';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';
        modal.innerHTML = '<div class="card-panel" style="max-width:1060px; width:100%; padding:26px; text-align:center; font-size:15px; border:1px solid #38bdf8;">⚡ Загрузка командного центра OMEGA v12...</div>';

        if (activeTab === 'recipes') {
            loadRecipesTab(modal);
            return;
        }

        fetch('/api/omega/dashboard')
        .then(r => r.json())
        .then(d => {
            lastOmegaData = d;
            renderOmegaModal(modal, d, activeTab);
        })
        .catch(err => {
            modal.innerHTML = '<div class="card-panel" style="max-width:600px; padding:24px; border:1px solid #dc2626;">Ошибка связи с сервером: ' + err + ' <br><br><button class="quick-chip omega-internal-btn" onclick="document.getElementById(\'omega-v12-modal\').style.display=\'none\'">Закрыть</button></div>';
        });
    };

    function renderOmegaModal(modal, d, tab) {
        const navHtml = `
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid rgba(161,161,170,0.2);">
                <div>
                    <h2 style="margin:0; font-size:18px; color:#38bdf8; text-transform:uppercase;">⚡ КРЕВЕТКА IS • OMEGA v12 КОМАНДНЫЙ ЦЕНТР</h2>
                    <div style="font-size:12px; opacity:0.8; margin-top:2px;">Период: <b>${d.period_label}</b> • Стандарт роллов: <b>8 кусочков</b></div>
                </div>
                <div style="display:flex; gap:6px; flex-wrap:wrap;">
                    <button type="button" class="quick-chip omega-internal-btn" style="${tab==='zreport'?'border-color:#38bdf8;color:#38bdf8;font-weight:800;':''}" onclick="window.openOmegaHub('zreport')">🧾 Z-Отчёт & Сейф</button>
                    <button type="button" class="quick-chip omega-internal-btn" style="${tab==='logistics'?'border-color:#16a34a;color:#16a34a;font-weight:800;':''}" onclick="window.openOmegaHub('logistics')">🗺 Радар районов Инты</button>
                    <button type="button" class="quick-chip omega-internal-btn" style="${tab==='recipes'?'border-color:#ff6900;color:#ff6900;font-weight:800;':''}" onclick="window.openOmegaHub('recipes')">🍣 Конструктор Техкарт</button>
                    <button type="button" class="quick-chip omega-internal-btn" style="${tab==='antifraud'?'border-color:#eab308;color:#eab308;font-weight:800;':''}" onclick="window.openOmegaHub('antifraud')">🛡 Анти-Фрод & Склад</button>
                    <button type="button" id="omega-close-btn" class="quick-chip omega-internal-btn" style="color:#dc2626; border-color:#dc2626; font-weight:800;" onclick="document.getElementById('omega-v12-modal').style.display='none'">✕ Закрыть</button>
                </div>
            </div>
        `;

        let bodyHtml = '';

        if (tab === 'zreport') {
            const procRows = (d.procurement || []).map(p => `
                <tr>
                    <td><b>${p.name}</b></td>
                    <td style="color:#dc2626; font-weight:700;">${p.stock} ${p.unit}</td>
                    <td>${p.min_stock} ${p.unit}</td>
                    <td><b style="color:#16a34a;">+${p.order_qty} ${p.unit}</b></td>
                    <td>~${p.est_cost} ₽</td>
                </tr>
            `).join('') || '<tr><td colspan="5" style="color:#16a34a;">✓ Все остатки сырья в норме (выше минимального порога)</td></tr>';

            bodyHtml = `
                <div id="omega-z-printable" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(215px, 1fr)); gap:10px; margin-bottom:16px;">
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">ВЫРУЧКА (${d.orders_count} чеков)</div>
                        <div style="font-size:22px; font-weight:800; margin-top:4px;">${d.total_revenue} ₽</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">Средний чек: <b>${d.avg_check} ₽</b> • Отмен: <b>${d.cancelled_count}</b></div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">НАЛИЧНЫЕ vs БЕЗНАЛ</div>
                        <div style="font-size:15px; font-weight:800; color:#16a34a; margin-top:4px;">💵 Наличные: ${d.cash_revenue} ₽</div>
                        <div style="font-size:15px; font-weight:800; color:#38bdf8; margin-top:2px;">💳 Карта / СБП: ${d.card_revenue} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">НАЧИСЛЕНО ПЕРСОНАЛУ (ФОТ)</div>
                        <div style="font-size:14px; font-weight:800; color:#ff6900; margin-top:4px;">🛵 Курьерам (за заказы): ${d.courier_payroll} ₽</div>
                        <div style="font-size:13px; margin-top:3px;">👨‍🍳 Поварам/Кассе (часы): <b>${d.hourly_payroll} ₽</b></div>
                    </div>
                    <div class="card-panel" style="padding:12px; border-left:4px solid #16a34a !important;">
                        <div style="font-size:11px; opacity:0.7;">РАСЧЁТНЫЙ НАЛ В ЯЩИКЕ КАССЫ</div>
                        <div style="font-size:22px; font-weight:800; color:#16a34a; margin-top:4px;" id="z-expected-val" data-expected="${d.expected_drawer_cash}">${d.expected_drawer_cash} ₽</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">Чистая прибыль: <b>${d.day_net_profit} ₽</b></div>
                    </div>
                </div>

                <!-- КУПЮРОПРИЁМНИК И СВЕРКА СЕЙФА -->
                <div class="card-panel" style="padding:14px; margin-bottom:16px; border-left:4px solid #38bdf8 !important;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                        <div style="font-size:13px; font-weight:800; color:#38bdf8; text-transform:uppercase;">🧮 Калькулятор фактического пересчёта купюр в денежном ящике</div>
                        <button type="button" class="quick-chip omega-internal-btn" onclick="window.printOmegaZSlip()">🖨 Напечатать Z-Чек на термоленту</button>
                    </div>
                    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(110px, 1fr)); gap:8px; align-items:center;">
                        <div><label style="font-size:11px;">Купюры 5000 ₽</label><input type="number" min="0" value="0" class="bill-inp" data-denom="5000" oninput="window.recalcCashDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Купюры 2000 ₽</label><input type="number" min="0" value="0" class="bill-inp" data-denom="2000" oninput="window.recalcCashDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Купюры 1000 ₽</label><input type="number" min="0" value="0" class="bill-inp" data-denom="1000" oninput="window.recalcCashDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Купюры 500 ₽</label><input type="number" min="0" value="0" class="bill-inp" data-denom="500" oninput="window.recalcCashDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Купюры 100/200 ₽ (сумма)</label><input type="number" min="0" value="0" class="bill-inp" data-denom="1" oninput="window.recalcCashDrawer()" style="width:100%;"></div>
                        <div style="padding:8px; border-radius:6px; background:rgba(56,189,248,0.1); text-align:center;">
                            <div style="font-size:10px; opacity:0.75;">ФАКТ В ЯЩИКЕ / СВЕРКА</div>
                            <div id="drawer-fact-result" style="font-size:14px; font-weight:800; margin-top:2px;">Введите купюры</div>
                        </div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
                    <h3 style="margin:0; font-size:14px; text-transform:uppercase; color:#eab308;">📦 Авто-Заявка поставщику (сырьё ниже минимального остатка)</h3>
                    <button type="button" class="quick-chip omega-internal-btn" style="border-color:#16a34a; color:#16a34a;" onclick="window.copySupplierOrderText(this)">📋 Скопировать заявку для WhatsApp</button>
                </div>
                <table>
                    <tr><th>Сырьё</th><th>Остаток</th><th>Мин. порог</th><th>К заказу</th><th>Сумма закупа</th></tr>
                    ${procRows}
                </table>
            `;
        } else if (tab === 'logistics') {
            const zRows = (d.zones_stats || []).map(z => `
                <tr>
                    <td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${z.color};margin-right:6px;"></span><b>${escHtml(z.name)}</b></td>
                    <td><b>${z.cnt}</b> зак.</td>
                    <td><b>${z.rev} ₽</b></td>
                    <td style="color:#ff6900; font-weight:700;">${z.courier_pay} ₽</td>
                    <td>${z.cnt > 0 ? Math.round(z.rev / z.cnt) : 0} ₽</td>
                </tr>
            `).join('');

            bodyHtml = `
                <h3 style="margin:0 0 10px; font-size:14px; text-transform:uppercase; color:#16a34a;">🗺 Тепловая матрица доставки по районам г. Инта (Сдельный ФОТ курьеров)</h3>
                <table>
                    <tr><th>Район Инты / Зона</th><th>Выполнено заказов</th><th>Выручка района</th><th>Начислено курьерам</th><th>Средний чек</th></tr>
                    ${zRows}
                </table>
            `;
        } else if (tab === 'antifraud') {
            const cancRows = (d.cancelled_orders || []).map(c => `
                <tr><td><b>#${c.id}</b></td><td>${c.time}</td><td style="color:#dc2626;font-weight:700;">${c.total} ₽</td><td>${escHtml(c.address)}</td></tr>
            `).join('') || '<tr><td colspan="4" style="color:#16a34a;">✓ Отменённых чеков за смену нет</td></tr>';

            const woRows = (d.writeoffs || []).map(w => `
                <tr><td>${escHtml(w.created_at || '')}</td><td><b>${escHtml(w.ing_name || '')}</b></td><td>${escHtml(w.change_amount)}</td><td>${escHtml(w.reason || '')}</td><td>${escHtml(w.username || '')}</td></tr>
            `).join('') || '<tr><td colspan="5">Нет ручных списаний</td></tr>';

            bodyHtml = `
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
                    <div>
                        <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#dc2626;">🚨 Контроль отменённых чеков (Анти-Фрод)</h3>
                        <table>
                            <tr><th>Чек</th><th>Время</th><th>Сумма</th><th>Адрес</th></tr>
                            ${cancRows}
                        </table>
                    </div>
                    <div>
                        <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#eab308;">🔪 Журнал списаний и возвратов сырья</h3>
                        <table>
                            <tr><th>Дата</th><th>Сырьё</th><th>Кол-во</th><th>Причина</th><th>Кто списал</th></tr>
                            ${woRows}
                        </table>
                    </div>
                </div>
            `;
        }

        modal.innerHTML = `
            <div class="card-panel" style="max-width:1060px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #38bdf8;">
                ${navHtml}
                ${bodyHtml}
            </div>
        `;
    }

    function loadRecipesTab(modal) {
        fetch('/api/ultra/recipes_matrix')
        .then(r => r.json())
        .then(d => {
            const menuOpts = (d.menu_items || []).map(m =>
                `<option value="${m.id}">${escHtml(m.name)} (Цена: ${escHtml(m.price)} ₽ • Себест: ${escHtml(m.cost)} ₽)</option>`
            ).join('');
            const ingOpts = (d.ingredients || []).map(i =>
                `<option value="${i.id}">${escHtml(i.name)} (${escHtml(i.cost_price)} ₽ / ${escHtml(i.unit || 'кг')})</option>`
            ).join('');
            const rowsHtml = (d.menu_items || []).map(m => {
                const fcColor = m.fc_pct > 35 ? '#dc2626' : (m.fc_pct > 0 ? '#16a34a' : '#eab308');
                const compText = (m.recipe || []).map(rc => `${escHtml(rc.ing_name)}: ${escHtml(rc.amount)}${escHtml(rc.unit)}`).join(', ') || 'Техкарта не заполнена';
                return `<tr>
                    <td><b>${escHtml(m.name)}</b> <span class="roll-8-badge" style="font-size:10px;">8 кусочков</span></td>
                    <td>${m.price} ₽</td>
                    <td><b>${m.cost} ₽</b> <span style="color:${fcColor}; font-weight:700;">(${m.fc_pct}%)</span></td>
                    <td style="font-size:11px;">${compText}</td>
                    <td><span class="roll-8-badge">${m.recommended_price} ₽</span></td>
                </tr>`;
            }).join('');

            modal.innerHTML = `
            <div class="card-panel" style="max-width:1060px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #ff6900;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:14px;">
                    <h2 style="margin:0; font-size:18px; color:#ff6900; text-transform:uppercase;">🍣 Конструктор Техкарт (Стандарт: 8 кусочков в порции)</h2>
                    <div style="display:flex; gap:6px;">
                        <button type="button" class="quick-chip omega-internal-btn" onclick="window.openOmegaHub('zreport')">← Назад к Z-Отчёту</button>
                        <button type="button" class="quick-chip omega-internal-btn" style="color:#dc2626; border-color:#dc2626;" onclick="document.getElementById('omega-v12-modal').style.display='none'">✕ Закрыть</button>
                    </div>
                </div>
                <div class="card-panel" style="padding:14px; margin-bottom:14px;">
                    <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                        <select id="om-menu-id" style="flex:1; min-width:200px;">${menuOpts}</select>
                        <select id="om-ing-id" style="flex:1; min-width:180px;">${ingOpts}</select>
                        <input id="om-amount" type="number" step="0.005" placeholder="Вес (напр. 0.120 кг)" style="width:160px;">
                        <button type="button" class="btn-ready omega-internal-btn" style="padding:7px 14px; border-radius:6px; font-weight:700; cursor:pointer;" onclick="window.saveOmegaRecipe()">Сохранить граммовку</button>
                    </div>
                </div>
                <table>
                    <tr><th>Позиция (8 шт.)</th><th>Цена</th><th>Себестоимость (FC%)</th><th>Граммовки техкарты</th><th>Реком. цена</th></tr>
                    ${rowsHtml}
                </table>
            </div>`;
        });
    }

    window.saveOmegaRecipe = function() {
        const menuId = document.getElementById('om-menu-id').value;
        const ingId = document.getElementById('om-ing-id').value;
        const amount = document.getElementById('om-amount').value;
        fetch('/api/ultra/recipe_save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ menu_id: menuId, ingredient_id: ingId, amount: amount })
        }).then(() => window.openOmegaHub('recipes'));
    };

    window.recalcCashDrawer = function() {
        const expEl = document.getElementById('z-expected-val');
        const expected = expEl ? parseInt(expEl.getAttribute('data-expected') || '0', 10) : 0;
        let fact = 0;
        document.querySelectorAll('.bill-inp').forEach(inp => {
            const denom = parseInt(inp.getAttribute('data-denom') || '1', 10);
            const cnt = parseFloat(inp.value || '0') || 0;
            fact += Math.round(denom * cnt);
        });
        const diff = fact - expected;
        const resEl = document.getElementById('drawer-fact-result');
        if (!resEl) return;
        if (diff === 0) {
            resEl.style.color = '#16a34a';
            resEl.textContent = fact + ' ₽ (ИДЕАЛЬНО 0 ₽)';
        } else if (diff > 0) {
            resEl.style.color = '#38bdf8';
            resEl.textContent = fact + ' ₽ (Излишек +' + diff + ' ₽)';
        } else {
            resEl.style.color = '#dc2626';
            resEl.textContent = fact + ' ₽ (Недостача ' + diff + ' ₽)';
        }
    };

    window.copySupplierOrderText = function(btn) {
        if (!lastOmegaData) return;
        const lines = (lastOmegaData.procurement || []).map(p => '- ' + p.name + ': ' + p.order_qty + ' ' + p.unit);
        const text = 'Заявка на закуп сырья КРЕВЕТКА IS (' + lastOmegaData.date + '):\n' + (lines.join('\n') || 'Все позиции в норме');
        navigator.clipboard.writeText(text);
        btn.textContent = '✓ Скопировано в буфер!';
    };

    window.printOmegaZSlip = function() {
        if (!lastOmegaData) return;
        const d = lastOmegaData;
        const w = window.open('', '_blank', 'width=360,height=580');
        w.document.write(
            '<html><head><title>Z-Отчёт</title><style>body{font-family:monospace;width:270px;margin:10px auto;font-size:12px;}</style></head><body>' +
            '<h3>=== КРЕВЕТКА IS • Z-ОТЧЁТ ===</h3>' +
            '<p>Дата: ' + d.date + '</p><hr>' +
            '<p>Чеков проведено: <b>' + d.orders_count + '</b> (отмен: ' + d.cancelled_count + ')</p>' +
            '<p>ВЫРУЧКА ИТОГО: <b>' + d.total_revenue + ' Р</b></p>' +
            '<p> - Наличные: ' + d.cash_revenue + ' Р</p>' +
            '<p> - Карта / СБП: ' + d.card_revenue + ' Р</p><hr>' +
            '<p>Выплаты курьерам: ' + d.courier_payroll + ' Р</p>' +
            '<p>ФОТ цеха (часы): ' + d.hourly_payroll + ' Р</p>' +
            '<p>НАЛ В КАССЕ (РАСЧЁТ): <b>' + d.expected_drawer_cash + ' Р</b></p><hr>' +
            '<p>Подпись: _________________</p></body></html>'
        );
        w.document.close();
        w.focus();
        w.print();
        w.close();
    };

    // Плавающий пульт OMEGA DOCK в правом нижнем углу, который работает на 100% страниц
    function injectOmegaFloatingDock() {
        const path = window.location.pathname;
        if (path.startsWith('/site') || path.startsWith('/login') || path.startsWith('/track')) return;
        if (document.getElementById('omega-floating-dock')) return;

        const dock = document.createElement('div');
        dock.id = 'omega-floating-dock';
        dock.style.cssText = 'position:fixed; bottom:14px; right:14px; z-index:9990; display:flex; gap:6px; background:rgba(24,24,27,0.94); padding:6px 10px; border-radius:999px; border:1px solid #38bdf8; box-shadow:0 6px 20px rgba(0,0,0,0.45);';
        dock.innerHTML = `
            <button type="button" class="quick-chip omega-internal-btn" style="border-color:#38bdf8; color:#38bdf8; font-weight:800; cursor:pointer; padding:4px 10px;" onclick="window.openOmegaHub('zreport')">🧾 Z-Отчёт (F9)</button>
            <button type="button" class="quick-chip omega-internal-btn" style="border-color:#16a34a; color:#16a34a; font-weight:800; cursor:pointer; padding:4px 10px;" onclick="window.openOmegaHub('logistics')">🗺 Районы Инты</button>
            <button type="button" class="quick-chip omega-internal-btn" style="border-color:#ff6900; color:#ff6900; font-weight:800; cursor:pointer; padding:4px 10px;" onclick="window.openOmegaHub('recipes')">🍣 Техкарты (8 шт.)</button>
        `;
        document.body.appendChild(dock);
    }

    document.addEventListener('DOMContentLoaded', injectOmegaFloatingDock);
    setTimeout(injectOmegaFloatingDock, 600);
})();
