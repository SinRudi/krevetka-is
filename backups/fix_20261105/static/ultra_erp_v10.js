(function() {
    let lastAnnouncedOrderId = null;
    let voiceEnabled = localStorage.getItem('kds_voice_tts') !== '0';

    function speakRussianKDS(text) {
        if (!voiceEnabled || !('speechSynthesis' in window)) return;
        try {
            window.speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(text);
            u.lang = 'ru-RU';
            u.rate = 1.05;
            u.pitch = 1.0;
            window.speechSynthesis.speak(u);
        } catch (e) {}
    }

    // === 1. KDS АГРЕГАТОР ПАРТИЙ («ALL-DAY СВОДКА ЦЕХА») + ГОЛОСОВОЙ ДИКТОР НА /kitchen ===
    function initKitchenBatchAggregator() {
        if (!window.location.pathname.startsWith('/kitchen')) return;

        let bar = document.getElementById('kds-allday-batch-bar');
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'kds-allday-batch-bar';
            bar.className = 'card-panel';
            bar.style.cssText = 'margin:10px 14px; padding:12px 16px; border-left:4px solid #ff6900 !important;';
            const container = document.querySelector('main, .kds-container, body');
            container.prepend(bar);
        }

        function pollBatchData() {
            fetch('/api/ultra/kds_batch')
            .then(r => r.json())
            .then(d => {
                if (d.newest_order && d.newest_order.id) {
                    if (lastAnnouncedOrderId !== null && d.newest_order.id > lastAnnouncedOrderId) {
                        speakRussianKDS(
                            `Внимание, цех! Новый заказ номер ${d.newest_order.id}. ${d.newest_order.items_summary}`
                        );
                    }
                    lastAnnouncedOrderId = d.newest_order.id;
                } else if (lastAnnouncedOrderId === null) {
                    lastAnnouncedOrderId = 0;
                }

                const chipsHtml = (d.batches || []).map(b => {
                    const isMulti = b.qty >= 2;
                    const borderCol = isMulti ? '#ff6900' : 'rgba(161,161,170,0.35)';
                    return `<span class="roll-8-badge" style="padding:5px 10px; font-size:12px; border-color:${borderCol};">
                        <b>${b.name}</b> <span style="opacity:0.75;">(8 шт.)</span>:
                        <b style="color:${isMulti ? '#ff6900' : '#16a34a'}; font-size:14px; margin-left:4px;">× ${b.qty} порц.</b>
                    </span>`;
                }).join(' ') || '<span style="opacity:0.7; font-size:12px;">Нет активных позиций в очереди — стол чист</span>';

                bar.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
                        <div style="font-size:12px; font-weight:800; text-transform:uppercase; color:#ff6900;">
                            🍣 СВОДКА ЦЕХА (ALL-DAY БАТЧИ НА СКРУТКУ) • Активных чеков: ${d.active_orders_count} • Всего порций: ${d.total_portions}
                        </div>
                        <button type="button" class="quick-chip" id="kds-tts-toggle" style="font-size:11px; cursor:pointer; border-color:${voiceEnabled ? '#16a34a' : '#71717a'}; color:${voiceEnabled ? '#16a34a' : '#a1a1aa'};">
                            ${voiceEnabled ? '🔊 Голосовой диктор: ВКЛ' : '🔇 Голосовой диктор: ВЫКЛ'}
                        </button>
                    </div>
                    <div style="display:flex; flex-wrap:wrap; gap:6px;">${chipsHtml}</div>
                `;

                const tBtn = document.getElementById('kds-tts-toggle');
                if (tBtn) {
                    tBtn.onclick = function() {
                        voiceEnabled = !voiceEnabled;
                        localStorage.setItem('kds_voice_tts', voiceEnabled ? '1' : '0');
                        if (voiceEnabled) {
                            speakRussianKDS('Голосовой диктор кухни включен');
                        }
                        pollBatchData();
                    };
                }
            }).catch(() => {});
        }

        pollBatchData();
        setInterval(pollBatchData, 4000);
    }

    // === 2. SLA-РАДАР ДОСТАВКИ И ГОРЯЧИЕ КЛАВИШИ КАССИРА НА КАССЕ (/) ===
    function initCashierRadarAndHotkeys() {
        const isPosPage = (window.location.pathname === '/' || window.location.pathname === '/index');
        if (!isPosPage) return;

        // Горячие клавиши F2 (Поиск по телефону), F4 (Без сдачи), F9 (Z-Отчёт)
        document.addEventListener('keydown', function(e) {
            if (e.key === 'F2') {
                e.preventDefault();
                const pInp = document.querySelector('input[placeholder*="Телефон"], input[name="phone"], #phone');
                if (pInp) {
                    pInp.focus();
                    pInp.select();
                }
            } else if (e.key === 'F9') {
                e.preventDefault();
                window.openUltraCenterModal('zreport');
            }
        });

        // Плашка SLA-времени доставки по районам Инты
        const addrInp = document.querySelector('input[placeholder*="Адрес"], input[name="address"], #address');
        if (addrInp && !document.getElementById('pos-sla-radar')) {
            const radar = document.createElement('div');
            radar.id = 'pos-sla-radar';
            radar.style.cssText = 'margin-top:4px; margin-bottom:6px; font-size:11px; padding:5px 8px; border-radius:6px; background:rgba(22,163,74,0.08); border:1px solid rgba(22,163,74,0.3); display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px;';
            addrInp.insertAdjacentElement('afterend', radar);

            function updateSlaRadar() {
                fetch('/api/ultra/kds_batch')
                .then(r => r.json())
                .then(d => {
                    const s = d.sla || { city_min: 30, west_south_min: 40, upper_inta_min: 50 };
                    radar.innerHTML = `
                        <span>⏱ <b>Обещанное время (очередь KDS: ${d.active_orders_count}):</b></span>
                        <span>Город: <b style="color:#16a34a;">~${s.city_min} мин</b> • Южный/Запад: <b style="color:#eab308;">~${s.west_south_min} мин</b> • Верхняя: <b style="color:#ff6900;">~${s.upper_inta_min} мин</b></span>
                    `;
                }).catch(() => {});
            }
            updateSlaRadar();
            setInterval(updateSlaRadar, 10000);
        }
    }

    // === 3. МОДАЛЬНЫЙ ЦЕНТР ULTRA v10: Z-ОТЧЁТ СВЕРКИ + КОНСТРУКТОР ТЕХКАРТ + АВТО-ЗАКУП ===
    window.openUltraCenterModal = function(tab = 'zreport') {
        let modal = document.getElementById('ultra-v10-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'ultra-v10-modal';
            modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.76); z-index:10001; display:flex; align-items:center; justify-content:center; padding:14px;';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';
        modal.innerHTML = '<div class="card-panel" style="max-width:1020px; width:100%; padding:22px;">Загрузка модуля ULTRA v10...</div>';

        if (tab === 'zreport') {
            fetch('/api/ultra/zreport_and_prep')
            .then(r => r.json())
            .then(d => {
                if (d.error) { modal.style.display = 'none'; return; }
                const procRows = (d.procurement || []).map(p => `
                    <tr>
                        <td><b>${p.name}</b></td>
                        <td style="color:#dc2626; font-weight:700;">${p.stock} ${p.unit}</td>
                        <td>${p.min_stock} ${p.unit}</td>
                        <td><b style="color:#16a34a;">+${p.order_qty} ${p.unit}</b></td>
                        <td>~${p.est_cost} ₽</td>
                    </tr>
                `).join('') || '<tr><td colspan="5" style="color:#16a34a;">✓ Все позиции сырья выше минимального порога</td></tr>';

                const waText = (d.procurement || []).map(p => `• ${p.name}: ${p.order_qty} ${p.unit}`).join('\n');

                modal.innerHTML = `
                <div class="card-panel" style="max-width:1020px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #38bdf8;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:16px;">
                        <div>
                            <h2 style="margin:0; font-size:18px; color:#38bdf8; text-transform:uppercase;">⚡ ULTRA ЦЕНТР: Z-ОТЧЁТ КАССЫ • ТЕХКАРТЫ (8 ШТ.) • АВТО-ЗАКУП</h2>
                            <div style="font-size:12px; opacity:0.75;">Дата смены: ${d.date} • Горячая клавиша вызова: F9</div>
                        </div>
                        <div style="display:flex; gap:6px; flex-wrap:wrap;">
                            <button type="button" class="quick-chip" style="border-color:#38bdf8; color:#38bdf8; font-weight:800;" onclick="openUltraCenterModal('zreport')">🧾 Z-Отчёт & Закуп</button>
                            <button type="button" class="quick-chip" style="border-color:#ff6900; color:#ff6900; font-weight:800;" onclick="openUltraCenterModal('recipes')">🍣 Конструктор Техкарт</button>
                            <button type="button" class="quick-chip" onclick="printThermalZReport()">🖨 Печать Z-чека</button>
                            <button type="button" class="quick-chip" style="color:#dc2626; border-color:#dc2626;" onclick="document.getElementById('ultra-v10-modal').style.display='none'">✕ Закрыть</button>
                        </div>
                    </div>

                    <div id="printable-z-report" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:10px; margin-bottom:18px;">
                        <div class="card-panel" style="padding:12px;">
                            <div style="font-size:11px; opacity:0.7;">ВЫРУЧКА ЗА СЕГОДНЯ (${d.orders_count} зак.)</div>
                            <div style="font-size:21px; font-weight:800; margin-top:4px;">${d.total_revenue} ₽</div>
                            <div style="font-size:11px; opacity:0.8; margin-top:3px;">Средний чек: <b>${d.avg_check} ₽</b> (Отмен: ${d.cancelled_count})</div>
                        </div>
                        <div class="card-panel" style="padding:12px;">
                            <div style="font-size:11px; opacity:0.7;">НАЛИЧНЫЕ vs КАРТА / СБП</div>
                            <div style="font-size:15px; font-weight:800; color:#16a34a; margin-top:4px;">💵 Нал: ${d.cash_revenue} ₽</div>
                            <div style="font-size:15px; font-weight:800; color:#38bdf8; margin-top:2px;">💳 Безнал: ${d.card_revenue} ₽</div>
                        </div>
                        <div class="card-panel" style="padding:12px;">
                            <div style="font-size:11px; opacity:0.7;">ФОТ СМЕНЫ (КУРЬЕРЫ И ЦЕХ)</div>
                            <div style="font-size:15px; font-weight:800; color:#ff6900; margin-top:4px;">🛵 Курьерам (сдельно): ${d.courier_payroll} ₽</div>
                            <div style="font-size:13px; margin-top:2px;">👨‍🍳 Часы (повар/касса): <b>${d.hourly_payroll} ₽</b></div>
                        </div>
                        <div class="card-panel" style="padding:12px; border-left:4px solid #16a34a !important;">
                            <div style="font-size:11px; opacity:0.7;">ОЖИДАЕМЫЙ НАЛ В ЯЩИКЕ КАССЫ</div>
                            <div style="font-size:21px; font-weight:800; color:#16a34a; margin-top:4px;">${d.expected_drawer_cash} ₽</div>
                            <div style="font-size:11px; opacity:0.8; margin-top:3px;">Чистая прибыль дня: <b>${d.day_net_profit} ₽</b></div>
                        </div>
                    </div>

                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
                        <h3 style="margin:0; font-size:14px; text-transform:uppercase; color:#eab308;">📦 Авто-Закуп сырья поставщику (позиции ниже норматива)</h3>
                        <button type="button" class="quick-chip" style="border-color:#16a34a; color:#16a34a;" onclick="navigator.clipboard.writeText(\`Заявка на закуп Креветка IS (${d.date}):\\n${waText}\`); this.textContent='✓ Скопировано для WhatsApp!';">📋 Скопировать заявку поставщику</button>
                    </div>
                    <table>
                        <tr>
                            <th>Ингредиент</th>
                            <th>Текущий остаток</th>
                            <th>Мин. норма</th>
                            <th>Рекомендуемый закуп</th>
                            <th>Ориентир суммы</th>
                        </tr>
                        ${procRows}
                    </table>
                </div>`;
            });
        } else {
            fetch('/api/ultra/recipes_matrix')
            .then(r => r.json())
            .then(d => {
                if (d.error) { modal.style.display = 'none'; return; }
                const menuOpts = (d.menu_items || []).map(m =>
                    `<option value="${m.id}">${m.name} (Цена: ${m.price} ₽ • Себест: ${m.cost} ₽)</option>`
                ).join('');
                const ingOpts = (d.ingredients || []).map(i =>
                    `<option value="${i.id}">${i.name} (${i.cost_price} ₽ / ${i.unit || 'кг'})</option>`
                ).join('');

                const rowsHtml = (d.menu_items || []).map(m => {
                    const fcColor = m.fc_pct > 35 ? '#dc2626' : (m.fc_pct > 0 ? '#16a34a' : '#eab308');
                    const compText = (m.recipe || []).map(rc => `${rc.ing_name}: ${rc.amount}${rc.unit}`).join(', ') || 'Техкарта пуста';
                    return `<tr>
                        <td><b>${m.name}</b> <span class="roll-8-badge" style="font-size:10px;">8 шт.</span></td>
                        <td>${m.price} ₽</td>
                        <td><b>${m.cost} ₽</b> <span style="color:${fcColor}; font-weight:700;">(${m.fc_pct}%)</span></td>
                        <td style="font-size:11px; opacity:0.85;">${compText}</td>
                        <td><span class="roll-8-badge">${m.recommended_price} ₽</span></td>
                    </tr>`;
                }).join('');

                modal.innerHTML = `
                <div class="card-panel" style="max-width:1020px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #ff6900;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:14px;">
                        <div>
                            <h2 style="margin:0; font-size:18px; color:#ff6900; text-transform:uppercase;">🍣 Живой Конструктор Техкарт и Контроль Наценки (Стандарт: 8 кусочков)</h2>
                            <div style="font-size:12px; opacity:0.75;">Точный расчёт себестоимости каждого ролла по закладке сырья в граммах/кг</div>
                        </div>
                        <div style="display:flex; gap:6px;">
                            <button type="button" class="quick-chip" onclick="openUltraCenterModal('zreport')">← Назад к Z-Отчёту</button>
                            <button type="button" class="quick-chip" style="border-color:#16a34a; color:#16a34a;" onclick="enforce8PiecesStandard()">✓ Проверить стандарт 8 шт.</button>
                            <button type="button" class="quick-chip" style="color:#dc2626; border-color:#dc2626;" onclick="document.getElementById('ultra-v10-modal').style.display='none'">✕ Закрыть</button>
                        </div>
                    </div>

                    <div class="card-panel" style="padding:14px; margin-bottom:16px;">
                        <div style="font-size:12px; font-weight:800; color:#38bdf8; margin-bottom:8px; text-transform:uppercase;">➕ Добавить или обновить закладку сырья в техкарте (0 = удалить)</div>
                        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                            <select id="tc-menu-id" style="flex:1; min-width:210px;">${menuOpts}</select>
                            <select id="tc-ing-id" style="flex:1; min-width:190px;">${ingOpts}</select>
                            <input id="tc-amount" type="number" step="0.005" placeholder="Норма (напр. 0.120 кг)" style="width:165px;">
                            <button type="button" class="btn-ready" style="padding:7px 14px; border-radius:6px; font-weight:700; cursor:pointer;" onclick="saveTechCardRow()">Сохранить граммовку</button>
                        </div>
                    </div>

                    <table>
                        <tr>
                            <th>Блюдо меню</th>
                            <th>Цена витрины</th>
                            <th>Себестоимость (Foodcost)</th>
                            <th>Состав техкарты</th>
                            <th>Реком. цена (FC 28%)</th>
                        </tr>
                        ${rowsHtml}
                    </table>
                </div>`;
            });
        }
    };

    window.saveTechCardRow = function() {
        const menuId = document.getElementById('tc-menu-id').value;
        const ingId = document.getElementById('tc-ing-id').value;
        const amount = document.getElementById('tc-amount').value;
        fetch('/api/ultra/recipe_save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ menu_id: menuId, ingredient_id: ingId, amount: amount })
        })
        .then(r => r.json())
        .then(() => window.openUltraCenterModal('recipes'));
    };

    window.enforce8PiecesStandard = function() {
        fetch('/api/ultra/standardize_8pcs', { method: 'POST' })
        .then(r => r.json())
        .then(() => window.openUltraCenterModal('recipes'));
    };

    window.printThermalZReport = function() {
        const zBlock = document.getElementById('printable-z-report');
        if (!zBlock) return;
        const w = window.open('', '_blank', 'width=380,height=600');
        w.document.write(`
            <html><head><title>Z-Отчёт КРЕВЕТКА IS</title>
            <style>body{font-family:monospace;width:280px;margin:10px auto;font-size:12px;} div{margin-bottom:6px;}</style>
            </head><body>
            <h3>=== КРЕВЕТКА IS • Z-ОТЧЁТ ===</h3>
            ${zBlock.innerText.replace(/\n+/g, '<br>')}
            <hr><p>Подпись кассира: _____________</p>
            </body></html>
        `);
        w.document.close();
        w.focus();
        w.print();
        w.close();
    };

    function injectUltraButton() {
        if (window.location.pathname.startsWith('/courier') || window.location.pathname.startsWith('/kitchen') || window.location.pathname.startsWith('/site')) {
            return;
        }
        const navRight = document.querySelector('.erp-topbar-right, .topbar, header, nav');
        if (navRight && !document.getElementById('btn-open-ultra-v10')) {
            const btn = document.createElement('button');
            btn.id = 'btn-open-ultra-v10';
            btn.type = 'button';
            btn.className = 'quick-chip';
            btn.style.cssText = 'border-color:#38bdf8; color:#38bdf8; font-weight:800; cursor:pointer;';
            btn.innerHTML = '⚡ Z-Отчёт • Техкарты';
            btn.onclick = function() { window.openUltraCenterModal('zreport'); };
            navRight.prepend(btn);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        initKitchenBatchAggregator();
        initCashierRadarAndHotkeys();
        setTimeout(injectUltraButton, 450);
    });
})();
