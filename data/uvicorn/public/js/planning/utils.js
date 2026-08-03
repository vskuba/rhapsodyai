// Shared helpers — tz formatting and HTML escaping
// TZ offset injected by template: window.PLANNING_TZ_OFFSET

const TZ_OFFSET_HOURS = (() => {
    const n = parseFloat(window.PLANNING_TZ_OFFSET);
    return isNaN(n) ? 0 : n;
})();

function tzFmt(dtStr, withSeconds) {
    if (!dtStr) return '—';
    const utcStr = dtStr.includes('T') ? dtStr : dtStr.replace(' ', 'T');
    const d = new Date(utcStr + (utcStr.endsWith('Z') ? '' : 'Z'));
    if (isNaN(d)) return dtStr.slice(0, withSeconds ? 19 : 16);
    const offsetMs = TZ_OFFSET_HOURS * 3600000;
    const local = new Date(d.getTime() + offsetMs);
    const pad = n => String(n).padStart(2, '0');
    const base = `${local.getUTCFullYear()}-${pad(local.getUTCMonth()+1)}-${pad(local.getUTCDate())} ${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}`;
    return withSeconds ? base + ':' + pad(local.getUTCSeconds()) : base;
}

function escHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escAttr(s) { return escHtml(s); }

const _TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i',
    'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
    'у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'',
    'э':'e','ю':'yu','я':'ya',
    'і':'i','ї':'yi','є':'ye','ґ':'g',
};
function translitLat(text) {
    return String(text || '').split('').map(c => {
        const lo = c.toLowerCase();
        if (_TRANSLIT[lo] !== undefined) {
            const t = _TRANSLIT[lo];
            return (c === c.toUpperCase() && c !== lo) ? t.charAt(0).toUpperCase() + t.slice(1) : t;
        }
        return c;
    }).join('').replace(/[^a-zA-Z0-9_\-]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
}
