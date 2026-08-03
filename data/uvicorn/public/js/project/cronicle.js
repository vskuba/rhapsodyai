// Cronicle schedule — next-run calculations

let _cronicleSchedule = {};

async function loadCronicleSchedule() {
    try {
        const r = await fetch('/planning/cronicle/schedule');
        const d = await r.json();
        _cronicleSchedule = d.result || {};
    } catch(e) {}
}

// Returns ms timestamp of next Cronicle run for phase, or null.
// Schedule minutes are 0-59 (within the hour); hours=[] means every hour.
function cronicleNextMs(phase) {
    const sched = _cronicleSchedule[phase];
    if (!sched) return null;
    const mins = sched.minutes || [];
    const hrs = sched.hours && sched.hours.length ? sched.hours : null;
    if (!mins.length) return null;
    const now = new Date();
    const allowedHours = hrs || Array.from({length: 24}, (_, i) => i);
    let best = null;
    for (let dayOffset = 0; dayOffset <= 1; dayOffset++) {
        for (const h of allowedHours) {
            for (const m of mins) {
                const c = new Date(now);
                c.setUTCDate(c.getUTCDate() + dayOffset);
                c.setUTCHours(h, m, 0, 0);
                if (c > now && (!best || c < best)) best = c;
            }
        }
        if (best) break;
    }
    return best ? best.getTime() : null;
}

function cronicleNextLabel(phase) {
    const ms = cronicleNextMs(phase);
    if (ms === null) return null;
    const minsUntil = Math.round((ms - Date.now()) / 60000);
    const nextStr = tzFmt(new Date(ms).toISOString().replace('T', ' ').slice(0, 19));
    if (minsUntil <= 0) return { label: `→ ${nextStr} (сейчас)`, imminent: true };
    return { label: `→ ${nextStr} (через ${minsUntil} мин)`, imminent: minsUntil <= 2 };
}
