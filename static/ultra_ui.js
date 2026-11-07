(function() {
    if (window.location.pathname.startsWith('/site') ||
        window.location.pathname.startsWith('/track') ||
        window.location.pathname.startsWith('/rate') ||
        window.location.pathname.startsWith('/login')) {
        return;
    }

    // Встроенная защита верстки топ-бара (чтобы он никогда не становился левой колонкой во flex/grid)
    const criticalStyle = document.createElement('style');
    criticalStyle.id = 'erp-topbar-critical-css';
    criticalStyle.textContent = `
        body { padding-top: 46px !important; }
        #ultra-erp-topbar.erp-topbar {
            position: fixed !important; top: 0 !important; left: 0 !important; right: 0 !important;
            width: 100% !important; height: 46px !important; z-index: 99999 !important;
            display: flex !important; flex-direction: row !important; align-items: center !important;
            justify-content: space-between !important; padding: 0 12px !important; gap: 8px !important;
            background: #111216 !important; border-bottom: 1px solid #27272a !important; box-sizing: border-box !important;
        }
        #ultra-erp-topbar .erp-topbar-left, #ultra-erp-topbar .erp-topbar-right, #ultra-erp-topbar .erp-nav {
            display: flex !important; flex-direction: row !important; align-items: center !important;
            gap: 5px !important; white-space: nowrap !important;
        }
        #ultra-erp-topbar .erp-brand {
            display: inline-flex !important; align-items: center !important; gap: 5px !important;
            font-size: 13px !important; font-weight: 800 !important; color: #fafafa !important;
            text-decoration: none !important; margin-right: 4px !important;
        }
        #ultra-erp-topbar .erp-badge {
            background: #ff6900 !important; color: #fff !important; font-size: 10px !important;
            padding: 2px 5px !important; border-radius: 4px !important; font-weight: 800 !important;
        }
        #ultra-erp-topbar .erp-nav-link {
            display: inline-flex !important; align-items: center !important; padding: 5px 9px !important;
            border-radius: 6px !important; font-size: 12px !important; font-weight: 600 !important;
            color: #a1a1aa !important; text-decoration: none !important; border: 1px solid transparent !important;
        }
        #ultra-erp-topbar .erp-nav-link:hover { background: #1f2026 !important; color: #fafafa !important; }
        #ultra-erp-topbar .erp-nav-link.active {
            background: rgba(255, 105, 0, 0.16) !important; color: #ff6900 !important;
            border-color: rgba(255, 105, 0, 0.4) !important; font-weight: 700 !important;
        }
        html[data-theme="light"] #ultra-erp-topbar.erp-topbar {
            background: #d8dee9 !important; border-bottom: 1px solid #b8c2d4 !important;
        }
        html[data-theme="light"] #ultra-erp-topbar .erp-brand { color: #0f172a !important; }
        html[data-theme="light"] #ultra-erp-topbar .erp-nav-link { color: #334155 !important; }
        html[data-theme="light"] #ultra-erp-topbar .erp-nav-link.active {
            background: #ff6900 !important; color: #ffffff !important; border-color: #ff6900 !important;
        }
    `;
    document.head.appendChild(criticalStyle);

    function applySavedTheme(theme) {
        const t = (theme === 'light') ? 'light' : 'dark';
        localStorage.setItem('krevetka_theme', t);
        document.documentElement.setAttribute('data-theme', t);
        if (document.body) {
            document.body.classList.toggle('light-theme', t === 'light');
            document.body.classList.toggle('theme-light', t === 'light');
            document.body.classList.toggle('dark-theme', t === 'dark');
        }
        const btn = document.getElementById('erp-theme-toggle-btn');
        if (btn) {
            btn.innerText = (t === 'light') ? '☀ Светлая' : '🌙 Тёмная';
        }
    }

    window.toggleErpTheme = function() {
        const cur = localStorage.getItem('krevetka_theme') || 'dark';
        applySavedTheme(cur === 'dark' ? 'light' : 'dark');
    };

    window.closeMyPersonalShift = function() {
        if (!confirm('Завершить вашу личную смену и зафиксировать заработок в табеле?')) return;
        fetch('/api/staff_shift/close_my', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                alert(`Смена закрыта!\nОтработано: ${d.hours} ч.\nПо часовой ставке: ${d.hourly_pay} ₽\nЗа доставку заказов: ${d.delivery_pay} ₽\nИТОГО НАЧИСЛЕНО: ${d.total_pay} ₽`);
                window.location.href = '/logout';
            }
        });
    };

    document.addEventListener("DOMContentLoaded", function() {
        applySavedTheme(localStorage.getItem('krevetka_theme') || 'dark');

        Promise.all([
            fetch('/api/current_role').then(r => r.json()).catch(() => ({role: 'admin', username: 'Администратор'})),
            fetch('/api/erp/live_metrics').then(r => r.json()).catch(() => ({shift_revenue: 0, active_kds: 0, avg_cook_time: '00:00'}))
        ]).then(([roleData, metrics]) => {
            const isAdmin = (roleData.role === 'admin');
            const path = window.location.pathname;

            const navLinks = [
                { href: "/", label: "Касса POS", icon: "💳", show: true },
                { href: "/kitchen", label: "Экран KDS", icon: "🔥", show: true },
                { href: "/courier", label: "Курьер", icon: "🛵", show: true },
                { href: "/admin", label: "Управление и Штат", icon: "👥", show: isAdmin || roleData.can_edit_menu },
                { href: "/warehouse", label: "Склад и П/Ф", icon: "📦", show: isAdmin || roleData.can_edit_menu },
                { href: "/accounting", label: "Бухгалтерия", icon: "🧮", show: isAdmin || roleData.can_view_finance },
                { href: "/analytics", label: "Финансы P&L", icon: "📊", show: isAdmin || roleData.can_view_finance },
                { href: "/crm", label: "CRM", icon: "🤝", show: isAdmin },
                { href: "/map", label: "Зоны", icon: "🗺", show: isAdmin }
            ];

            const navHtml = navLinks.filter(l => l.show).map(l => {
                const active = (path === l.href) ? 'active' : '';
                return `<a href="${l.href}" class="drop-item ${active}">${l.icon} ${l.label}</a>`;
            }).join('');

            const ps = roleData.personal_shift;
            const shiftBadge = ps
                ? `<span class="kpi-pill" title="Личная смена открыта в ${ps.opened_at}">Смена: <b style="color:#16a34a;">${ps.hours} ч</b> • <b style="color:#ff6900;">${ps.total_pay} ₽</b></span>
                   <button type="button" class="quick-chip" onclick="closeMyPersonalShift()" style="font-size:11px; padding:4px 8px;">Закрыть смену</button>`
                : '';

            const existingBar = document.getElementById('ultra-erp-topbar');
            if (existingBar) existingBar.remove();

            const bar = document.createElement('div');
            bar.id = 'ultra-erp-topbar';
            bar.className = 'erp-topbar';
            bar.innerHTML = `
                <div class="erp-topbar-left">
                    <button type="button" class="btn-back-nav" onclick="window.history.length > 1 ? window.history.back() : window.location.href='/'" style="padding:4px 8px; font-size:11px;">←</button>
                    <a href="/" class="erp-brand">КРЕВЕТКА IS <span class="erp-badge">ERP</span></a>
                    <details class="menu-drop" id="service-menu">
                        <summary aria-label="Открыть меню сервиса">Сервис<span class="chev">▾</span></summary>
                        <div class="drop-panel">
                            ${navHtml}
                            <div class="drop-sep"></div>
                            <a class="drop-item" href="/logout">🚪 Выйти (${roleData.username || 'Сотрудник'})</a>
                        </div>
                    </details>
                </div>
                <div class="erp-topbar-right">
                    <span class="kpi-pill">Касса: <b id="top-shift-rev">${metrics.shift_revenue} ₽</b></span>
                    <span class="kpi-pill">KDS: <b id="top-active-kds">${metrics.active_kds}</b> (${metrics.avg_cook_time})</span>
                    ${shiftBadge}
                    <span class="kpi-pill">👤 <b>${roleData.username || 'Сотрудник'}</b></span>
                    <button type="button" id="erp-theme-toggle-btn" class="quick-chip" onclick="toggleErpTheme()" style="font-size:11px; padding:4px 8px;">Тема</button>
                    <a href="/logout" class="quick-chip" style="font-size:11px; padding:4px 8px; border-color:#ff6900; color:#ff6900;">ПИН</a>
                </div>
            `;
            document.body.prepend(bar);
            applySavedTheme(localStorage.getItem('krevetka_theme') || 'dark');

            // Закрытие дропдауна: клик по ссылке, вне меню, Escape
            const drop = document.getElementById('service-menu');
            if (drop) {
                drop.addEventListener('click', function(e) {
                    if (e.target.closest('a')) drop.removeAttribute('open');
                });
                document.addEventListener('click', function(e) {
                    if (drop.open && !drop.contains(e.target)) drop.removeAttribute('open');
                });
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape' && drop.open) drop.removeAttribute('open');
                });
            }
        });
    });
})();
