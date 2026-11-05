(function() {
    // === 1. ЖИВАЯ CRM-КАРТОЧКА КЛИЕНТА И БЫСТРЫЕ ЧИПЫ НА КАССЕ (/) ===
    function initCashierCRM() {
        const phoneInputs = document.querySelectorAll(
            'input[placeholder*="Телефон"], input[placeholder*="телефон"], input[name="phone"], #phone, #client_phone'
        );
        const addrInputs = document.querySelectorAll(
            'input[placeholder*="Адрес"], input[placeholder*="адрес"], input[name="address"], #address, #client_address'
        );
        const commentInputs = document.querySelectorAll(
            'input[placeholder*="Коммент"], textarea[placeholder*="Коммент"], input[name="comment"], textarea[name="comment"], #comment'
        );

        if (phoneInputs.length > 0) {
            const pInp = phoneInputs[0];
            let crmBox = document.getElementById('live-crm-card');
            if (!crmBox) {
                crmBox = document.createElement('div');
                crmBox.id = 'live-crm-card';
                crmBox.style.cssText = 'display:none; margin-top:6px; margin-bottom:8px; padding:8px 10px; border-radius:6px; font-size:11px; border:1px solid rgba(56,189,248,0.35); background:rgba(56,189,248,0.08);';
                pInp.insertAdjacentElement('afterend', crmBox);
            }

            let timer = null;
            pInp.addEventListener('input', function() {
                clearTimeout(timer);
                const val = (this.value || '').trim();
                if (val.replace(/\D/g, '').length < 6) {
                    crmBox.style.display = 'none';
                    return;
                }
                timer = setTimeout(() => {
                    fetch('/api/crm/lookup?phone=' + encodeURIComponent(val))
                    .then(r => r.json())
                    .then(d => {
                        if (!d || !d.found) {
                            crmBox.style.display = 'block';
                            crmBox.style.borderColor = 'rgba(161,161,170,0.3)';
                            crmBox.innerHTML = '✨ <b>Новый клиент</b> — первый заказ в базе';
                            return;
                        }
                        crmBox.style.display = 'block';
                        crmBox.style.borderColor = d.tier_color;
                        let html = `<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px;">
                            <span style="font-weight:800; color:${d.tier_color};">★ ${d.tier} (${d.orders_count} зак. • ${d.total_spent} ₽)</span>
                            <span style="font-weight:700; color:#16a34a;">🎁 Бонусы: ${d.bonuses} ₽</span>
                        </div>`;
                        if (d.last_address) {
                            html += `<div style="margin-top:5px; display:flex; align-items:center; justify-content:space-between; gap:6px;">
                                <span>📍 <b>${d.last_address}</b></span>
                                <button type="button" class="quick-chip" id="crm-fill-addr-btn" style="padding:2px 8px; font-size:10px; border-color:#ff6900; color:#ff6900;">Подставить адрес</button>
                            </div>`;
                        }
                        if (d.favorites && d.favorites.length) {
                            html += `<div style="margin-top:4px; opacity:0.85;">❤️ Любит: ${d.favorites.join(', ')}</div>`;
                        }
                        crmBox.innerHTML = html;

                        const fillBtn = document.getElementById('crm-fill-addr-btn');
                        if (fillBtn && addrInputs.length > 0) {
                            fillBtn.onclick = function() {
                                addrInputs[0].value = d.last_address;
                                addrInputs[0].dispatchEvent(new Event('input', { bubbles: true }));
                            };
                        }
                    }).catch(() => {});
                }, 250);
            });
        }

        // Быстрые чипы кассира (палочки, сдача, комментарии)
        if (commentInputs.length > 0 && !document.getElementById('cashier-fast-chips')) {
            const cInp = commentInputs[0];
            const chipsWrap = document.createElement('div');
            chipsWrap.id = 'cashier-fast-chips';
            chipsWrap.style.cssText = 'display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; margin-bottom:6px;';
            const presets = [
                '🥢 2 перс.', '🥢 3 перс.', '🥢 4 перс.',
                '💵 Сдача с 1000', '💵 Сдача с 5000',
                '🔕 Домофон не раб.', '⏰ К времени'
            ];
            presets.forEach(label => {
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'quick-chip';
                b.style.cssText = 'padding:3px 7px; font-size:10px; cursor:pointer;';
                b.textContent = label;
                b.onclick = function() {
                    const cur = (cInp.value || '').trim();
                    cInp.value = cur ? (cur + ' | ' + label) : label;
                    cInp.dispatchEvent(new Event('input', { bubbles: true }));
                };
                chipsWrap.appendChild(b);
            });
            cInp.insertAdjacentElement('afterend', chipsWrap);
        }
    }

    // === 2. ПРОКАЧКА ЭКРАНА КУРЬЕРА (/courier): ЗАРАБОТОК + ЯНДЕКС.КАРТЫ + ЗВОНОК ===
    function initCourierPro() {
        if (!window.location.pathname.startsWith('/courier')) return;

        let statsBar = document.getElementById('courier-pro-bar');
        if (!statsBar) {
            statsBar = document.createElement('div');
            statsBar.id = 'courier-pro-bar';
            statsBar.className = 'card-panel';
            statsBar.style.cssText = 'margin:10px auto; max-width:960px; padding:12px 16px; border-left:4px solid #ff6900 !important; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;';
            const target = document.querySelector('main, .container, body');
            target.prepend(statsBar);
        }

        function refreshCourierStats() {
            fetch('/api/courier/my_stats')
            .then(r => r.json())
            .then(d => {
                statsBar.innerHTML = `
                    <div>
                        <div style="font-size:11px; text-transform:uppercase; font-weight:800; color:#ff6900;">🛵 Моя курьерская смена (Сдельная оплата за заказы)</div>
                        <div style="font-size:13px; margin-top:3px;">
                            Доставлено сегодня: <b>${d.orders_total} зак.</b>
                            (Город: <b>${d.city_count}</b> • Дальний: <b>${d.distant_count}</b>)
                        </div>
                    </div>
                    <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
                        <span class="roll-8-badge" style="font-size:13px; padding:6px 12px; color:#16a34a; border-color:#16a34a;">
                            💰 Заработано: <b>${d.earned_today} ₽</b>
                        </span>
                        <span class="roll-8-badge" style="font-size:12px; padding:6px 10px;">
                            💵 Нал к сдаче в кассу: <b>${d.cash_collected} ₽</b>
                        </span>
                    </div>
                `;
            }).catch(() => {});

            // Добавляем кнопки Навигатора и Звонка в карточки заказов курьера
            document.querySelectorAll('.card, .order-card, .card-panel, div').forEach(card => {
                if (card.querySelector('.courier-nav-actions')) return;
                if (card.children.length < 2 || card.clientHeight < 70 || card.clientWidth > 850) return;
                const txt = card.innerText || '';
                if (!txt.match(/#\d+/)) return;

                const phoneMatch = txt.match(/(\+7|8)[\d\s\-()]{9,14}/);
                const lines = txt.split('\n').map(s => s.trim()).filter(Boolean);
                const addrLine = lines.find(l => l.includes('ул.') || l.includes('д.') || l.includes('Инта') || l.includes('Мира') || l.includes('Горького') || l.includes('Куратова') || l.includes('Кирова'));

                if (!phoneMatch && !addrLine) return;

                const actBar = document.createElement('div');
                actBar.className = 'courier-nav-actions';
                actBar.style.cssText = 'display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; padding-top:8px; border-top:1px dashed rgba(161,161,170,0.25);';

                if (phoneMatch) {
                    const cleanPhone = phoneMatch[0].replace(/[^\d+]/g, '');
                    const callLink = document.createElement('a');
                    callLink.href = 'tel:' + cleanPhone;
                    callLink.className = 'quick-chip';
                    callLink.style.cssText = 'text-decoration:none; font-weight:700; color:#16a34a; border-color:#16a34a; padding:5px 10px;';
                    callLink.innerHTML = '📞 Позвонить клиенту';
                    actBar.appendChild(callLink);
                }

                if (addrLine) {
                    const mapLink = document.createElement('a');
                    mapLink.href = 'https://yandex.ru/maps/?text=' + encodeURIComponent('Республика Коми, Инта, ' + addrLine);
                    mapLink.target = '_blank';
                    mapLink.className = 'quick-chip';
                    mapLink.style.cssText = 'text-decoration:none; font-weight:700; color:#38bdf8; border-color:#38bdf8; padding:5px 10px;';
                    mapLink.innerHTML = '🗺 Маршрут в Яндекс.Картах ↗';
                    actBar.appendChild(mapLink);
                }
                card.appendChild(actBar);
            });
        }

        refreshCourierStats();
        setInterval(refreshCourierStats, 5000);
    }

    // === 3. ЦЕНТР УПРАВЛЕНИЯ P&L + ABC-АНАЛИЗ МЕНЮ + ЦЕХ ЗАГОТОВОК ===
    window.openErpCommandModal = function(days = 7) {
        let modal = document.getElementById('erp-command-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'erp-command-modal';
            modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.72); z-index:10000; display:flex; align-items:center; justify-content:center; padding:16px;';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';
        modal.innerHTML = '<div class="card-panel" style="max-width:980px; width:100%; max-height:90vh; overflow-y:auto; padding:20px;">Загрузка P&L и ABC-аналитики...</div>';

        fetch('/api/erp/abc_pnl?days=' + days)
        .then(r => r.json())
        .then(d => {
            if (d.error) {
                modal.style.display = 'none';
                return;
            }
            const profitColor = d.net_profit >= 0 ? '#16a34a' : '#dc2626';
            let abcRows = (d.abc_items || []).map(it => {
                const badgeColor = it.group === 'A' ? '#16a34a' : (it.group === 'B' ? '#eab308' : '#dc2626');
                return `<tr>
                    <td><b>${it.name}</b> <span class="roll-8-badge" style="font-size:10px;">8 кусочков</span></td>
                    <td>${it.qty} шт.</td>
                    <td><b>${it.revenue} ₽</b> (${it.share}%)</td>
                    <td><span class="roll-8-badge" style="color:${badgeColor}; border-color:${badgeColor}; font-weight:800;">Группа ${it.group} • ${it.verdict}</span></td>
                </tr>`;
            }).join('') || '<tr><td colspan="4">Нет продаж за выбранный период</td></tr>';

            let ingOptions = (d.ingredients || []).map(ix =>
                `<option value="${ix.id}">${ix.name} (остаток: ${ix.stock} ${ix.unit || ''})</option>`
            ).join('');

            modal.innerHTML = `
            <div class="card-panel" style="max-width:980px; width:100%; max-height:90vh; overflow-y:auto; padding:22px; border:1px solid #ff6900;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px;">
                    <div>
                        <h2 style="margin:0; font-size:18px; color:#ff6900; text-transform:uppercase;">📊 Центр Управления: P&L Юнит-экономика • ABC-Матрица • Цех</h2>
                        <div style="font-size:12px; opacity:0.75;">Реальная маржинальность точки за ${d.days} дн. (заказов: ${d.orders_count})</div>
                    </div>
                    <div style="display:flex; gap:6px; align-items:center;">
                        <button type="button" class="quick-chip" onclick="openErpCommandModal(1)">Сегодня</button>
                        <button type="button" class="quick-chip" onclick="openErpCommandModal(7)">7 дней</button>
                        <button type="button" class="quick-chip" onclick="openErpCommandModal(30)">30 дней</button>
                        <button type="button" class="quick-chip" style="color:#dc2626; border-color:#dc2626;" onclick="document.getElementById('erp-command-modal').style.display='none'">✕ Закрыть</button>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:10px; margin-bottom:18px;">
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">ВЫРУЧКА ПРОДАЖ</div>
                        <div style="font-size:20px; font-weight:800; margin-top:4px;">${d.revenue} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">СЫРЬЁ (FOODCOST)</div>
                        <div style="font-size:20px; font-weight:800; color:#eab308; margin-top:4px;">${d.food_cost} ₽ <span style="font-size:12px;">(${d.food_cost_pct}%)</span></div>
                    </div>
                    <div class="card-panel" style="padding:12px;">
                        <div style="font-size:11px; opacity:0.7;">ФОТ (ПОВАРА + КУРЬЕРЫ)</div>
                        <div style="font-size:20px; font-weight:800; color:#38bdf8; margin-top:4px;">${d.total_payroll} ₽ <span style="font-size:12px;">(${d.fot_pct}%)</span></div>
                        <div style="font-size:10px; opacity:0.75;">Часы: ${d.payroll_hours} ₽ • Курьеры: ${d.payroll_courier} ₽</div>
                    </div>
                    <div class="card-panel" style="padding:12px; border-left:4px solid ${profitColor} !important;">
                        <div style="font-size:11px; opacity:0.7;">ЧИСТАЯ ПРИБЫЛЬ (NET)</div>
                        <div style="font-size:20px; font-weight:800; color:${profitColor}; margin-top:4px;">${d.net_profit} ₽ <span style="font-size:12px;">(${d.margin_pct}%)</span></div>
                    </div>
                </div>

                <div class="card-panel" style="padding:14px; margin-bottom:18px;">
                    <div style="font-size:13px; font-weight:800; color:#ff6900; margin-bottom:8px; text-transform:uppercase;">🔪 Быстрое списание по цеху (Стафф-питание / Порча / Проработка)</div>
                    <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                        <select id="wo-ing-id" style="flex:1; min-width:180px;">${ingOptions}</select>
                        <input id="wo-qty" type="number" step="0.05" placeholder="Кол-во (кг/л/шт)" style="width:140px;">
                        <select id="wo-reason" style="width:185px;">
                            <option value="Питание персонала (Стафф)">Питание персонала (Стафф)</option>
                            <option value="Порча / Срок годности">Порча / Срок годности</option>
                            <option value="Проработка меню">Проработка меню</option>
                        </select>
                        <button type="button" class="btn-ready" style="padding:7px 14px; border-radius:6px; font-weight:700; cursor:pointer;" onclick="submitQuickWriteoff()">Списать со склада</button>
                    </div>
                    <div id="wo-result-msg" style="font-size:12px; margin-top:6px;"></div>
                </div>

                <h3 style="margin:0 0 8px; font-size:14px; text-transform:uppercase;">🏆 ABC-анализ меню (Стандарт: 8 кусочков в порции ролла)</h3>
                <table>
                    <tr>
                        <th>Позиция меню</th>
                        <th>Продано</th>
                        <th>Выручка (Доля)</th>
                        <th>ABC-Рейтинг</th>
                    </tr>
                    ${abcRows}
                </table>
            </div>`;
        });
    };

    window.submitQuickWriteoff = function() {
        const ingId = document.getElementById('wo-ing-id').value;
        const qty = document.getElementById('wo-qty').value;
        const reason = document.getElementById('wo-reason').value;
        const msgBox = document.getElementById('wo-result-msg');
        fetch('/api/erp/quick_writeoff', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ingredient_id: ingId, qty: qty, reason: reason })
        })
        .then(r => r.json())
        .then(d => {
            if (d.error) {
                msgBox.style.color = '#dc2626';
                msgBox.textContent = 'Ошибка: ' + d.error;
            } else {
                msgBox.style.color = '#16a34a';
                msgBox.innerHTML = `✓ Списано: <b>${d.ing_name}</b> (${d.written_off}) на сумму <b>${d.cost_impact} ₽</b>`;
            }
        });
    };

    function injectTopbarAnalyticsButton() {
        if (window.location.pathname.startsWith('/courier') || window.location.pathname.startsWith('/kitchen') || window.location.pathname.startsWith('/site')) {
            return;
        }
        const navRight = document.querySelector('.erp-topbar-right, .topbar, header, nav');
        if (navRight && !document.getElementById('btn-open-erp-modal')) {
            const btn = document.createElement('button');
            btn.id = 'btn-open-erp-modal';
            btn.type = 'button';
            btn.className = 'quick-chip';
            btn.style.cssText = 'border-color:#ff6900; color:#ff6900; font-weight:800; cursor:pointer;';
            btn.innerHTML = '📊 P&L • ABC • Цех';
            btn.onclick = function() { window.openErpCommandModal(7); };
            navRight.prepend(btn);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        initCashierCRM();
        initCourierPro();
        setTimeout(injectTopbarAnalyticsButton, 400);
    });
})();
