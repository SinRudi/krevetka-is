
function goBackSmart() {
    if (window.location.pathname === '/') {
        return;
    }
    if (document.referrer && document.referrer.includes(window.location.host) && document.referrer !== window.location.href) {
        window.history.back();
    } else {
        window.location.href = '/';
    }
}

document.addEventListener("DOMContentLoaded", function() {
    const path = window.location.pathname;
    // Не показываем админский док на клиентской витрине (/site), трекинге (/track), оценке (/rate) и печатных формах
    if (path.startsWith('/site') || path.startsWith('/track') || path.startsWith('/rate') ||
        path.startsWith('/receipt') || path.startsWith('/ticket') || path.startsWith('/fiscal') ||
        path.startsWith('/shift/z_report') || path.startsWith('/login')) {
        return;
    }

    document.body.classList.add("has-ultra-dock");

    fetch('/api/current_role').then(r=>r.json()).then(roleData => {
        const role = roleData.role || 'admin';
        const isAdmin = (role === 'admin');

        const navItems = [
            { href: "/", label: "Касса POS", show: true },
            { href: "/kitchen", label: "Экран KDS", show: true },
            { href: "/courier", label: "Курьер", show: true },
            { href: "/admin", label: "Управление", show: isAdmin },
            { href: "/warehouse", label: "Склад и П/Ф", show: isAdmin },
            { href: "/accounting", label: "Бухгалтерия (Белая / Упр.)", show: isAdmin },
            { href: "/analytics", label: "Финансы P&L", show: isAdmin },
            { href: "/reports", label: "Смены (Z)", show: true },
            { href: "/crm", label: "Клиенты CRM", show: isAdmin },
            { href: "/map", label: "Гео-зоны", show: isAdmin },
            { href: "/chat", label: "Чат", show: true },
            { href: "/site", label: "Витрина ↗", target: "_blank", show: true }
        ];

        const dock = document.createElement("div");
        dock.id = "krevetka-ultra-dock";

        const linksHtml = navItems.filter(i => i.show).map(item => {
            const isActive = (item.href === "/" && path === "/") || (item.href !== "/" && path.startsWith(item.href));
            const targetAttr = item.target ? `target="${item.target}"` : "";
            return `<a href="${item.href}" ${targetAttr} class="ultra-nav-link ${isActive ? 'active' : ''}">${item.label}</a>`;
        }).join("");

        const nextRole = isAdmin ? 'cashier' : 'admin';
        const roleLabel = isAdmin ? 'АДМИН' : 'КАССИР';
        const backBtnHtml = path !== '/' ? `<button type="button" class="dock-back-btn" onclick="goBackSmart()" title="Вернуться на предыдущий экран">← Назад</button>` : '';

        dock.innerHTML = `
            <div class="dock-left-group">
                ${backBtnHtml}
                <a href="/" class="ultra-brand">
                    <span>КРЕВЕТКА IS</span>
                    <span class="ultra-brand-badge">ERP</span>
                </a>
            </div>
            <div class="ultra-nav-links">${linksHtml}</div>
            <div class="ultra-right-tools">
                <span class="kpi-pill" id="dock-kpi-rev">Выручка: <b>—</b></span>
                <span class="kpi-pill" id="dock-kpi-sla">KDS: <b>—</b></span>
                <span class="kpi-pill">Сотрудник: <b>${roleData.username || roleLabel}</b></span>
                <a href="/logout" class="quick-chip" style="font-size:11px; padding:4px 8px; border-color:#ff6900; color:#ff6900;" title="Заблокировать терминал и ввести другой ПИН-код">Сменить ПИН</a>
                <button class="ultra-demo-btn" onclick="triggerPresentationDemoOrder()">+ Тест-заказ</button>
                <span class="ultra-clock" id="ultra-live-clock">--:--:--</span>
            </div>
        `;

        document.body.prepend(dock);

        function updateClock() {
            const el = document.getElementById("ultra-live-clock");
            if (el) el.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        }
        function updateLiveKpi() {
            fetch('/api/erp/live_metrics').then(r=>r.json()).then(m => {
                const revEl = document.getElementById('dock-kpi-rev');
                const slaEl = document.getElementById('dock-kpi-sla');
                if (revEl) revEl.innerHTML = `Смена: <b>${m.shift_revenue} ₽</b>`;
                if (slaEl) slaEl.innerHTML = `KDS: <b>${m.active_kds} в раб. (${m.avg_cook_time})</b>`;
            }).catch(()=>{});
        }
        updateClock();
        updateLiveKpi();
        setInterval(updateClock, 1000);
        setInterval(updateLiveKpi, 6000);
    });
});

function triggerPresentationDemoOrder() {
    fetch('/api/demo/generate_order', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
        if (d.success) {
            if (typeof fetchAllOrders === 'function') fetchAllOrders();
            if (typeof fetchActiveOrders === 'function') fetchActiveOrders();
            if (typeof fetchOrders === 'function') fetchOrders();
            alert(`Тестовый заказ #${d.order_id} создан (${d.summary}). Сумма: ${d.total} ₽.`);
        }
    });
}
