
window.INTA_ZONES = {};

window.getDishPhoto = function(name, category, dbImg) {
    let clean = (dbImg || '').trim();
    if (clean.length > 3 && !clean.includes('none') && !clean.includes('placeholder') && clean !== 'null') {
        if (!clean.startsWith('http') && !clean.startsWith('/')) {
            return '/static/uploads/' + clean;
        }
        return clean;
    }
    let n = ((name || '') + ' ' + (category || '')).toLowerCase();
    if(n.includes('филадельф')) return 'https://images.unsplash.com/photo-1579871494447-9811cf80d66c?auto=format&fit=crop&w=600&q=80';
    if(n.includes('калифорн')) return 'https://images.unsplash.com/photo-1617196034796-73dfa7b1fd56?auto=format&fit=crop&w=600&q=80';
    if(n.includes('запеч')) return 'https://images.unsplash.com/photo-1611143669185-af224c5e3252?auto=format&fit=crop&w=600&q=80';
    if(n.includes('темпур') || n.includes('жарен') || n.includes('кранч')) return 'https://images.unsplash.com/photo-1553621042-f6e147245754?auto=format&fit=crop&w=600&q=80';
    if(n.includes('сет') || n.includes('набор')) return 'https://images.unsplash.com/photo-1562802378-063ec186a863?auto=format&fit=crop&w=600&q=80';
    if(n.includes('вок') || n.includes('wok') || n.includes('лапш') || n.includes('удон') || n.includes('соба') || n.includes('тяхан')) return 'https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=600&q=80';
    if(n.includes('суп') || n.includes('том ям') || n.includes('мисо') || n.includes('рамен') || n.includes('фо бо')) return 'https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80';
    return 'https://images.unsplash.com/photo-1579584425555-c3ce17fd4351?auto=format&fit=crop&w=600&q=80';
};

// Приятный звуковой сигнал нового заказа (Web Audio API без внешних mp3)
window.playNewOrderBell = function() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const playTone = (freq, start, dur) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
            gain.gain.setValueAtTime(0.18, ctx.currentTime + start);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(ctx.currentTime + start);
            osc.stop(ctx.currentTime + start + dur);
        };
        playTone(659.25, 0, 0.18);
        playTone(880.00, 0.16, 0.35);
    } catch(e) {}
};
