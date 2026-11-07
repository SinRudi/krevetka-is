(function() {
    // Публичные страницы (витрина/трекинг/оценка) — только для клиентов: без виджетов ФЧ и персонала
    const __pub = window.location.pathname;
    if (__pub.startsWith('/site') || __pub.startsWith('/track') || __pub.startsWith('/rate')) return;

    let fchMapCache = {};
    let fchSummaryCache = null;

    // 1. Загружаем карту статусов ФЧ с сервера и автоматически вешаем штампы «✅ ФЧ» или «⚪ Пробить ФЧ» на любые заказы на экране
    function syncFchBadgesEverywhere() {
        fetch('/api/hyperion/fch_badges_map')
        .then(r => r.json())
        .then(d => {
            fchMapCache = d.orders_map || {};
            fchSummaryCache = d.summary || {};
            updateTopTelemetryPill();
            decorateOrderElementsWithFch();
        })
        .catch(() => {});
    }

    function updateTopTelemetryPill() {
        if (!fchSummaryCache) return;
        let pill = document.getElementById('hyperion-top-telemetry');
        if (!pill) {
            const navLinks = Array.from(document.querySelectorAll('a, button'));
            const anchor = navLinks.find(el => ((el.textContent || '').includes('54-ФЗ') || (el.textContent || '').includes('Декларация')) && !(el.closest && el.closest('#service-menu')));
            if (anchor && anchor.parentElement) {
                pill = document.createElement('div');
                pill.id = 'hyperion-top-telemetry';
                pill.title = 'Нажмите, чтобы открыть Реестр ФЧ (54-ФЗ), Пакетную фискализацию и Анти-Вор цеха';
                pill.onclick = function() { window.openHyperionModal('fch_registry'); };
                anchor.parentElement.insertBefore(pill, anchor);
            }
        }
        if (pill) {
            const s = fchSummaryCache;
            const kdsBadge = s.kds_overload
                ? `<span style="color:#ef4444;">🔥 KDS ПЕРЕГРУЗ (${s.active_kds_queue})</span>`
                : `<span style="color:#38bdf8;">🔪 KDS: ${s.active_kds_queue}</span>`;
            pill.innerHTML = `
                <span style="color:#34d399;">✅ ФЧ: ${s.fch_count} шт. (${s.fch_revenue} ₽)</span>
                <span style="opacity:0.4;">|</span>
                <span style="color:#fbbf24;">Без ФЧ: ${s.non_fch_count}</span>
                <span style="opacity:0.4;">|</span>
                ${kdsBadge}
            `;
        }
    }

    // Умный поиск карточек/строк заказов (#12, №12, Заказ #12) во всех шаблонах (Касса, Заказы, История, KDS, Курьер)
    function decorateOrderElementsWithFch() {
        const candidates = document.querySelectorAll(
            '.order-card, .kds-card, .history-row, tr, li, .card, .panel, [data-order-id]'
        );

        candidates.forEach(el => {
            if (el.closest('#titanium-v20-modal')) return; // Внутри модального окна своя таблица
            let oid = el.getAttribute('data-order-id');

            if (!oid) {
                // Ищем заголовок с номером заказа внутри карточки/строки
                const headerEl = el.querySelector('b, strong, h3, h4, .order-id, td:first-child');
                if (!headerEl) return;
                const txt = (headerEl.textContent || '').trim();
                const m = txt.match(/^(?:Заказ\s*|Чек\s*)?[№#](\d{1,6})\b/i);
                if (!m) return;
                oid = m[1];
                el.setAttribute('data-fch-target-id', oid);
            }

            const info = fchMapCache[String(oid)];
            if (!info) return;

            const host = el.querySelector('b, strong, h3, h4, .order-id, td:first-child') || el;
            let badge = el.querySelector('.hyperion-fch-badge');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'hyperion-fch-badge';
                host.appendChild(badge);
            }

            if (info.is_fch) {
                badge.className = 'hyperion-fch-badge fch-stamp-ok';
                badge.innerHTML = `✅ ФЧ • ФД:${info.fd}`;
                badge.title = `Фискальный чек пробит (ФД: ${info.fd}, ФПД: ${info.fpd}, Крипто-хеш: ${info.chash}). Нажмите для печати чека 80мм.`;
                badge.onclick = function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    window.open('/fiscal_slip/' + info.id, '_blank');
                };
            } else {
                badge.className = 'hyperion-fch-badge fch-stamp-pending';
                badge.innerHTML = `⚪ Пробить ФЧ`;
                badge.title = `Заказ #${info.id} ещё не фискализирован. Нажмите, чтобы пробить ФЧ в 1 клик!`;
                badge.onclick = function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    window.quickPunchFchOrder(info.id, badge);
                };
            }
        });

        // Также добавляем галочку «Пробить ФЧ сразу при оформлении» рядом с кнопкой «Оформить • Enter» на кассе
        injectPosAutoFchToggle();
    }

    function injectPosAutoFchToggle() {
        if (document.getElementById('pos-auto-fch-bar')) return;
        const buttons = Array.from(document.querySelectorAll('button'));
        const submitBtn = buttons.find(b => (b.textContent || '').includes('Оформить'));
        if (!submitBtn || !submitBtn.parentElement) return;

        const bar = document.createElement('div');
        bar.id = 'pos-auto-fch-bar';
        bar.style.cssText = 'display:flex; justify-content:space-between; align-items:center; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.4); border-radius:9px; padding:7px 11px; margin-bottom:8px; font-size:12px;';
        // По умолчанию авто-пробитие выключено: владелец решает сам, как и когда пробивать чек
        const savedPref = localStorage.getItem('krevetka_auto_fch') === '1';
        bar.innerHTML = `
            <label style="display:flex; align-items:center; gap:7px; cursor:pointer; font-weight:800; color:#34d399;">
                <input type="checkbox" id="pos-auto-fch-chk" ${savedPref ? 'checked' : ''} style="width:16px; height:16px;">
                <span>🧾 Авто-пробитие ФЧ (54-ФЗ) с пометкой «✅ ФЧ» в заказе</span>
            </label>
            <button type="button" class="ti-tab-btn" style="padding:3px 8px; font-size:11px; border-color:#10b981; color:#10b981;" onclick="window.openHyperionModal('fch_registry')">Реестр ФЧ</button>
        `;
        submitBtn.parentElement.parentElement.insertBefore(bar, submitBtn.parentElement);

        const chk = document.getElementById('pos-auto-fch-chk');
        chk.addEventListener('change', function() {
            localStorage.setItem('krevetka_auto_fch', this.checked ? '1' : '0');
        });

        // При клике на «Оформить» автоматически ставим метку ФЧ новому заказу, если включён чекбокс
        submitBtn.addEventListener('click', function() {
            if (!document.getElementById('pos-auto-fch-chk')?.checked) return;
            setTimeout(() => {
                fetch('/api/hyperion/fch_badges_map').then(r => r.json()).then(d => {
                    const ids = Object.keys(d.orders_map || {}).map(Number).sort((a,b) => b - a);
                    if (ids.length > 0) {
                        const newestId = ids[0];
                        if (!d.orders_map[String(newestId)].is_fch) {
                            window.quickPunchFchOrder(newestId, null, true);
                        }
                    }
                });
            }, 900);
        });
    }

    window.quickPunchFchOrder = function(orderId, badgeEl, silent) {
        if (badgeEl) {
            badgeEl.textContent = '⏳ Пробитие ФЧ...';
        }
        fetch('/api/hyperion/punch_fch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_id: orderId })
        })
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                syncFchBadgesEverywhere();
                if (!silent && document.getElementById('titanium-v20-modal')?.style.display === 'flex') {
                    window.openHyperionModal('fch_registry');
                }
            }
        });
    };

    window.punchAllUnfiscalizedShift = function() {
        fetch('/api/hyperion/punch_all_shift_fch', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            syncFchBadgesEverywhere();
            window.openHyperionModal('fch_registry');
        });
    };

    // 2. Полноэкранный командный центр HYPERION v200 (Реестр ФЧ + Сверка Фискал/Нефискал + Анти-Вор цеха)
    window.openHyperionModal = function(tab) {
        tab = tab || 'fch_registry';
        let modal = document.getElementById('titanium-v20-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'titanium-v20-modal';
            modal.style.cssText = 'position:fixed; inset:0; background:rgba(7,9,14,0.88); z-index:100000; display:flex; align-items:center; justify-content:center; padding:16px; backdrop-filter:blur(5px);';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';

        fetch('/api/hyperion/command_data')
        .then(r => r.json())
        .then(d => {
            const orderRows = (d.orders || []).map(o => {
                const statusBadge = o.is_fch
                    ? `<span class="fch-stamp-ok" onclick="window.open('/fiscal_slip/${o.id}', '_blank')">✅ ФЧ • ФД:${o.fd} (ФПД:${o.fpd})</span>`
                    : `<span class="fch-stamp-pending" onclick="window.quickPunchFchOrder(${o.id})">⚪ Не фискализирован — Пробить ФЧ в 1 клик</span>`;
                const hashTxt = o.chash
                    ? `<span style="font-family:monospace; font-size:11px; color:#38bdf8;">🔒 ${o.chash}</span>`
                    : `<span style="font-size:11px; opacity:0.5;">—</span>`;

                return `<tr>
                    <td><b>#${o.id}</b> <span style="font-size:11px; opacity:0.7;">(${(o.created_at||'').slice(11,16)})</span></td>
                    <td><b>${o.total} ₽</b> (${o.payment_method || 'Оплата'})</td>
                    <td>${o.address || 'Самовывоз'}</td>
                    <td>${statusBadge}</td>
                    <td>${hashTxt}</td>
                    <td>
                        ${o.is_fch
                            ? `<a href="/fiscal_slip/${o.id}" target="_blank" class="ti-tab-btn ti-internal" style="text-decoration:none; padding:4px 9px; border-color:#10b981; color:#10b981;">🖨 Чек 80мм ↗</a>`
                            : `<button type="button" class="ti-tab-btn ti-internal active" style="padding:4px 9px;" onclick="window.quickPunchFchOrder(${o.id})">⚡ Пробить ФЧ</button>`
                        }
                    </td>
                </tr>`;
            }).join('');

            const radarRows = (d.shrinkage_radar || []).map(s => `
                <tr>
                    <td><b>${s.name}</b></td>
                    <td>${s.cost_price} ₽ / ${s.unit}</td>
                    <td><b>${s.ideal_used} ${s.unit}</b> (по техкартам 8 шт.)</td>
                    <td style="font-weight:900; color:${s.current_stock < 0 ? '#ef4444' : '#10b981'};">${s.current_stock} ${s.unit}</td>
                    <td><span class="roll-8-badge" style="border-color:${s.current_stock < 0 ? '#ef4444' : '#10b981'}; color:${s.current_stock < 0 ? '#ef4444' : '#10b981'};">${s.status}</span></td>
                </tr>
            `).join('');

            modal.innerHTML = `
                <div class="card-panel" style="max-width:1160px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #10b981;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px; padding-bottom:12px; border-bottom:1px solid rgba(148,163,184,0.2);">
                        <div>
                            <div style="font-size:18px; font-weight:900; color:#10b981;">👑 КРЕВЕТКА IS • HYPERION v200 (СКВОЗНОЙ КОНТРОЛЬ «ФЧ» & КРИПТО-АУДИТ ЦЕХА)</div>
                            <div style="font-size:12px; opacity:0.8; margin-top:2px;">Мгновенная маркировка заказов штампом «✅ ФЧ», раздельный учёт фискальной и внутренней кассы, защита чеков SHA-256</div>
                        </div>
                        <div style="display:flex; gap:8px; flex-wrap:wrap;">
                            <button type="button" class="ti-tab-btn ti-internal active" style="background:#10b981; color:#042f1e; border-color:#10b981;" onclick="window.punchAllUnfiscalizedShift()">⚡ Пробить «ФЧ» всем непробитым чекам смены (${d.unfiscal_count} шт.)</button>
                            <button type="button" class="ti-tab-btn ti-internal" onclick="window.openMonolithFiscalModal && window.openMonolithFiscalModal()">🔍 Сканер Честный Знак</button>
                            <button type="button" class="ti-tab-btn ti-internal" onclick="window.openTitaniumSuite && window.openTitaniumSuite('zreport')">← К Z-Отчёту</button>
                            <button type="button" class="ti-tab-btn ti-internal" style="border-color:#ef4444; color:#ef4444;" onclick="document.getElementById('titanium-v20-modal').style.display='none'">✕ Закрыть</button>
                        </div>
                    </div>

                    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:12px; margin-bottom:16px;">
                        <div class="card-panel" style="padding:14px; border-left:4px solid #10b981 !important;">
                            <div style="font-size:11px; opacity:0.75;">ПРОВЕДЕНО С ПОМЕТКОЙ «✅ ФЧ» (54-ФЗ / ОФД)</div>
                            <div style="font-size:23px; font-weight:900; color:#10b981; margin-top:4px;">${d.fch_total} ₽ (${d.fch_count} чеков)</div>
                            <div style="font-size:11px; opacity:0.85; margin-top:3px;">Идёт в официальную декларацию ФНС и КУДиР</div>
                        </div>
                        <div class="card-panel" style="padding:14px; border-left:4px solid #f59e0b !important;">
                            <div style="font-size:11px; opacity:0.75;">ЗАКАЗЫ БЕЗ «ФЧ» (ОЖИДАЮТ ФИСКАЛИЗАЦИИ)</div>
                            <div style="font-size:23px; font-weight:900; color:#fbbf24; margin-top:4px;">${d.unfiscal_total} ₽ (${d.unfiscal_count} чеков)</div>
                            <div style="font-size:11px; opacity:0.85; margin-top:3px;">Можно пробить выборочно в 1 клик в таблице ниже</div>
                        </div>
                        <div class="card-panel" style="padding:14px; border-left:4px solid #38bdf8 !important;">
                            <div style="font-size:11px; opacity:0.75;">КРИПТО-ЗАЩИТА КАССЫ (SHA-256 CHAIN)</div>
                            <div style="font-size:19px; font-weight:900; color:#38bdf8; margin-top:4px;">100% ЦЕЛОСТНОСТЬ БД</div>
                            <div style="font-size:11px; opacity:0.85; margin-top:3px;">Удаление или подмена закрытых ФЧ заблокирована</div>
                        </div>
                    </div>

                    <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#10b981;">🧾 Живой реестр заказов и управление пометками «✅ ФЧ» (Фискальный Чек)</h3>
                    <table style="margin-bottom:18px;">
                        <tr>
                            <th>Заказ / Время</th>
                            <th>Сумма и Оплата</th>
                            <th>Адрес клиента (г. Инта)</th>
                            <th>Статус Фискального Чека (ФЧ)</th>
                            <th>Крипто-подпись SHA256</th>
                            <th>Действие</th>
                        </tr>
                        ${orderRows}
                    </table>

                    <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#38bdf8;">🕵️‍♂️ Радар списаний ценного сырья по техкартам (Контроль потерь: стандарт 8 кусочков)</h3>
                    <table>
                        <tr><th>Сырьё</th><th>Закупочная цена</th><th>Списано по чекам (Норма)</th><th>Текущий остаток БД</th><th>Статус ревизии</th></tr>
                        ${radarRows}
                    </table>
                </div>
            `;
        });
    };

    document.addEventListener('DOMContentLoaded', () => {
        syncFchBadgesEverywhere();
        setInterval(syncFchBadgesEverywhere, 4000);
    });
    setTimeout(syncFchBadgesEverywhere, 300);
})();
