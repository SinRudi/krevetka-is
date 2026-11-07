(function() {
    // Встраиваем 3 монопольные вкладки прямо в существующее окно TITANIUM v20
    function injectSingularityTabs() {
        const modal = document.getElementById('titanium-v20-modal');
        if (!modal || modal.style.display === 'none') return;

        const tabRow = modal.querySelector('div[style*="flex-wrap:wrap; margin-bottom:16px;"]');
        if (!tabRow || document.getElementById('sg-tab-shield')) return;

        const extraTabs = [
            { id: 'sg_shield', label: '🛡 Щит Маржи (Анти-Инфляция)', color: '#ec4899' },
            { id: 'sg_rfm', label: '🧲 RFM-Удержание VIP Гостей', color: '#a855f7' },
            { id: 'sg_ai_prep', label: '🔮 ИИ-План Заготовок & Рейсы', color: '#06b6d4' }
        ];

        extraTabs.forEach(t => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.id = t.id === 'sg_shield' ? 'sg-tab-shield' : ('sg-tab-' + t.id);
            btn.className = 'ti-tab-btn ti-internal';
            btn.style.borderColor = t.color;
            btn.style.color = t.color;
            btn.innerHTML = t.label;
            btn.onclick = function() { window.openSingularityView(t.id); };
            tabRow.appendChild(btn);
        });
    }

    // Отслеживаем открытие модального окна TITANIUM
    const obs = new MutationObserver(() => injectSingularityTabs());
    document.addEventListener('DOMContentLoaded', () => {
        obs.observe(document.body, { childList: true, subtree: true });
    });

    window.openSingularityView = function(viewId) {
        let modal = document.getElementById('titanium-v20-modal');
        if (!modal) {
            window.openTitaniumSuite('zreport');
            setTimeout(() => window.openSingularityView(viewId), 350);
            return;
        }
        modal.style.display = 'flex';

        if (viewId === 'sg_shield') {
            fetch('/api/singularity/margin_shield?target_fc=28')
            .then(r => r.json())
            .then(d => renderMarginShield(modal, d));
        } else {
            fetch('/api/singularity/monopoly_intel')
            .then(r => r.json())
            .then(d => {
                if (viewId === 'sg_rfm') renderRfmRetention(modal, d);
                else renderAiPrepAndRoutes(modal, d);
            });
        }
    };

    function renderMarginShield(modal, d) {
        const ingOpts = (d.ingredients || []).map(i =>
            `<option value="${i.id}">${i.name} (Текущая закупка: ${i.cost_price} ₽ / ${i.unit || 'кг'})</option>`
        ).join('');

        const rows = (d.items || []).map(it => {
            const badgeCol = it.status === 'DANGER' ? '#ef4444' : (it.status === 'WARN' ? '#eab308' : '#10b981');
            const diffTxt = it.diff_price > 0 ? `<b style="color:#ef4444;">+${it.diff_price} ₽ (Нужно ${it.ideal_price} ₽)</b>` : `<span style="color:#10b981;">Запас прочности OK (${it.ideal_price} ₽)</span>`;
            return `<tr>
                <td><b>${it.name}</b> <span class="roll-8-badge" style="font-size:10px;">8 шт.</span></td>
                <td><b>${it.price} ₽</b></td>
                <td><b>${it.cost} ₽</b></td>
                <td><span class="roll-8-badge" style="border-color:${badgeCol}; color:${badgeCol}; font-weight:800;">${it.current_fc}%</span></td>
                <td><b style="color:#10b981;">+${it.margin_rub} ₽</b> с порции</td>
                <td>${diffTxt}</td>
            </tr>`;
        }).join('');

        const panel = modal.querySelector('.card-panel');
        if (!panel) return;
        const headerHtml = panel.innerHTML.split('<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px;">')[0];

        panel.innerHTML = `
            ${headerHtml}
            <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px;">
                <button type="button" class="ti-tab-btn ti-internal" onclick="window.openTitaniumSuite('zreport')">← Назад к Z-Отчёту и Базе</button>
                <button type="button" class="ti-tab-btn ti-internal active" style="border-color:#ec4899;color:#ec4899;" onclick="window.openSingularityView('sg_shield')">🛡 Щит Маржи (Анти-Инфляция)</button>
                <button type="button" class="ti-tab-btn ti-internal" style="border-color:#a855f7;color:#a855f7;" onclick="window.openSingularityView('sg_rfm')">🧲 RFM-Удержание VIP Гостей</button>
                <button type="button" class="ti-tab-btn ti-internal" style="border-color:#06b6d4;color:#06b6d4;" onclick="window.openSingularityView('sg_ai_prep')">🔮 ИИ-План Заготовок & Рейсы</button>
            </div>

            <div class="card-panel" style="padding:14px; margin-bottom:14px; border-left:4px solid #ec4899 !important;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:10px;">
                    <div>
                        <div style="font-size:14px; font-weight:900; color:#ec4899; text-transform:uppercase;">🛡 Симулятор накладной поставщика и Авто-Защита Маржи</div>
                        <div style="font-size:12px; opacity:0.8;">Измените закупочную цену любого сырья (лосось, сыр, рис) — система пересчитает все роллы и защитит вашу прибыль</div>
                    </div>
                    <button type="button" class="ti-tab-btn ti-internal active" style="background:#ec4899; color:#fff; border-color:#ec4899;" onclick="window.autoBalanceMenuPrices()">⚡ Авто-выровнять цены убыточных позиций (${d.loss_alerts} шт.) под Фудкост 28%</button>
                </div>
                <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                    <select id="sg-ing-select" style="flex:1; min-width:250px;">${ingOpts}</select>
                    <input type="number" step="10" id="sg-ing-newcost" placeholder="Новая цена закупки за кг/л (₽)" style="width:240px;">
                    <button type="button" class="ti-tab-btn ti-internal" style="border-color:#10b981; color:#10b981;" onclick="window.updateSupplierPrice()">Обновить накладную и пересчитать меню</button>
                </div>
            </div>

            <table>
                <tr>
                    <th>Позиция ролла (8 кусочков)</th>
                    <th>Текущая цена</th>
                    <th>Себестоимость</th>
                    <th>Фудкост %</th>
                    <th>Чистая маржа</th>
                    <th>Вердикт алгоритма (Цель FC 28%)</th>
                </tr>
                ${rows}
            </table>
        `;
    }

    function renderRfmRetention(modal, d) {
        const rows = (d.rfm_clients || []).map(c => {
            const msg = encodeURIComponent(
                `Здравствуйте! Это шеф доставки роллов «КРЕВЕТКА» (г. Инта) 🍤 Мы заметили, что вы не заказывали у нас уже ${c.days_silent} дн., и приготовили для вас закрытый бонус: порция фирменного ролла (8 кусочков) в подарок к любому заказу сегодня! Ждём вас!`
            );
            const waUrl = `https://wa.me/${c.wa_phone}?text=${msg}`;
            return `<tr>
                <td><b>${c.phone}</b><div style="font-size:11px; opacity:0.7;">${c.address}</div></td>
                <td><b>${c.orders_cnt}</b> зак.</td>
                <td><b style="color:#10b981;">${c.ltv} ₽</b></td>
                <td><b>${c.days_silent} дн. назад</b></td>
                <td><span class="roll-8-badge" style="border-color:${c.color}; color:${c.color}; font-weight:800;">${c.segment}</span></td>
                <td><a href="${waUrl}" target="_blank" class="ti-tab-btn ti-internal" style="text-decoration:none; border-color:#10b981; color:#10b981; display:inline-block;">💬 Вернуть в 1 клик (WhatsApp)</a></td>
            </tr>`;
        }).join('') || '<tr><td colspan="6">Оформите первые заказы с номером телефона, чтобы радар построил RFM-карту гостей</td></tr>';

        const panel = modal.querySelector('.card-panel');
        if (!panel) return;
        const headerHtml = panel.innerHTML.split('<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px;">')[0];

        panel.innerHTML = `
            ${headerHtml}
            <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px;">
                <button type="button" class="ti-tab-btn ti-internal" onclick="window.openTitaniumSuite('zreport')">← Назад к Z-Отчёту и Базе</button>
                <button type="button" class="ti-tab-btn ti-internal" style="border-color:#ec4899;color:#ec4899;" onclick="window.openSingularityView('sg_shield')">🛡 Щит Маржи (Анти-Инфляция)</button>
                <button type="button" class="ti-tab-btn ti-internal active" style="border-color:#a855f7;color:#a855f7;" onclick="window.openSingularityView('sg_rfm')">🧲 RFM-Удержание VIP Гостей</button>
                <button type="button" class="ti-tab-btn ti-internal" style="border-color:#06b6d4;color:#06b6d4;" onclick="window.openSingularityView('sg_ai_prep')">🔮 ИИ-План Заготовок & Рейсы</button>
            </div>

            <div class="card-panel" style="padding:14px; margin-bottom:14px; border-left:4px solid #a855f7 !important;">
                <div style="font-size:14px; font-weight:900; color:#a855f7; text-transform:uppercase;">🧲 Радар перехвата уходящих VIP-гостей (Найдено под угрозой оттока: ${d.sleeping_vips_count} чел.)</div>
                <div style="font-size:12px; opacity:0.85; margin-top:3px;">Система сама находит постоянных клиентов Инты, которые давно не делали заказ, и формирует персональное приглашение в WhatsApp</div>
            </div>

            <table>
                <tr>
                    <th>Клиент / Адрес в Инте</th>
                    <th>Заказов</th>
                    <th>Выручка (LTV)</th>
                    <th>Пауза без заказов</th>
                    <th>RFM-Статус</th>
                    <th>Действие перехвата</th>
                </tr>
                ${rows}
            </table>
        `;
    }

    function renderAiPrepAndRoutes(modal, d) {
        const prepRows = (d.prep_forecast || []).map(p => `
            <tr>
                <td><b>${p.station}</b></td>
                <td><b>${p.item}</b></td>
                <td><span class="roll-8-badge" style="border-color:#06b6d4; color:#06b6d4; font-size:13px; font-weight:900;">${p.recommended_kg} кг</span></td>
                <td style="font-size:12px; opacity:0.85;">${p.raw_note}</td>
            </tr>
        `).join('');

        const routeCards = (d.route_bundles || []).map(r => {
            const listHtml = (r.orders || []).map(o =>
                `<div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.06); font-size:12px;">
                    <span><b>#${o.id}</b> • ${o.address}</span>
                    <a href="/live/${o.id}" target="_blank" style="color:#38bdf8; text-decoration:none;">Трекер гостя ↗</a>
                </div>`
            ).join('') || '<div style="font-size:12px; opacity:0.6;">В этом секторе сейчас нет ожидающих доставок</div>';

            return `<div class="card-panel" style="padding:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <b style="color:#06b6d4; font-size:13px;">${r.route_name}</b>
                    <span class="roll-8-badge">В связку: ${r.count} зак.</span>
                </div>
                ${listHtml}
            </div>`;
        }).join('');

        const panel = modal.querySelector('.card-panel');
        if (!panel) return;
        const headerHtml = panel.innerHTML.split('<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px;">')[0];

        panel.innerHTML = `
            ${headerHtml}
            <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px;">
                <button type="button" class="ti-tab-btn ti-internal" onclick="window.openTitaniumSuite('zreport')">← Назад к Z-Отчёту и Базе</button>
                <button type="button" class="ti-tab-btn ti-internal" style="border-color:#ec4899;color:#ec4899;" onclick="window.openSingularityView('sg_shield')">🛡 Щит Маржи (Анти-Инфляция)</button>
                <button type="button" class="ti-tab-btn ti-internal" style="border-color:#a855f7;color:#a855f7;" onclick="window.openSingularityView('sg_rfm')">🧲 RFM-Удержание VIP Гостей</button>
                <button type="button" class="ti-tab-btn ti-internal active" style="border-color:#06b6d4;color:#06b6d4;" onclick="window.openSingularityView('sg_ai_prep')">🔮 ИИ-План Заготовок & Рейсы</button>
            </div>

            <div class="card-panel" style="padding:14px; margin-bottom:14px; border-left:4px solid #06b6d4 !important;">
                <div style="font-size:14px; font-weight:900; color:#06b6d4; text-transform:uppercase;">
                    🔮 Утренний ИИ-Норматив Заготовок П/Ф на смену • Прогноз: ~${d.est_daily_orders} чеков (~${d.est_rolls_portions} порций роллов по 8 шт.)
                </div>
                <div style="font-size:12px; opacity:0.85; margin-top:3px;">
                    Режим дня: <b>${d.is_peak_day ? '🔥 ПЯТНИЦА / ВЫХОДНОЙ ПИК (+45% к заготовкам риса и лосося)' : 'Будний график смены'}</b>
                </div>
            </div>

            <table>
                <tr><th>Участок цеха</th><th>Полуфабрикат</th><th>Норма заготовки на утро</th><th>Технологическая подсказка шефу</th></tr>
                ${prepRows}
            </table>

            <h3 style="margin:18px 0 10px; font-size:14px; text-transform:uppercase; color:#10b981;">🚀 Умная группировка попутных рейсов курьеров по секторам Инты (Авто-Батчинг)</h3>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:10px;">
                ${routeCards}
            </div>
        `;
    }

    window.updateSupplierPrice = function() {
        const ingId = document.getElementById('sg-ing-select').value;
        const newCost = document.getElementById('sg-ing-newcost').value;
        if (!newCost) return;
        fetch('/api/singularity/update_ing_cost', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ingredient_id: ingId, cost_price: newCost })
        }).then(() => window.openSingularityView('sg_shield'));
    };

    window.autoBalanceMenuPrices = function() {
        fetch('/api/singularity/apply_auto_prices', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_fc: 28.0, only_danger: true })
        })
        .then(r => r.json())
        .then(d => {
            alert('Цены автоматически скорректированы под целевой фудкост 28% для ' + (d.updated_count || 0) + ' позиций!');
            window.openSingularityView('sg_shield');
        });
    };
})();
