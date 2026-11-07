(function() {
    // 1. МГНОВЕННЫЙ ЖИВОЙ ПОИСК БЛЮД И ПЕРЕКЛЮЧАТЕЛЬ КОНЦЕПЦИЙ НА КАССЕ
    function initInstantMenuFilter() {
        const isPos = (window.location.pathname === '/' || window.location.pathname === '/index');
        if (!isPos) return;
        if (document.getElementById('pos-instant-search-bar')) return;

        const headings = Array.from(document.querySelectorAll('h2, h3, .section-title'));
        const menuHeading = headings.find(h => (h.textContent || '').toLowerCase().includes('меню') || (h.textContent || '').toLowerCase().includes('витрина'));
        const targetContainer = menuHeading ? menuHeading.parentElement : document.querySelector('main, .container, body');
        if (!targetContainer) return;

        const searchBar = document.createElement('div');
        searchBar.id = 'pos-instant-search-bar';
        searchBar.innerHTML = `
            <span style="font-weight:900; color:#ff6900; font-size:12px; white-space:nowrap;">⚡ УМНЫЙ ПОИСК (F3):</span>
            <input type="text" id="pos-fast-filter-inp" placeholder="Введите название ролла (8 шт.) или бургера..." style="flex:1; min-width:180px;">
            <button type="button" class="quick-chip" onclick="window.filterPosMenu('')" style="border-color:#38bdf8;color:#38bdf8;">Все</button>
            <button type="button" class="quick-chip" onclick="window.filterPosMenu('филадельфия')" style="border-color:#ff6900;color:#ff6900;">🍣 Хиты Роллов (8 шт.)</button>
            <button type="button" class="quick-chip" onclick="window.filterPosMenu('бургер')" style="border-color:#eab308;color:#eab308;">🍔 Бургеры</button>
        `;
        targetContainer.prepend(searchBar);

        const inp = document.getElementById('pos-fast-filter-inp');
        inp.addEventListener('input', function() {
            window.filterPosMenu(this.value);
        });

        document.addEventListener('keydown', function(e) {
            if (e.key === 'F3') {
                e.preventDefault();
                inp.focus();
                inp.select();
            }
        });
    }

    window.filterPosMenu = function(query) {
        const inp = document.getElementById('pos-fast-filter-inp');
        if (inp && inp.value !== query) inp.value = query;
        const q = (query || '').trim().toLowerCase();

        document.querySelectorAll('.menu-item, .pos-card, [onclick*="addToCart"], [onclick*="add_to_cart"]').forEach(card => {
            const txt = (card.innerText || '').toLowerCase();
            if (!q || txt.includes(q)) {
                card.style.display = '';
            } else {
                card.style.display = 'none';
            }
        });
    };

    // 2. МОДАЛЬНОЕ ОКНО «ШТАБ ФРАНШИЗЫ И СЕТИ КРЕВЕТКА IS»
    window.openFranchiseHqModal = function() {
        let modal = document.getElementById('franchise-hq-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'franchise-hq-modal';
            modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:100005; display:flex; align-items:center; justify-content:center; padding:16px; backdrop-filter:blur(5px);';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';
        modal.innerHTML = '<div class="card-panel" style="max-width:1060px; width:100%; padding:26px; text-align:center;">👑 Загрузка Штаба Франшизы...</div>';

        fetch('/api/franchise/overview?days=30')
        .then(r => r.json())
        .then(d => {
            const branchRows = (d.branches || []).map(b => `
                <tr>
                    <td><span class="roll-8-badge" style="border-color:${b.is_flagship?'#ff6900':'#38bdf8'}; color:${b.is_flagship?'#ff6900':'#38bdf8'}; font-weight:800;">${b.code}</span></td>
                    <td><b>${b.name}</b><div style="font-size:11px; opacity:0.7;">${b.city}</div></td>
                    <td>${b.concept}</td>
                    <td><b>${b.orders}</b> чеков</td>
                    <td><b style="color:#10b981;">${b.revenue} ₽</b></td>
                    <td><b>${b.royalty_due} ₽</b> <span style="font-size:11px; opacity:0.75;">(${b.status})</span></td>
                    <td>⏱ до ${b.sla_target} мин</td>
                </tr>
            `).join('');

            modal.innerHTML = `
            <div class="card-panel" style="max-width:1080px; width:100%; max-height:92vh; overflow-y:auto; padding:24px; border:1px solid #ff6900 !important;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:18px; padding-bottom:12px; border-bottom:1px solid rgba(148,163,184,0.2);">
                    <div>
                        <h2 style="margin:0; font-size:20px; color:#ff6900; text-transform:uppercase;">👑 КРЕВЕТКА IS • ШТАБ УПРАВЛЕНИЯ ФРАНШИЗОЙ И СЕТЬЮ</h2>
                        <div style="font-size:12px; opacity:0.8; margin-top:3px;">Единое облачное ядро: Контроль стандартов (Роллы 8 шт. + Смэш-Бургеры), SLA-метрики и Роялти</div>
                    </div>
                    <div style="display:flex; gap:8px; flex-wrap:wrap;">
                        <a href="/tv_board" target="_blank" class="quick-chip" style="text-decoration:none; border-color:#10b981 !important; color:#10b981 !important;">📺 Открыть ТВ-Табло Гостя ↗</a>
                        <button type="button" class="quick-chip" style="border-color:#eab308 !important; color:#eab308 !important;" onclick="window.loadBurgerLinePreset()">🍔 + Загрузить линейку Бургеров в меню</button>
                        <button type="button" class="quick-chip" style="border-color:#dc2626 !important; color:#dc2626 !important;" onclick="document.getElementById('franchise-hq-modal').style.display='none'">✕ Закрыть</button>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:12px; margin-bottom:18px;">
                    <div class="card-panel" style="padding:14px;">
                        <div style="font-size:11px; opacity:0.7;">ВЫРУЧКА ФЛАГМАНА (30 ДН.)</div>
                        <div style="font-size:24px; font-weight:900; color:#10b981; margin-top:4px;">${d.flagship_revenue} ₽</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">Сегодня: <b>${d.today_revenue} ₽</b> (${d.today_orders} зак.)</div>
                    </div>
                    <div class="card-panel" style="padding:14px;">
                        <div style="font-size:11px; opacity:0.7;">СРЕДНИЙ ЧЕК ТОЧКИ</div>
                        <div style="font-size:24px; font-weight:900; color:#38bdf8; margin-top:4px;">${d.avg_check} ₽</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">Всего заказов: <b>${d.flagship_orders}</b></div>
                    </div>
                    <div class="card-panel" style="padding:14px;">
                        <div style="font-size:11px; opacity:0.7;">СТАНДАРТ ФРАНШИЗЫ (8 КУСОЧКОВ)</div>
                        <div style="font-size:22px; font-weight:900; color:#ff6900; margin-top:4px;">${d.rolls_8pcs_compliant} / ${d.menu_total} поз.</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">100% контроль выхода порций</div>
                    </div>
                    <div class="card-panel" style="padding:14px;">
                        <div style="font-size:11px; opacity:0.7;">БУРГЕРНЫЙ ЦЕХ (МУЛЬТИ-КУХНЯ)</div>
                        <div style="font-size:22px; font-weight:900; color:#eab308; margin-top:4px;">${d.burger_items_count} бургеров</div>
                        <div style="font-size:11px; opacity:0.8; margin-top:3px;">Готовность к запуску доставки бургеров</div>
                    </div>
                </div>

                <h3 style="margin:0 0 10px; font-size:14px; text-transform:uppercase; color:#38bdf8;">🌐 Матрица точек сети и расчёт Роялти партнёров</h3>
                <table>
                    <tr>
                        <th>Код точки</th>
                        <th>Локация</th>
                        <th>Формат кухни</th>
                        <th>Заказы</th>
                        <th>Оборот</th>
                        <th>Роялти основателю</th>
                        <th>Норматив SLA</th>
                    </tr>
                    ${branchRows}
                </table>
            </div>`;
        });
    };

    window.loadBurgerLinePreset = function() {
        fetch('/api/franchise/add_burger_preset', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            alert('В меню успешно добавлено новых позиций бургерного цеха: ' + (d.added || 0) + ' шт.! Обновите кассу.');
            window.openFranchiseHqModal();
        });
    };

    // Добавляем кнопку «👑 Франшиза» и «📺 ТВ-Табло» в плавающий док-пульт
    function upgradeFloatingDock() {
        const dock = document.getElementById('omega-floating-dock');
        if (dock && !document.getElementById('btn-franchise-hq')) {
            const btn = document.createElement('button');
            btn.id = 'btn-franchise-hq';
            btn.type = 'button';
            btn.className = 'quick-chip omega-internal-btn';
            btn.style.cssText = 'border-color:#eab308 !important; color:#eab308 !important; font-weight:900; cursor:pointer; padding:4px 12px;';
            btn.innerHTML = '👑 Франшиза & Бургеры';
            btn.onclick = function() { window.openFranchiseHqModal(); };
            dock.prepend(btn);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        initInstantMenuFilter();
        setTimeout(upgradeFloatingDock, 750);
    });
    setTimeout(initInstantMenuFilter, 500);
    setTimeout(upgradeFloatingDock, 950);
})();
