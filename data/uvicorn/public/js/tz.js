// Global timezone utility loaded by base.html.
// Call await loadTz() in page init, then use fmtTz(value) for UTC date strings.
(function () {
    window.APP_TZ_OFFSET = 0; // minutes

    window.loadTz = async function () {
        try {
            const r = await fetch('/api/setting');
            const data = await r.json();
            const row = (data.result?.settings || []).find(s => s.key === 'timezone' && !s.node_id);
            if (row) {
                const m = String(row.value || '').match(/([+-]?\d+)/);
                if (m) window.APP_TZ_OFFSET = parseInt(m[1], 10) * 60;
            }
        } catch {}
    };

    window.fmtTz = function (value, withSeconds) {
        if (!value) return '—';
        const raw = String(value).replace(' ', 'T');
        const d = new Date(raw.endsWith('Z') ? raw : raw + 'Z');
        if (isNaN(d.getTime())) return String(value).slice(0, withSeconds ? 19 : 16);
        const local = new Date(d.getTime() + window.APP_TZ_OFFSET * 60000);
        const pad = n => String(n).padStart(2, '0');
        const base = `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())} ${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}`;
        return withSeconds ? base + ':' + pad(local.getUTCSeconds()) : base;
    };
})();
