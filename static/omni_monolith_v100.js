(function() {
    // =========================================================================
    // А. ВСТРАИВАЕМ ПУЛЬТ 54-ФЗ / ЧЕСТНЫЙ ЗНАК / ОНЛАЙН-ВИТРИНЫ В ШАПКУ И В ОКНО F9
    // =========================================================================
    function injectMonolithHeaderButtons() {
        if (document.getElementById('omni-top-fiscal-btn')) return;
        const navLinks = Array.from(document.querySelectorAll('a, button'));
        const target = navLinks.find(el => (el.textContent || '').includes('Декларация ФНС') || (el.textContent || '').includes('Бухгалтерия'));
        if (target && target.parentElement) {
            const btnFiscal = document.createElement('button');
            btnFiscal.id = 'omni-top-fiscal-btn';
            btnFiscal.type = 'button';
            btnFiscal.style.cssText = 'background:rgba(56,189,248,0.16); color:#38bdf8; border:1px solid #38bdf8; border-radius:8px; padding:5px 10px; font-size:12px; font-weight:900; cursor:pointer;';
            btnFiscal.innerHTML = '🧾 54-ФЗ • Честный Знак';
            btnFiscal.onclick = function(e) {
                e.preventDefault();
                window.openMonolithFiscalModal();
            };
            target.parentElement.insertBefore(btnFiscal, target);

            const linkShop = document.createElement('a');
            linkShop.href = '/shop';
            linkShop.target = '_blank';
            linkShop.style.cssText = 'background:rgba(255,105,0,0.18); color:#ff6900; border:1px solid #ff6900; border-radius:8px; padding:5px 10px; font-size:12px; font-weight:900; text-decoration:none;';
            linkShop.innerHTML = '📱 Витрина СБП (/shop) ↗';
            target.parentElement.insertBefore(linkShop, btnFiscal);
        }
    }

    window.openMonolithFiscalModal = function() {
        let modal = document.getElementById('titanium-v20-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'titanium-v20-modal';
            modal.style.cssText = 'position:fixed; inset:0; background:rgba(7,9,14,0.88); z-index:100000; display:flex; align-items:center; justify-content:center; padding:16px; backdrop-filter:blur(5px);';
            document.body.appendChild(modal);
        }
        modal.style.display = 'flex';

        fetch('/api/fiscal/status')
        .then(r => r.json())
        .then(d => {
            const orderOpts = (d.recent_orders || []).map(o =>
                `<option value="${o.id}">Заказ #${o.id} • ${o.total} ₽ (${o.payment_method || 'Оплата'}) — ${o.address || 'Самовывоз'}</option>`
            ).join('');

            const recRows = (d.receipts || []).map(r => `
                <tr>
                    <td><b>#${r.order_id}</b></td>
                    <td>${r.created_at}</td>
                    <td><b>${r.total} ₽</b> (${r.payment_method})</td>
                    <td style="font-family:monospace; font-size:11px;">ФН: ${r.fn_number}<br>ФД: ${r.fd_number} • ФПД: ${r.fpd_sign}</td>
                    <td><a href="/fiscal_slip/${r.order_id}" target="_blank" class="ti-tab-btn ti-internal" style="text-decoration:none; border-color:#10b981; color:#10b981;">🖨 Чек 54-ФЗ с QR ↗</a></td>
                </tr>
            `).join('') || '<tr><td colspan="5">Фискальных чеков за смену ещё не пробито</td></tr>';

            const markRows = (d.marks || []).map(m => `
                <tr>
                    <td>${m.scanned_at}</td>
                    <td style="font-family:monospace; font-size:11px;">GTIN: ${m.gtin} • S/N: ${m.serial}</td>
                    <td><b>${m.product_name}</b></td>
                    <td><span class="roll-8-badge" style="border-color:#10b981; color:#10b981;">${m.verdict}</span></td>
                </tr>
            `).join('') || '<tr><td colspan="4">Коды маркировки DataMatrix сегодня ещё не сканировались</td></tr>';

            modal.innerHTML = `
                <div class="card-panel" style="max-width:1140px; width:100%; max-height:92vh; overflow-y:auto; padding:22px; border:1px solid #38bdf8;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px; padding-bottom:12px; border-bottom:1px solid rgba(148,163,184,0.2);">
                        <div>
                            <div style="font-size:18px; font-weight:900; color:#38bdf8;">🧾 ШЛЮЗ 54-ФЗ (АТОЛ WEBSERVER) • РАЗРЕШИТЕЛЬНЫЙ РЕЖИМ «ЧЕСТНЫЙ ЗНАК» • БЭКАП БД</div>
                            <div style="font-size:12px; opacity:0.8; margin-top:2px;">Прямая фискализация чеков, проверка марок DataMatrix [М+] на воду/напитки и горячее резервирование базы SQLite</div>
                        </div>
                        <div style="display:flex; gap:8px;">
                            <button type="button" class="ti-tab-btn ti-internal" style="border-color:#eab308; color:#eab308;" onclick="window.runHotDbBackup(this)">💾 Создать горячий бэкап БД (sushi.db)</button>
                            <button type="button" class="ti-tab-btn ti-internal" onclick="window.openTitaniumSuite && window.openTitaniumSuite('zreport')">← К Z-Отчёту</button>
                            <button type="button" class="ti-tab-btn ti-internal" style="border-color:#ef4444; color:#ef4444;" onclick="document.getElementById('titanium-v20-modal').style.display='none'">✕ Закрыть</button>
                        </div>
                    </div>

                    <!-- Разрешительный режим Честный знак -->
                    <div class="card-panel" style="padding:14px; margin-bottom:16px; border-left:4px solid #10b981 !important;">
                        <div style="font-size:13px; font-weight:900; color:#10b981; margin-bottom:8px; text-transform:uppercase;">🔍 Сканер 2D DataMatrix — Разрешительный режим ГИС МТ «Честный Знак» (Вода / Энергетики / Напитки)</div>
                        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                            <input type="text" id="dm-scan-inp" placeholder="Наведите 2D-сканер или вставьте код DataMatrix (напр. 0104607004891221215abcXYZ)..." style="flex:1; min-width:260px;">
                            <button type="button" class="ti-tab-btn ti-internal" onclick="document.getElementById('dm-scan-inp').value='0104607004891221215KREV' + Math.floor(1000+Math.random()*9000)">🎲 Тестовая марка</button>
                            <button type="button" class="ti-tab-btn ti-internal active" style="border-color:#10b981; color:#10b981;" onclick="window.verifyDataMatrixNow()">Проверить марку в ГИС МТ [М+]</button>
                        </div>
                        <div id="dm-scan-result" style="font-size:12px; margin-top:8px; font-weight:800;"></div>
                    </div>

                    <!-- Пробивка фискального чека 54-ФЗ по заказу -->
                    <div class="card-panel" style="padding:14px; margin-bottom:16px; border-left:4px solid #38bdf8 !important;">
                        <div style="font-size:13px; font-weight:900; color:#38bdf8; margin-bottom:8px; text-transform:uppercase;">🖨 Пробивка фискального чека 54-ФЗ (АТОЛ DTO v10 JSON + Печатный чек с QR ФНС)</div>
                        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                            <select id="fiscal-order-sel" style="flex:1; min-width:260px;">${orderOpts}</select>
                            <button type="button" class="ti-tab-btn ti-internal active" style="border-color:#38bdf8; color:#38bdf8;" onclick="window.punchFiscalReceiptNow()">⚡ Фискализировать и открыть чек с QR</button>
                        </div>
                    </div>

                    <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#38bdf8;">📋 Журнал фискализированных чеков ОФД (54-ФЗ)</h3>
                    <table style="margin-bottom:16px;">
                        <tr><th>Заказ</th><th>Время</th><th>Сумма / Оплата</th><th>Реквизиты ФН / ФД / ФПД</th><th>Кассовый чек</th></tr>
                        ${recRows}
                    </table>

                    <h3 style="margin:0 0 8px; font-size:13px; text-transform:uppercase; color:#10b981;">🛡 Журнал проверенных кодов маркировки «Честный Знак» [М+]</h3>
                    <table>
                        <tr><th>Время сканирования</th><th>GTIN и Серийный номер</th><th>Номенклатура</th><th>Статус проверки ГИС МТ</th></tr>
                        ${markRows}
                    </table>
                </div>
            `;
        });
    };

    window.verifyDataMatrixNow = function() {
        const code = document.getElementById('dm-scan-inp').value.trim();
        const resEl = document.getElementById('dm-scan-result');
        fetch('/api/fiscal/verify_datamatrix', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        }).then(r => r.json()).then(d => {
            if (d.valid) {
                resEl.style.color = '#10b981';
                resEl.textContent = d.verdict + ' (GTIN: ' + d.gtin + ')';
                setTimeout(() => window.openMonolithFiscalModal(), 900);
            } else {
                resEl.style.color = '#ef4444';
                resEl.textContent = d.error || 'Ошибка проверки марки';
            }
        });
    };

    window.punchFiscalReceiptNow = function() {
        const oid = document.getElementById('fiscal-order-sel').value;
        if (!oid) return;
        fetch('/api/fiscal/punch_order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_id: oid })
        }).then(r => r.json()).then(d => {
            if (d.slip_url) window.open(d.slip_url, '_blank');
            window.openMonolithFiscalModal();
        });
    };

    window.runHotDbBackup = function(btn) {
        fetch('/api/system/create_backup', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            btn.textContent = '✅ Бэкап создан: ' + d.created_file + ' (Всего: ' + d.total_backups + ')';
            btn.style.borderColor = '#10b981';
            btn.style.color = '#10b981';
        });
    };

    // =========================================================================
    // Б. ГОЛОСОВОЙ СИНТЕЗАТОР ЭКРАНА КУХНИ KDS (/kitchen) С СОСТАВОМ РОЛЛОВ
    // =========================================================================
    let announcedOrders = new Set();
    let voiceEnabled = true;

    function speakRussianChefText(text) {
        if (!voiceEnabled || !('speechSynthesis' in window)) return;
        try {
            window.speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(text);
            u.lang = 'ru-RU';
            u.rate = 1.02;
            window.speechSynthesis.speak(u);
        } catch (e) {}
    }

    function initKdsVoicePanel() {
        if (!window.location.pathname.includes('/kitchen')) return;
        if (!document.getElementById('kds-voice-bar')) {
            const bar = document.createElement('div');
            bar.id = 'kds-voice-bar';
            bar.style.cssText = 'margin:10px 18px; padding:10px 16px; background:#121723; border:1px solid #ff6900; border-radius:12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;';
            bar.innerHTML = `
                <div>
                    <b style="color:#ff6900; font-size:14px;">🔊 ГОЛОСОВОЙ ИИ-ДИСПЕТЧЕР ЦЕХА АКТИВЕН</b>
                    <span style="font-size:12px; color:#cbd5e1; margin-left:10px;">Автоматическая озвучка состава новых чеков (стандарт 8 кусочков) и района доставки</span>
                </div>
                <div style="display:flex; gap:8px;">
                    <button type="button" class="ti-tab-btn" style="border-color:#10b981; color:#10b981;" onclick="window.announceLatestKdsOrder()">🔊 Озвучить текущий активный заказ</button>
                </div>
            `;
            document.body.prepend(bar);
        }

        window.announceLatestKdsOrder = function() {
            fetch('/api/kds/voice_feed').then(r => r.json()).then(d => {
                const list = d.orders || [];
                if (list.length > 0) {
                    speakRussianChefText(list[0].spoken_phrase);
                } else {
                    speakRussianChefText('Активных заказов на экране кухни сейчас нет. Все чеки отданы.');
                }
            });
        };

        function pollKdsVoice() {
            fetch('/api/kds/voice_feed').then(r => r.json()).then(d => {
                const list = d.orders || [];
                if (announcedOrders.size === 0 && list.length > 0) {
                    list.forEach(o => announcedOrders.add(o.id));
                    return;
                }
                list.forEach(o => {
                    if (!announcedOrders.has(o.id)) {
                        announcedOrders.add(o.id);
                        speakRussianChefText(o.spoken_phrase);
                    }
                });
            }).catch(() => {});
        }
        pollKdsVoice();
        setInterval(pollKdsVoice, 6000);
    }

    // =========================================================================
    // В. ДВУСТОРОННИЙ GPS-РАДАР КУРЬЕРОВ (/courier ↔ /map)
    // =========================================================================
    function initCourierPwaPanel() {
        if (!window.location.pathname.includes('/courier')) return;
        if (document.getElementById('courier-gps-pwa-bar')) return;

        const bar = document.createElement('div');
        bar.id = 'courier-gps-pwa-bar';
        bar.style.cssText = 'margin:12px 18px; padding:14px 18px; background:#121723; border:1px solid #10b981; border-radius:12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;';
        bar.innerHTML = `
            <div>
                <div style="font-size:14px; font-weight:900; color:#10b981;">🛰 GPS-ТЕЛЕМЕТРИЯ КУРЬЕРА (ПЕРЕДАЧА НА КАРТУ ДИСПЕТЧЕРА /map)</div>
                <div id="courier-gps-status" style="font-size:12px; color:#cbd5e1; margin-top:2px;">Координаты синхронизируются с картой г. Инта каждые 6 секунд</div>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <input type="text" id="courier-callsign" value="Экипаж #1 (Куратова)" style="width:170px; padding:6px 10px; border-radius:8px; background:#1a202e; color:#fff; border:1px solid #38bdf8;">
                <button type="button" class="ti-tab-btn" style="border-color:#10b981; color:#10b981;" onclick="window.sendCourierGpsPing('center')">📍 В Центре Инты</button>
                <button type="button" class="ti-tab-btn" style="border-color:#eab308; color:#eab308;" onclick="window.sendCourierGpsPing('west')">📍 В Западном</button>
                <button type="button" class="ti-tab-btn" style="border-color:#ef4444; color:#ef4444;" onclick="window.sendCourierGpsPing('upper')">📍 Верхняя Инта</button>
            </div>
        `;
        document.body.prepend(bar);

        window.sendCourierGpsPing = function(sector) {
            const name = document.getElementById('courier-callsign').value || 'Экипаж #1';
            let lat = 66.0328 + (Math.random() - 0.5) * 0.004;
            let lng = 60.1655 + (Math.random() - 0.5) * 0.006;
            if (sector === 'west') { lat = 66.0355; lng = 60.1310; }
            if (sector === 'upper') { lat = 66.0715; lng = 60.2640; }

            fetch('/api/omni/courier_telemetry', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ courier_name: name, lat, lng, speed_kmh: 38, status: 'В рейсе (' + sector + ')' })
            }).then(() => {
                document.getElementById('courier-gps-status').textContent = `✅ Отправлен маяк: ${name} → [${lat.toFixed(4)}, ${lng.toFixed(4)}]`;
            });
        };
    }

    // Отрисовка живых GPS-экипажей на карте /map
    let courierMarkersLayer = null;
    function initLiveCouriersOnMap() {
        if (!window.location.pathname.includes('/map')) return;
        setInterval(() => {
            if (typeof intaMap === 'undefined' || !intaMap || typeof L === 'undefined') return;
            if (!courierMarkersLayer) {
                courierMarkersLayer = L.layerGroup().addTo(intaMap);
            }
            fetch('/api/omni/courier_telemetry').then(r => r.json()).then(d => {
                courierMarkersLayer.clearLayers();
                (d.couriers || []).forEach(c => {
                    const icon = L.divIcon({
                        className: 'courier-live-pin',
                        html: `<div style="background:#38bdf8;color:#082f49;font-weight:900;font-size:11px;padding:3px 8px;border-radius:99px;border:2px solid #fff;box-shadow:0 3px 12px rgba(0,0,0,0.6);white-space:nowrap;">🚗 ${c.courier_name}</div>`,
                        iconSize: [140, 24],
                        iconAnchor: [70, 12]
                    });
                    L.marker([c.lat, c.lng], { icon })
                        .addTo(courierMarkersLayer)
                        .bindPopup(`<b>🚗 ${c.courier_name}</b><br>Статус: ${c.status}<br>Скорость: ${c.speed_kmh} км/ч<br>Обновлено: ${c.updated_at}`);
                });
            }).catch(() => {});
        }, 5000);
    }

    document.addEventListener('DOMContentLoaded', () => {
        injectMonolithHeaderButtons();
        initKdsVoicePanel();
        initCourierPwaPanel();
        initLiveCouriersOnMap();
    });
    setTimeout(() => {
        injectMonolithHeaderButtons();
        initKdsVoicePanel();
        initCourierPwaPanel();
    }, 450);
})();
