(function() {
    function buildExecutiveNavigation() {
        if (document.getElementById('exec-erp-dropdown')) return;

        // Находим верхнюю панель навигации
        const allAnchors = Array.from(document.querySelectorAll('a, button'));
        const posBtn = allAnchors.find(el => {
            const t = (el.textContent || '').trim();
            return t === 'Касса POS' || t.includes('Z-Отчёт');
        });
        if (!posBtn || !posBtn.parentElement) return;

        const navBar = posBtn.parentElement;

        // Скрываем второстепенные кнопки из главной полосы, чтобы оставить только 4 рабочих экрана смены:
        // Касса POS, Экран KDS, Курьер, Зоны (Карта)
        const hideKeywords = [
            'z-отчёт', 'p&l', 'управление и штат', 'склад и п/ф',
            'бухгалтерия', 'финансы p&l', 'crm', 'декларация фнс',
            '54-фз', 'витрина сбп'
        ];

        Array.from(navBar.children).forEach(child => {
            const txt = (child.textContent || '').trim().toLowerCase();
            if (hideKeywords.some(k => txt.includes(k))) {
                child.style.display = 'none';
            }
        });

        // Создаём единую строгую кнопку с выпадающим мега-меню всех функций ERP
        const wrapper = document.createElement('div');
        wrapper.id = 'exec-erp-dropdown';
        wrapper.className = 'exec-dropdown-wrapper';

        wrapper.innerHTML = `
            <button type="button" class="exec-dropdown-trigger" id="exec-menu-btn">
                <span>⚙️ Управление и ERP</span>
                <span style="font-size:10px; opacity:0.7;">▾</span>
            </button>
            <div class="exec-mega-menu" id="exec-mega-panel">
                <!-- Колонка 1: Финансы, Касса и 54-ФЗ -->
                <div class="exec-menu-col">
                    <div class="exec-col-title">Финансы, 54-ФЗ и Налоги</div>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('fch_registry')">
                        <span>🧾 Реестр «ФЧ» (54-ФЗ)</span>
                        <span class="exec-menu-sub">Чеки и ОФД</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('zreport')">
                        <span>📊 Z-Отчёт и Сверка сейфа</span>
                        <span class="exec-menu-sub">Горячая клавиша F9</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('tax')">
                        <span>🏛 Декларация ФНС & КУДиР</span>
                        <span class="exec-menu-sub">УСН / Патент / XML</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('datamatrix')">
                        <span>🔍 Сканер «Честный Знак»</span>
                        <span class="exec-menu-sub">Проверка марок [М+]</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('sim')">
                        <span>🎛 Симулятор P&L и прибыли</span>
                        <span class="exec-menu-sub">Точка безубыточности</span>
                    </button>
                    <a href="/accounting" class="exec-menu-item">
                        <span>💼 Бухгалтерия и Расходы</span>
                        <span class="exec-menu-sub">Ордера и табель</span>
                    </a>
                    <a href="/analytics" class="exec-menu-item">
                        <span>📈 Финансовый отчёт P&L</span>
                        <span class="exec-menu-sub">Динамика выручки</span>
                    </a>
                </div>

                <!-- Колонка 2: Цех, Склад и Техкарты -->
                <div class="exec-menu-col">
                    <div class="exec-col-title">Цех, Склад и Техкарты (8 шт.)</div>
                    <a href="/warehouse" class="exec-menu-item">
                        <span>📦 Склад и Приход сырья</span>
                        <span class="exec-menu-sub">Остатки и накладные</span>
                    </a>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('recipes')">
                        <span>🍣 Техкарты (Стандарт 8 шт.)</span>
                        <span class="exec-menu-sub">Граммовки и фудкост</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('prep')">
                        <span>🔪 Акты П/Ф (Рис / Лосось)</span>
                        <span class="exec-menu-sub">Уварка и разделка</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('inventory')">
                        <span>⚖️ Ревизия склада (Весы)</span>
                        <span class="exec-menu-sub">Сличительная ведомость</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('ai_prep')">
                        <span>🔮 План заготовок на утро</span>
                        <span class="exec-menu-sub">Норматив смены</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('haccp')">
                        <span>🛡 Журнал ХАССП (СанПиН)</span>
                        <span class="exec-menu-sub">Температуры и фритюр</span>
                    </button>
                </div>

                <!-- Колонка 3: Меню, Маржа и Клиенты -->
                <div class="exec-menu-col">
                    <div class="exec-col-title">Маркетинг, Маржа и CRM</div>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('shield')">
                        <span>🛡 Щит Маржи (Анти-Инфляция)</span>
                        <span class="exec-menu-sub">Защита фудкоста 28%</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('abc')">
                        <span>🏆 ABC-Матрица продаж</span>
                        <span class="exec-menu-sub">Рейтинг роллов A/B/C</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('combos')">
                        <span>🍱 Конструктор Сетов</span>
                        <span class="exec-menu-sub">Наборы 24 / 32 / 40 шт.</span>
                    </button>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('rfm')">
                        <span>🧲 Удержание VIP-гостей</span>
                        <span class="exec-menu-sub">Возврат через WhatsApp</span>
                    </button>
                    <a href="/crm" class="exec-menu-item">
                        <span>👥 Клиентская база (CRM)</span>
                        <span class="exec-menu-sub">Бонусы и история</span>
                    </a>
                    <a href="/edit_menu" class="exec-menu-item">
                        <span>📋 Редактор позиций меню</span>
                        <span class="exec-menu-sub">Цены, фото, стоп-лист</span>
                    </a>
                </div>

                <!-- Колонка 4: Витрины, Логистика и Администрирование -->
                <div class="exec-menu-col">
                    <div class="exec-col-title">Каналы продаж и Система</div>
                    <a href="/admin" class="exec-menu-item">
                        <span>👔 Админ-панель и Штат</span>
                        <span class="exec-menu-sub">Сотрудники и ПИН-коды</span>
                    </a>
                    <a href="/map" class="exec-menu-item">
                        <span>🗺 Карта зон и GPS курьеров</span>
                        <span class="exec-menu-sub">Районы г. Инта</span>
                    </a>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('inta_sla')">
                        <span>🛵 Сводка по районам Инты</span>
                        <span class="exec-menu-sub">Выплаты курьерам</span>
                    </button>
                    <a href="/shop" target="_blank" class="exec-menu-item">
                        <span>📱 Онлайн-витрина (/shop) ↗</span>
                        <span class="exec-menu-sub">Самозаказ + СБП QR</span>
                    </a>
                    <a href="/tv_board" target="_blank" class="exec-menu-item">
                        <span>📺 ТВ-Табло Гостя (/tv_board) ↗</span>
                        <span class="exec-menu-sub">Экран выдачи заказов</span>
                    </a>
                    <a href="/orders" class="exec-menu-item">
                        <span>🗂 Архив и список заказов</span>
                        <span class="exec-menu-sub">Все чеки смены</span>
                    </a>
                    <button type="button" class="exec-menu-item" onclick="window.execRun('backup')">
                        <span>💾 Резервная копия БД</span>
                        <span class="exec-menu-sub">Горячий снимок SQLite</span>
                    </button>
                </div>
            </div>
        `;

        // Вставляем кнопку «⚙️ Управление и ERP» сразу после логотипа КРЕВЕТКА IS
        const firstChild = navBar.firstElementChild;
        if (firstChild && firstChild.nextSibling) {
            navBar.insertBefore(wrapper, firstChild.nextSibling);
        } else {
            navBar.prepend(wrapper);
        }

        const triggerBtn = document.getElementById('exec-menu-btn');
        const megaPanel = document.getElementById('exec-mega-panel');

        triggerBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const isOpen = megaPanel.classList.toggle('show');
            triggerBtn.classList.toggle('open', isOpen);
        });

        document.addEventListener('click', function(e) {
            if (!wrapper.contains(e.target)) {
                megaPanel.classList.remove('show');
                triggerBtn.classList.remove('open');
            }
        });
    }

    // Быстрый селектор всех модулей прямо внутри страницы /admin
    function injectAdminPageSelector() {
        if (!window.location.pathname.includes('/admin')) return;
        if (document.getElementById('exec-admin-hub-bar')) return;

        const bar = document.createElement('div');
        bar.id = 'exec-admin-hub-bar';
        bar.innerHTML = `
            <div>
                <div style="font-size:14px; font-weight:800; color:#f8fafc;">Единый центр администрирования КРЕВЕТКА IS</div>
                <div style="font-size:12px; color:#94a3b8;">Выберите нужный контур управления из выпадающего списка или нажмите клавишу F9</div>
            </div>
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                <select id="admin-quick-select" style="min-width:290px; padding:8px 12px; border-radius:8px; background:#19202e; color:#f8fafc; border:1px solid rgba(148,163,184,0.3); font-size:13px; font-weight:600;" onchange="if(this.value) { window.execRun(this.value); this.value=''; }">
                    <option value="">▾ Выберите функцию или модуль ERP...</option>
                    <optgroup label="Финансы, Касса и 54-ФЗ">
                        <option value="fch_registry">🧾 Реестр Фискальных Чеков («ФЧ» 54-ФЗ)</option>
                        <option value="zreport">📊 Z-Отчёт, Сверка купюр и Авто-закуп</option>
                        <option value="tax">🏛 Налоговая Декларация ФНС (КНД 1152017) и КУДиР</option>
                        <option value="datamatrix">🔍 Сканер «Честный Знак» (Проверка марок М+)</option>
                        <option value="sim">🎛 Финансовый симулятор P&L и Безубыточности</option>
                    </optgroup>
                    <optgroup label="Производство, Склад и Техкарты (8 шт.)">
                        <option value="recipes">🍣 Техкарты роллов (Стандарт 8 кусочков)</option>
                        <option value="prep">🔪 Акты проработки П/Ф (Рис / Лосось / Соусы)</option>
                        <option value="inventory">⚖️ Сличительная ведомость (Ревизия на весах)</option>
                        <option value="ai_prep">🔮 Утренний план заготовок на смену</option>
                        <option value="haccp">🛡 Электронный журнал ХАССП (СанПиН)</option>
                    </optgroup>
                    <optgroup label="Маркетинг и Аналитика меню">
                        <option value="shield">🛡 Анти-инфляционный Щит Маржи (Цель FC 28%)</option>
                        <option value="abc">🏆 ABC-Матрица рентабельности меню</option>
                        <option value="combos">🍱 ИИ-Конструктор прибыльных сетов (24/32/40 шт.)</option>
                        <option value="rfm">🧲 RFM-Удержание уходящих VIP-гостей</option>
                        <option value="inta_sla">🗺 Логистика и выплаты курьерам по районам Инты</option>
                    </optgroup>
                </select>
                <button type="button" class="exec-dropdown-trigger" onclick="window.execRun('fch_registry')">🧾 Открыть реестр ФЧ</button>
                <button type="button" class="exec-dropdown-trigger" onclick="window.execRun('tax')">🏛 Декларация ФНС</button>
            </div>
        `;

        const firstHeader = document.querySelector('.top-bar, nav, header');
        if (firstHeader && firstHeader.nextSibling) {
            firstHeader.parentNode.insertBefore(bar, firstHeader.nextSibling);
        } else {
            document.body.prepend(bar);
        }
    }

    // Единый диспетчер вызова любого модуля из выпадающего меню
    window.execRun = function(action) {
        const megaPanel = document.getElementById('exec-mega-panel');
        const triggerBtn = document.getElementById('exec-menu-btn');
        if (megaPanel) megaPanel.classList.remove('show');
        if (triggerBtn) triggerBtn.classList.remove('open');

        if (action === 'fch_registry') {
            if (window.openHyperionModal) window.openHyperionModal('fch_registry');
        } else if (action === 'zreport' || action === 'abc' || action === 'prep' || action === 'inventory' || action === 'recipes') {
            if (window.openTitaniumSuite) window.openTitaniumSuite(action);
        } else if (action === 'inta_sla') {
            if (window.openTitaniumSuite) window.openTitaniumSuite('inta');
        } else if (action === 'tax') {
            if (window.openApexModule) window.openApexModule('apex_tax');
        } else if (action === 'combos') {
            if (window.openApexModule) window.openApexModule('apex_combos');
        } else if (action === 'sim' || action === 'haccp') {
            if (window.openApexModule) window.openApexModule('apex_sim');
        } else if (action === 'shield') {
            if (window.openSingularityView) window.openSingularityView('sg_shield');
        } else if (action === 'rfm') {
            if (window.openSingularityView) window.openSingularityView('sg_rfm');
        } else if (action === 'ai_prep') {
            if (window.openSingularityView) window.openSingularityView('sg_ai_prep');
        } else if (action === 'datamatrix') {
            if (window.openMonolithFiscalModal) window.openMonolithFiscalModal();
        } else if (action === 'backup') {
            fetch('/api/system/create_backup', { method: 'POST' })
            .then(r => r.json())
            .then(d => alert('Резервная копия базы данных успешно создана:\n' + d.created_file));
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        buildExecutiveNavigation();
        injectAdminPageSelector();
    });
    setTimeout(() => {
        buildExecutiveNavigation();
        injectAdminPageSelector();
    }, 250);
})();
