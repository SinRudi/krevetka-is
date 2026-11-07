(function() {
    let titaniumCache = null;

    // 1. Удаляем любые следы сломанного поиска и нижнего дока, если они остались в DOM
    function cleanBrokenElements() {
        ['pos-instant-search-bar', 'omega-floating-dock', 'franchise-hq-modal'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.remove();
        });
    }

    // 2. Привязываем существующий в вёрстке кассы поиск («Быстрый поиск блюда, например Дракон») к мгновенной фильтрации
    function bindNativeSearchInput() {
        const nativeSearch = document.querySelector('input[placeholder*="Быстрый поиск"], input[placeholder*="Дракон"]');
        if (nativeSearch && !nativeSearch.dataset.titaniumBound) {
            nativeSearch.dataset.titaniumBound = '1';
            nativeSearch.addEventListener('input', function() {
                const q = (this.value || '').trim().toLowerCase();
                document.querySelectorAll('.menu-item, .pos-card, [onclick*="addToCart"], [onclick*="add_to_cart"]').forEach(card => {
                    const txt = (card.innerText || '').toLowerCase();
                    card.style.display = (!q || txt.includes(q)) ? '' : 'none';
                });
            });
        }
    }

    // 3. Перехватываем нажатие на кнопки в верхней шапке («Z-Отчёт • Техкарты», «P&L • ABC • Цех», F9)
    document.addEventListener('click', function(e) {
        const el = e.target.closest('button, a, .quick-chip, [onclick]');
        if (!el || el.classList.contains('ti-internal')) return;

        const txt = (el.innerText || el.textContent || '').toLowerCase();
        const oc = (el.getAttribute('onclick') || '').toLowerCase();

        if (txt.includes('z-отч') || txt.includes('z отч') || oc.includes('zreport') || oc.includes('openultracentermodal') || oc.includes('openomegahub')) {
            e.preventDefault();
            e.stopPropagation();
            window.openTitaniumSuite('zreport');
        } else if (txt.includes('p&l') || txt.includes('abc') || oc.includes('openerpcommandmodal')) {
            e.preventDefault();
            e.stopPropagation();
            window.openTitaniumSuite('abc');
        }
    }, true);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'F9') {
            e.preventDefault();
            window.openTitaniumSuite('zreport');
        } else if (e.key === 'F3') {
            const nativeSearch = document.querySelector('input[placeholder*="Быстрый поиск"], input[placeholder*="Дракон"]');
            if (nativeSearch) {
                e.preventDefault();
                nativeSearch.focus();
                nativeSearch.select();
            }
        }
    });

    // Совместимость со старыми глобальными функциями
    window.openUltraCenterModal = function(t) { window.openTitaniumSuite(t || 'zreport'); };
    window.openOmegaHub = function(t) { window.openTitaniumSuite(t || 'zreport'); };
    window.openErpCommandModal = function() { window.openTitaniumSuite('abc'); };

    window.openTitaniumSuite = function(tab) {
        tab = tab || 'zreport';
        let modal = document.getElementById('titanium-v20-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'titanium-v20-modal';
            modal.style.cssText = 'position:fixed; inset:0; background:rgba(7,9,14,0.86); z-index:100000; display:flex; align-items:center; justify-content:center; padding:16px; backdrop-filter:blur(5px);';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';
        modal.innerHTML = '<div class="card-panel" style="max-width:1100px; width:100%; padding:28px; text-align:center; border:1px solid #ff6900;">⚡ Загрузка ядра KREVETKA IS • TITANIUM v20...</div>';

        if (tab === 'recipes') {
            renderRecipesEditor(modal);
            return;
        }

        fetch('/api/titanium/full_suite?days=14')
        .then(r => r.json())
        .then(d => {
            titaniumCache = d;
            renderTitaniumWindow(modal, d, tab);
        })
        .catch(err => {
            modal.innerHTML = '<div class="card-panel" style="max-width:520px; padding:24px;">Ошибка загрузки: ' + err + '<br><br><button class="ti-tab-btn ti-internal" onclick="document.getElementById(\'titanium-v20-modal\').style.display=\'none\'">Закрыть</button></div>';
        });
    };

    function buildHeader(d, activeTab) {
        const tabs = [
            { id: 'zreport', label: '🧾 Z-Отчёт & Сверка сейфа' },
            { id: 'abc', label: '📊 P&L • ABC-Матрица меню' },
            { id: 'prep', label: '🔪 Цех П/Ф (Рис / Лосось)' },
            { id: 'inventory', label: '⚖️ Ревизия склада (Ведомость)' },
            { id: 'recipes', label: '🍣 Техкарты (Стандарт 8 шт.)' },
            { id: 'inta', label: '🗺 Диспетчерская г. Инта' }
        ];
        const buttons = tabs.map(t =>
            `<button type="button" class="ti-tab-btn ti-internal ${activeTab===t.id?'active':''}" onclick="window.openTitaniumSuite('${t.id}')">${t.label}</button>`
        ).join('');

        return `
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px; padding-bottom:12px; border-bottom:1px solid rgba(148,163,184,0.2);">
                <div>
                    <div style="font-size:18px; font-weight:900; color:#ff6900; letter-spacing:0.3px;">🍤 КРЕВЕТКА IS • TITANIUM v20 (УРОВЕНЬ IIKO / SABY PRESTO)</div>
                    <div style="font-size:12px; opacity:0.78; margin-top:2px;">${d ? d.period_title : 'Производственный контур'} • Строгий стандарт нарезки: <b>8 кусочков</b></div>
                </div>
                <div style="display:flex; gap:8px;">
                    <a href="/tv_board" target="_blank" class="ti-tab-btn ti-internal" style="text-decoration:none; border-color:#10b981; color:#10b981;">📺 ТВ-Табло Гостя ↗</a>
                    <button type="button" class="ti-tab-btn ti-internal" style="border-color:#ef4444; color:#ef4444;" onclick="document.getElementById('titanium-v20-modal').style.display='none'">✕ Закрыть (Esc)</button>
                </div>
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px;">${buttons}</div>
        `;
    }

    function renderTitaniumWindow(modal, d, tab) {
        let content = '';

        if (tab === 'zreport') {
            const procRows = (d.procurement || []).map(p => `
                <tr>
                    <td><b>${p.name}</b></td>
                    <td style="color:#ef4444; font-weight:700;">${p.stock} ${p.unit}</td>
                    <td>${p.min_stock} ${p.unit}</td>
                    <td><b style="color:#10b981;">+${p.order_qty} ${p.unit}</b></td>
                    <td>~${p.est_cost} ₽</td>
                </tr>
            `).join('') || '<tr><td colspan="5" style="color:#10b981;">✓ Все позиции сырья выше минимального норматива</td></tr>';

            content = `
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:10px; margin-bottom:16px;">
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">ВЫРУЧКА (${d.orders_count} чеков)</div>
                        <div style="font-size:22px; font-weight:900; margin-top:4px;">${d.total_revenue} ₽</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">Средний чек: <b>${d.avg_check} ₽</b> • Отмен: <b>${d.cancelled_count}</b></div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">НАЛИЧНЫЕ vs БЕЗНАЛ</div>
                        <div style="font-size:15px; font-weight:800; color:#10b981; margin-top:4px;">💵 Наличные: ${d.cash_revenue} ₽</div>
                        <div style="font-size:15px; font-weight:800; color:#38bdf8; margin-top:2px;">💳 Карта / СБП: ${d.card_revenue} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">ФОТ СМЕНЫ (КУРЬЕРЫ + ЦЕХ)</div>
                        <div style="font-size:14px; font-weight:800; color:#ff6900; margin-top:4px;">🛵 Курьерам (сдельно): ${d.courier_payroll} ₽</div>
                        <div style="font-size:13px; margin-top:3px;">👨‍🍳 Поварам/Кассе (часы): <b>${d.hourly_payroll} ₽</b></div>
                    </div>
                    <div class="card-panel" style="padding:12px; border-left:4px solid #10b981 !important;">
                        <div style="font-size:11px; opacity:0.7;">ОЖИДАЕМЫЙ НАЛ В ЯЩИКЕ</div>
                        <div style="font-size:22px; font-weight:900; color:#10b981; margin-top:4px;" id="ti-expected-cash" data-val="${d.expected_drawer_cash}">${d.expected_drawer_cash} ₽</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">Чистая прибыль: <b>${d.net_profit} ₽</b></div>
                    </div>
                </div>

                <div class="card-panel" style="padding:14px; margin-bottom:16px; border-left:4px solid #38bdf8 !important;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                        <div style="font-size:13px; font-weight:800; color:#38bdf8; text-transform:uppercase;">🧮 Покупюрный калькулятор закрытия смены (Сверка денежного ящика)</div>
                        <button type="button" class="ti-tab-btn ti-internal" onclick="window.printTitaniumZSlip()">🖨 Напечатать Z-Чек смены</button>
                    </div>
                    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(115px, 1fr)); gap:8px; align-items:center;">
                        <div><label style="font-size:11px;">Купюры 5000 ₽</label><input type="number" min="0" value="0" class="ti-bill" data-d="5000" oninput="window.calcTitaniumDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Купюры 2000 ₽</label><input type="number" min="0" value="0" class="ti-bill" data-d="2000" oninput="window.calcTitaniumDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Купюры 1000 ₽</label><input type="number" min="0" value="0" class="ti-bill" data-d="1000" oninput="window.calcTitaniumDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Купюры 500 ₽</label><input type="number" min="0" value="0" class="ti-bill" data-d="500" oninput="window.calcTitaniumDrawer()" style="width:100%;"></div>
                        <div><label style="font-size:11px;">Мелкие / Монеты (₽)</label><input type="number" min="0" value="0" class="ti-bill" data-d="1" oninput="window.calcTitaniumDrawer()" style="width:100%;"></div>
                        <div style="padding:8px; border-radius:8px; background:rgba(56,189,248,0.1); text-align:center;">
                            <div style="font-size:10px; opacity:0.75;">ИТОГ СВЕРКИ КАССЫ</div>
                            <div id="ti-drawer-verdict" style="font-size:13px; font-weight:900; margin-top:3px;">Введите купюры</div>
                        </div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
                    <h3 style="margin:0; font-size:13px; text-transform:uppercase; color:#eab308;">📦 Авто-заявка поставщику по минимальным остаткам</h3>
                    <button type="button" class="ti-tab-btn ti-internal" style="border-color:#10b981; color:#10b981;" onclick="window.copyTitaniumOrder(this)">📋 Скопировать список для WhatsApp</button>
                </div>
                <table>
                    <tr><th>Ингредиент</th><th>Остаток</th><th>Мин. норма</th><th>Рекомендуемый закуп</th><th>Ориентир суммы</th></tr>
                    ${procRows}
                </table>
            `;
        } else if (tab === 'abc') {
            const abcRows = (d.abc_matrix || []).map(it => {
                const col = it.group === 'A' ? '#10b981' : (it.group === 'B' ? '#eab308' : '#ef4444');
                const desc = it.group === 'A' ? 'Группа A (Лидер кассы — 80% оборота)' : (it.group === 'B' ? 'Группа B (Стабильный спрос)' : 'Группа C (Аутсайдер)');
                return `<tr>
                    <td><b>${it.name}</b> <span class="roll-8-badge" style="font-size:10px;">8 шт.</span></td>
                    <td><b>${it.qty}</b> порц.</td>
                    <td><b>${it.rev} ₽</b> (${it.share}%)</td>
                    <td><span class="roll-8-badge" style="border-color:${col}; color:${col}; font-weight:800;">${desc}</span></td>
                </tr>`;
            }).join('') || '<tr><td colspan="4">Нет продаж за выбранный период</td></tr>';

            content = `
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:10px; margin-bottom:16px;">
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">ВЫРУЧКА ПРОДАЖ</div>
                        <div style="font-size:22px; font-weight:900; margin-top:4px;">${d.total_revenue} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">СЕБЕСТОИМОСТЬ СЫРЬЯ (FOODCOST)</div>
                        <div style="font-size:22px; font-weight:900; color:#eab308; margin-top:4px;">${d.food_cost} ₽ (${d.food_cost_pct}%)</div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">СУММАРНЫЙ ФОТ (ЦЕХ + КУРЬЕРЫ)</div>
                        <div style="font-size:22px; font-weight:900; color:#38bdf8; margin-top:4px;">${d.hourly_payroll + d.courier_payroll} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:12px; border-left:4px solid #10b981 !important;">
                        <div style="font-size:11px; opacity:0.7;">ЧИСТАЯ ОПЕРАЦИОННАЯ ПРИБЫЛЬ</div>
                        <div style="font-size:22px; font-weight:900; color:#10b981; margin-top:4px;">${d.net_profit} ₽</div>
                    </div>
                </div>
                <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#ff6900;">🏆 ABC-Матрица меню (Как в iikoOffice / Saby Presto)</h3>
                <table>
                    <tr><th>Позиция ролла (8 кусочков)</th><th>Продано порций</th><th>Выручка (Доля)</th><th>ABC-Классификация</th></tr>
                    ${abcRows}
                </table>
            `;
        } else if (tab === 'prep') {
            const prepRows = (d.prep_acts || []).map(p => `
                <tr>
                    <td>${p.created_at}</td>
                    <td><b>${p.prep_name}</b></td>
                    <td>${p.raw_weight} кг</td>
                    <td><b style="color:#10b981;">${p.yield_weight} кг</b></td>
                    <td>${p.waste_pct}%</td>
                    <td><b>${p.cost_per_kg} ₽/кг</b></td>
                </tr>
            `).join('') || '<tr><td colspan="6">Актов проработки за сегодня ещё нет</td></tr>';

            content = `
                <div class="card-panel" style="padding:14px; margin-bottom:16px; border-left:4px solid #ff6900 !important;">
                    <div style="font-size:13px; font-weight:800; color:#ff6900; margin-bottom:10px; text-transform:uppercase;">🔪 Акт разделки сырья и заготовки полуфабрикатов (Рис / Лосось / Угорь / Соусы)</div>
                    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:8px; align-items:end;">
                        <div>
                            <label style="font-size:11px;">Тип заготовки (П/Ф)</label>
                            <select id="ti-prep-name" style="width:100%;">
                                <option value="Разделка Лосося (Филе из тушки)">Разделка Лосося (Филе из тушки)</option>
                                <option value="Варка Суши-Риса (с заправкой Мицукан)">Варка Суши-Риса (с заправкой Мицукан)</option>
                                <option value="Замес соуса Лава / Спайси">Замес соуса Лава / Спайси</option>
                                <option value="Нарезка Угря / Креветки П/Ф">Нарезка Угря / Креветки П/Ф</option>
                            </select>
                        </div>
                        <div>
                            <label style="font-size:11px;">Вес брутто (до обработки, кг)</label>
                            <input type="number" step="0.05" id="ti-prep-raw" placeholder="Напр. 5.0" style="width:100%;">
                        </div>
                        <div>
                            <label style="font-size:11px;">Выход нетто (чистый П/Ф, кг)</label>
                            <input type="number" step="0.05" id="ti-prep-yield" placeholder="Напр. 3.65" style="width:100%;">
                        </div>
                        <div>
                            <label style="font-size:11px;">Стоимость закладки сырья (₽)</label>
                            <input type="number" step="10" id="ti-prep-cost" placeholder="Напр. 6500" style="width:100%;">
                        </div>
                        <button type="button" class="ti-tab-btn ti-internal active" style="height:36px;" onclick="window.submitTitaniumPrep()">Провести акт П/Ф</button>
                    </div>
                </div>
                <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase;">📋 Журнал актов переработки и реальная себестоимость П/Ф за 1 кг</h3>
                <table>
                    <tr><th>Время</th><th>Полуфабрикат</th><th>Вес Брутто</th><th>Выход Нетто</th><th>% Отхода/Уварки</th><th>Чистая себест. 1 кг</th></tr>
                    ${prepRows}
                </table>
            `;
        } else if (tab === 'inventory') {
            const ingOpts = (d.ingredients || []).map(i =>
                `<option value="${i.id}">${i.name} (По базе: ${i.stock} ${i.unit} • ${i.cost_price} ₽/${i.unit})</option>`
            ).join('');

            const audRows = (d.inventory_audits || []).map(a => {
                const col = a.diff_qty < 0 ? '#ef4444' : (a.diff_qty > 0 ? '#38bdf8' : '#10b981');
                const label = a.diff_qty < 0 ? `Недостача ${a.diff_qty} (${a.diff_rub} ₽)` : (a.diff_qty > 0 ? `Излишек +${a.diff_qty} (+${a.diff_rub} ₽)` : 'Идеально 0');
                return `<tr>
                    <td>${a.created_at}</td>
                    <td><b>${a.ing_name}</b></td>
                    <td>${a.expected_stock}</td>
                    <td><b>${a.actual_stock}</b></td>
                    <td style="color:${col}; font-weight:800;">${label}</td>
                </tr>`;
            }).join('') || '<tr><td colspan="5">Сличительных ведомостей ещё не проводилось</td></tr>';

            content = `
                <div class="card-panel" style="padding:14px; margin-bottom:16px; border-left:4px solid #eab308 !important;">
                    <div style="font-size:13px; font-weight:800; color:#eab308; margin-bottom:10px; text-transform:uppercase;">⚖️ Сличительная ведомость (Взвешивание фактических остатков на весах)</div>
                    <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                        <select id="ti-inv-id" style="flex:1; min-width:240px;">${ingOpts}</select>
                        <input type="number" step="0.01" id="ti-inv-actual" placeholder="Фактический вес на весах (кг/л)" style="width:230px;">
                        <button type="button" class="ti-tab-btn ti-internal active" onclick="window.submitTitaniumInventory()">Зафиксировать факт ревизии</button>
                    </div>
                </div>
                <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase;">📊 Результаты инвентаризаций (Контроль недостач и пересорта цеха)</h3>
                <table>
                    <tr><th>Дата ревизии</th><th>Сырьё</th><th>Книжный остаток</th><th>Факт на весах</th><th>Разница (Недостача / Излишек)</th></tr>
                    ${audRows}
                </table>
            `;
        } else if (tab === 'inta') {
            const zRows = (d.zones || []).map(z => `
                <tr>
                    <td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${z.color};margin-right:8px;"></span><b>${z.name}</b></td>
                    <td><b>${z.cnt}</b> зак.</td>
                    <td><b>${z.rev} ₽</b></td>
                    <td style="color:#ff6900; font-weight:800;">${z.fee} ₽</td>
                    <td><span class="roll-8-badge">Норматив SLA: ${z.sla}</span></td>
                </tr>
            `).join('');

            content = `
                <h3 style="margin:0 0 10px; font-size:14px; text-transform:uppercase; color:#10b981;">🗺 Логистическая матрица районов г. Инта и сдельный ФОТ курьеров</h3>
                <table>
                    <tr><th>Зона доставки г. Инта</th><th>Выполнено заказов</th><th>Выручка района</th><th>Выплаты курьерам</th><th>Целевой SLA</th></tr>
                    ${zRows}
                </table>
            `;
        }

        modal.innerHTML = `
            <div class="card-panel" style="max-width:1120px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #ff6900;">
                ${buildHeader(d, tab)}
                ${content}
            </div>
        `;
    }

    function renderRecipesEditor(modal) {
        fetch('/api/ultra/recipes_matrix')
        .then(r => r.json())
        .then(d => {
            const menuOpts = (d.menu_items || []).map(m =>
                `<option value="${m.id}">${m.name} (Витрина: ${m.price} ₽ • Себест: ${m.cost} ₽)</option>`
            ).join('');
            const ingOpts = (d.ingredients || []).map(i =>
                `<option value="${i.id}">${i.name} (${i.cost_price} ₽ / ${i.unit || 'кг'})</option>`
            ).join('');
            const rowsHtml = (d.menu_items || []).map(m => {
                const fcCol = m.fc_pct > 35 ? '#ef4444' : (m.fc_pct > 0 ? '#10b981' : '#eab308');
                const comp = (m.recipe || []).map(rc => `${rc.ing_name}: ${rc.amount}${rc.unit}`).join(', ') || 'Граммовки не заданы';
                return `<tr>
                    <td><b>${m.name}</b> <span class="roll-8-badge" style="font-size:10px;">8 шт.</span></td>
                    <td><b>${m.price} ₽</b></td>
                    <td><b>${m.cost} ₽</b> <span style="color:${fcCol}; font-weight:800;">(${m.fc_pct}%)</span></td>
                    <td style="font-size:11px;">${comp}</td>
                    <td><span class="roll-8-badge">${m.recommended_price} ₽</span></td>
                </tr>`;
            }).join('');

            modal.innerHTML = `
                <div class="card-panel" style="max-width:1120px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #ff6900;">
                    ${buildHeader(titaniumCache, 'recipes')}
                    <div class="card-panel" style="padding:14px; margin-bottom:14px;">
                        <div style="font-size:12px; font-weight:800; color:#ff6900; margin-bottom:8px; text-transform:uppercase;">➕ Редактор технологических карт (Стандарт порции: 8 кусочков, 0 = удалить ингредиент)</div>
                        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                            <select id="ti-tc-menu" style="flex:1; min-width:220px;">${menuOpts}</select>
                            <select id="ti-tc-ing" style="flex:1; min-width:190px;">${ingOpts}</select>
                            <input id="ti-tc-amt" type="number" step="0.005" placeholder="Брутто/Нетто (напр. 0.120 кг)" style="width:190px;">
                            <button type="button" class="ti-tab-btn ti-internal active" onclick="window.saveTitaniumRecipe()">Сохранить в техкарту</button>
                        </div>
                    </div>
                    <table>
                        <tr><th>Блюдо (8 кусочков)</th><th>Цена</th><th>Себестоимость (Foodcost %)</th><th>Состав техкарты</th><th>Реком. цена (FC 28%)</th></tr>
                        ${rowsHtml}
                    </table>
                </div>
            `;
        });
    }

    window.saveTitaniumRecipe = function() {
        const menuId = document.getElementById('ti-tc-menu').value;
        const ingId = document.getElementById('ti-tc-ing').value;
        const amount = document.getElementById('ti-tc-amt').value;
        fetch('/api/ultra/recipe_save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ menu_id: menuId, ingredient_id: ingId, amount: amount })
        }).then(() => window.openTitaniumSuite('recipes'));
    };

    window.submitTitaniumPrep = function() {
        const name = document.getElementById('ti-prep-name').value;
        const rawW = document.getElementById('ti-prep-raw').value;
        const yieldW = document.getElementById('ti-prep-yield').value;
        const cost = document.getElementById('ti-prep-cost').value;
        fetch('/api/titanium/prep_act', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prep_name: name, raw_weight: rawW, yield_weight: yieldW, raw_cost_total: cost })
        }).then(() => window.openTitaniumSuite('prep'));
    };

    window.submitTitaniumInventory = function() {
        const ingId = document.getElementById('ti-inv-id').value;
        const actual = document.getElementById('ti-inv-actual').value;
        fetch('/api/titanium/inventory_check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ingredient_id: ingId, actual_stock: actual })
        }).then(() => window.openTitaniumSuite('inventory'));
    };

    window.calcTitaniumDrawer = function() {
        const expEl = document.getElementById('ti-expected-cash');
        const expected = expEl ? parseInt(expEl.getAttribute('data-val') || '0', 10) : 0;
        let fact = 0;
        document.querySelectorAll('.ti-bill').forEach(inp => {
            const denom = parseInt(inp.getAttribute('data-d') || '1', 10);
            const cnt = parseFloat(inp.value || '0') || 0;
            fact += Math.round(denom * cnt);
        });
        const diff = fact - expected;
        const vEl = document.getElementById('ti-drawer-verdict');
        if (!vEl) return;
        if (diff === 0) {
            vEl.style.color = '#10b981';
            vEl.textContent = fact + ' ₽ (СХОДИТСЯ В 0 ₽)';
        } else if (diff > 0) {
            vEl.style.color = '#38bdf8';
            vEl.textContent = fact + ' ₽ (Излишек +' + diff + ' ₽)';
        } else {
            vEl.style.color = '#ef4444';
            vEl.textContent = fact + ' ₽ (Недостача ' + diff + ' ₽)';
        }
    };

    window.copyTitaniumOrder = function(btn) {
        if (!titaniumCache) return;
        const lines = (titaniumCache.procurement || []).map(p => '• ' + p.name + ': ' + p.order_qty + ' ' + p.unit);
        navigator.clipboard.writeText('Заявка на закуп сырья КРЕВЕТКА (' + titaniumCache.date + '):\n' + (lines.join('\n') || 'Все остатки в норме'));
        btn.textContent = '✓ Скопировано!';
    };

    window.printTitaniumZSlip = function() {
        if (!titaniumCache) return;
        const d = titaniumCache;
        const w = window.open('', '_blank', 'width=360,height=580');
        w.document.write(
            '<html><head><title>Z-Отчёт КРЕВЕТКА</title><style>body{font-family:monospace;width:270px;margin:10px auto;font-size:12px;}</style></head><body>' +
            '<h3>=== КРЕВЕТКА IS • Z-ОТЧЁТ ===</h3>' +
            '<p>Дата: ' + d.date + '</p><hr>' +
            '<p>Выполнено чеков: <b>' + d.orders_count + '</b> (отмен: ' + d.cancelled_count + ')</p>' +
            '<p>ВЫРУЧКА ИТОГО: <b>' + d.total_revenue + ' Р</b></p>' +
            '<p> - Наличные: ' + d.cash_revenue + ' Р</p>' +
            '<p> - Карта / СБП: ' + d.card_revenue + ' Р</p><hr>' +
            '<p>Выплаты курьерам (сдельно): ' + d.courier_payroll + ' Р</p>' +
            '<p>ФОТ цеха (почасовая): ' + d.hourly_payroll + ' Р</p>' +
            '<p>НАЛ В КАССЕ (РАСЧЁТ): <b>' + d.expected_drawer_cash + ' Р</b></p><hr>' +
            '<p>Подпись кассира: _______________</p></body></html>'
        );
        w.document.close();
        w.focus();
        w.print();
        w.close();
    };

    document.addEventListener('DOMContentLoaded', function() {
        cleanBrokenElements();
        bindNativeSearchInput();
    });
    setTimeout(function() {
        cleanBrokenElements();
        bindNativeSearchInput();
    }, 350);
})();
