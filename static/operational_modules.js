(function() {
    function escHtml(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
    // === СПРАВОЧНИК УЛИЦ Г. ИНТА И ПРАВИЛА АВТО-ОПРЕДЕЛЕНИЯ ЗОНЫ ===
    const INTA_STREETS = [
        { street: "ул. Горького", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Мира", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Куратова", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Воркутинская", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Полярная", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Морозова", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Бабушкина", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Дзержинского", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Лунина", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Социалистическая", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Чапаева", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Чернова", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Спортивная", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Школьная", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Промышленная", zone: "Город", fee: 0, courier: 150, distant: false },
        { street: "ул. Западная", zone: "Западный", fee: 150, courier: 200, distant: true },
        { street: "ул. Заречная", zone: "Западный", fee: 150, courier: 200, distant: true },
        { street: "ул. Геологов", zone: "Западный", fee: 150, courier: 200, distant: true },
        { street: "ул. Шахтинская", zone: "Западный", fee: 150, courier: 200, distant: true },
        { street: "ул. Северная", zone: "Западный", fee: 150, courier: 200, distant: true },
        { street: "ул. Кирова", zone: "Южный", fee: 200, courier: 250, distant: true },
        { street: "ул. Чайковского", zone: "Южный", fee: 200, courier: 250, distant: true },
        { street: "ул. Южная", zone: "Южный", fee: 200, courier: 250, distant: true },
        { street: "ул. Сельскохозяйственная", zone: "Южный", fee: 200, courier: 250, distant: true },
        { street: "ул. Совхозная", zone: "Южный", fee: 200, courier: 250, distant: true },
        { street: "ул. Вокзальная (Верхняя Инта)", zone: "Верхняя Инта", fee: 350, courier: 350, distant: true },
        { street: "ул. Станционная (Верхняя Инта)", zone: "Верхняя Инта", fee: 350, courier: 350, distant: true },
        { street: "ул. Железнодорожная", zone: "Верхняя Инта", fee: 350, courier: 350, distant: true },
        { street: "пгт. Верхняя Инта", zone: "Верхняя Инта", fee: 350, courier: 350, distant: true },
        { street: "пос. Юсьтыдор", zone: "Верхняя Инта", fee: 350, courier: 350, distant: true }
    ];

    // --- МОДУЛЬ 1: АВТО-ОПРЕДЕЛЕНИЕ ЗОНЫ ПО АДРЕСУ ---
    function initStreetAutoDetector() {
        const addrInputs = document.querySelectorAll('input[placeholder*="Адрес"], input[placeholder*="адрес"], input[placeholder*="улиц"], input[name="address"], #address, #client_address, #order-address');
        if (!addrInputs.length) return;

        let datalist = document.getElementById('inta-streets-datalist');
        if (!datalist) {
            datalist = document.createElement('datalist');
            datalist.id = 'inta-streets-datalist';
            INTA_STREETS.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item.street + ", д. ";
                opt.label = `${item.zone} (Доставка: ${item.fee} ₽ | Курьеру: ${item.courier} ₽)`;
                datalist.appendChild(opt);
            });
            document.body.appendChild(datalist);
        }

        addrInputs.forEach(inp => {
            inp.setAttribute('list', 'inta-streets-datalist');

            let badge = inp.parentElement.querySelector('.auto-zone-badge');
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'auto-zone-badge';
                badge.style.cssText = 'font-size:11px; font-weight:700; margin-top:4px; padding:4px 8px; border-radius:5px; display:none; background:rgba(22,163,74,0.12); color:#16a34a; border:1px solid rgba(22,163,74,0.35);';
                inp.insertAdjacentElement('afterend', badge);
            }

            inp.addEventListener('input', function() {
                const val = (this.value || '').trim();
                if (val.length < 3) {
                    badge.style.display = 'none';
                    return;
                }
                fetch('/api/detect_zone?address=' + encodeURIComponent(val))
                .then(r => r.json())
                .then(data => {
                    if (!data || !data.zone_name) return;
                    badge.style.display = 'block';
                    if (data.is_distant) {
                        badge.style.background = 'rgba(255,105,0,0.14)';
                        badge.style.color = '#ff6900';
                        badge.style.borderColor = 'rgba(255,105,0,0.4)';
                    } else {
                        badge.style.background = 'rgba(22,163,74,0.12)';
                        badge.style.color = '#16a34a';
                        badge.style.borderColor = 'rgba(22,163,74,0.35)';
                    }
                    badge.innerHTML = `📍 Район: <b>${escHtml(data.zone_name)}</b> • Доставка: <b>${escHtml(data.client_fee)} ₽</b> • Курьеру: <b>${escHtml(data.courier_fee)} ₽</b>`;

                    // Автоматически переключаем select зоны доставки на кассе или сайте, если он есть
                    const selects = document.querySelectorAll('select');
                    selects.forEach(sel => {
                        const opts = Array.from(sel.options);
                        const isZoneSelect = opts.some(o => o.text.includes('₽') || o.text.toLowerCase().includes('район') || o.text.toLowerCase().includes('инта') || o.text.toLowerCase().includes('центр'));
                        if (isZoneSelect) {
                            const targetOpt = opts.find(o => o.text.toLowerCase().includes(data.zone_short.toLowerCase())) ||
                                              opts.find(o => parseInt(o.value) === data.client_fee);
                            if (targetOpt && sel.value !== targetOpt.value) {
                                sel.value = targetOpt.value;
                                sel.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        }
                    });
                }).catch(() => {});
            });
        });
    }

    // --- МОДУЛЬ 2: ЗВУКОВОЙ ГОНГ И ЦВЕТОВЫЕ ТАЙМЕРЫ НА КУХНЕ (KDS) ---
    let audioCtx = null;
    window.playKitchenGong = function() {
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!audioCtx) audioCtx = new Ctx();
            if (audioCtx.state === 'suspended') audioCtx.resume();

            const now = audioCtx.currentTime;
            // Двухтональный ресторанный гонг (A5 -> E5)
            [[880, 0, 0.45], [659.25, 0.22, 0.75]].forEach(([freq, startOffset, duration]) => {
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(freq, now + startOffset);
                gain.gain.setValueAtTime(0.35, now + startOffset);
                gain.gain.exponentialRampToValueAtTime(0.001, now + startOffset + duration);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start(now + startOffset);
                osc.stop(now + startOffset + duration);
            });
        } catch (e) {
            console.log("Gong audio error:", e);
        }
    };

    function initKitchenKdsMonitor() {
        if (!window.location.pathname.startsWith('/kitchen')) return;

        // Добавляем стили цветовой сигнализации просрочки на KDS
        const kdsStyle = document.createElement('style');
        kdsStyle.textContent = `
            @keyframes kdsOverduePulse {
                0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.55); border-color: #dc2626 !important; }
                50% { box-shadow: 0 0 16px 4px rgba(220, 38, 38, 0.85); border-color: #ef4444 !important; }
            }
            .kds-sla-ok { border-left: 4px solid #16a34a !important; }
            .kds-sla-warn { border: 2px solid #eab308 !important; background: rgba(234, 179, 8, 0.06) !important; }
            .kds-sla-overdue { border: 2px solid #dc2626 !important; animation: kdsOverduePulse 1.6s infinite !important; }
            .kds-timer-pill {
                display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px;
                border-radius: 5px; font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 800;
            }
        `;
        document.head.appendChild(kdsStyle);

        // Плавающая кнопка проверки и активации звука Гонга на кухне
        const soundBtn = document.createElement('button');
        soundBtn.type = 'button';
        soundBtn.className = 'quick-chip';
        soundBtn.style.cssText = 'position:fixed; bottom:16px; right:16px; z-index:9999; padding:8px 14px; font-weight:700; border-color:#16a34a; color:#16a34a;';
        soundBtn.innerHTML = '🔔 Звук Гонга KDS: ВКЛ (Тест)';
        soundBtn.onclick = function() {
            window.playKitchenGong();
        };
        document.body.appendChild(soundBtn);

        let knownOrderIds = null;
        let activeOrdersMap = {};

        function pollKitchenOrders() {
            fetch('/api/orders?status=active')
            .then(r => r.json())
            .then(orders => {
                if (!Array.isArray(orders)) return;
                const currentIds = new Set(orders.map(o => o.id));
                orders.forEach(o => { activeOrdersMap[o.id] = o; });

                if (knownOrderIds !== null) {
                    let hasNew = false;
                    currentIds.forEach(id => {
                        if (!knownOrderIds.has(id)) hasNew = true;
                    });
                    if (hasNew) {
                        window.playKitchenGong();
                    }
                }
                knownOrderIds = currentIds;
                decorateKdsCards();
            }).catch(() => {});
        }

        function decorateKdsCards() {
            const nowMs = Date.now();
            // Ищем карточки заказов на экране KDS по тексту #ID
            const allElements = document.querySelectorAll('.order-card, .kds-card, .ticket-card, .card, .card-panel, div');
            allElements.forEach(el => {
                if (el.children.length < 2 || el.clientHeight < 80 || el.clientWidth > 600) return;
                const txt = el.innerText || '';
                const match = txt.match(/#(\d+)/);
                if (!match) return;
                const oid = parseInt(match[1]);
                const ord = activeOrdersMap[oid];
                if (!ord || !ord.created_at) return;

                const createdMs = new Date(ord.created_at.replace(' ', 'T')).getTime();
                if (isNaN(createdMs)) return;
                const diffSec = Math.max(0, Math.floor((nowMs - createdMs) / 1000));
                const mins = Math.floor(diffSec / 60);
                const secs = diffSec % 60;
                const timeStr = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

                el.classList.remove('kds-sla-ok', 'kds-sla-warn', 'kds-sla-overdue');
                let statusColor = '#16a34a';
                let statusLabel = 'В НОРМЕ';
                if (mins >= 15) {
                    el.classList.add('kds-sla-overdue');
                    statusColor = '#dc2626';
                    statusLabel = '🔥 ПРОСРОЧКА >15 МИН';
                } else if (mins >= 10) {
                    el.classList.add('kds-sla-warn');
                    statusColor = '#eab308';
                    statusLabel = '⚠ ВНИМАНИЕ >10 МИН';
                } else {
                    el.classList.add('kds-sla-ok');
                }

                let badge = el.querySelector('.kds-timer-pill');
                if (!badge) {
                    badge = document.createElement('div');
                    badge.className = 'kds-timer-pill';
                    badge.style.marginTop = '6px';
                    badge.style.marginBottom = '6px';
                    el.prepend(badge);
                }
                badge.style.background = statusColor + '22';
                badge.style.color = statusColor;
                badge.style.border = `1px solid ${statusColor}`;
                badge.innerHTML = `⏱ ${timeStr} • ${statusLabel}`;
            });
        }

        pollKitchenOrders();
        setInterval(pollKitchenOrders, 4000);
        setInterval(decorateKdsCards, 1000);
    }

    // --- МОДУЛЬ 3: МГНОВЕННАЯ ПЕЧАТЬ ЧЕКА В 1 КЛИК БЕЗ УХОДА С КАССЫ ---
    window.printReceiptOneClick = function(orderId, type = 'fiscal') {
        fetch(`/api/print/direct/${orderId}?type=${type}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.printed_direct) {
                console.log("Чек отправлен напрямую на термопринтер:", data.message);
                return;
            }
            // Если физический принтер не подключен по USB/IP — печатаем через невидимый iframe без открытия новой вкладки
            let printFrame = document.getElementById('silent-print-iframe');
            if (!printFrame) {
                printFrame = document.createElement('iframe');
                printFrame.id = 'silent-print-iframe';
                printFrame.style.cssText = 'position:fixed; right:0; bottom:0; width:0; height:0; border:0;';
                document.body.appendChild(printFrame);
            }
            const url = (type === 'ticket') ? `/ticket/${orderId}` : `/fiscal/${orderId}`;
            printFrame.src = url;
        }).catch(() => {});
    };

    document.addEventListener("DOMContentLoaded", function() {
        initStreetAutoDetector();
        initKitchenKdsMonitor();
    });
})();
