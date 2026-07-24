import { getData, deleteData } from '/static/js/api.js';
import { state } from './state.js';
import { escapeHtml, confirmDialog } from './utils.js';

const eventsTab = document.getElementById('tab-events');

export async function loadEvents() {
    try {
        const res = await getData('/events');
        state.eventsTimezone = res.timezone || '+0';
        renderEvents(res.result || []);
    } catch (err) {
        eventsTab.innerHTML = `<div class="denied-state">⚠️ Не удалось загрузить события: ${escapeHtml(err.message || 'Ошибка')}</div>`;
    }
}

function renderEvents(events) {
    const eventsHtml = events.length
        ? events.map(e => {
            const summary = formatEventSummary(e.type, e.payload);
            const timeStr = formatEventTime(e.created_at, state.eventsTimezone);
            return `
            <div class="event-row">
                <span class="event-time">${escapeHtml(timeStr)}</span>
                <span class="event-type">${escapeHtml(e.type || 'system')}</span>
                ${summary ? `<div class="event-summary">${escapeHtml(summary)}</div>` : ''}
            </div>`;
        }).join('')
        : '<div class="empty-state">Событий пока нет</div>';

    eventsTab.innerHTML = `
        <div class="panel-title" style="display:flex;align-items:center;justify-content:space-between;">
            <span>Последние события</span>
            <button id="clearEventsBtn" style="background:none;border:none;font-size:18px;cursor:pointer;padding:0 2px;color:#e74c3c;" title="Очистить события">🗑</button>
        </div>
        <div class="panel-card">${eventsHtml}</div>
    `;

    document.getElementById('clearEventsBtn').addEventListener('click', async () => {
        const confirmed = await confirmDialog('Удалить все события?');
        if (!confirmed) return;
        try {
            await deleteData('/events');
            renderEvents([]);
        } catch {
            eventsTab.insertAdjacentHTML('beforeend', '<div class="denied-state">⚠️ Не удалось очистить события</div>');
        }
    });
}

function formatEventTime(utcDateStr, tzOffset) {
    if (!utcDateStr) return '';
    const match = String(tzOffset || '0').match(/^([+-]?)(\d+)(?::(\d+))?$/);
    if (!match) return String(utcDateStr);
    const sign = match[1] === '-' ? -1 : 1;
    const offsetMin = sign * (parseInt(match[2], 10) * 60 + parseInt(match[3] || '0', 10));
    const date = new Date(String(utcDateStr).replace(' ', 'T') + 'Z');
    if (isNaN(date.getTime())) return String(utcDateStr);
    const local = new Date(date.getTime() + offsetMin * 60000);
    const pad = n => String(n).padStart(2, '0');
    return `${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())} ${pad(local.getUTCDate())}.${pad(local.getUTCMonth() + 1)}`;
}

const EVENT_FORMATTERS = {
    github(p) {
        const ev = p.event || '';
        const branch = p.branch ? `#${p.branch}` : '';
        const commit = p.commit ? p.commit.slice(0, 7) : '';
        const actor = p.actor ? `@${p.actor}` : '';
        if (ev === 'deploy.started') return `🚀 deploy.started ${branch} ${commit} ${actor}`.trim();
        if (ev === 'deploy.finished') {
            const icon = p.status === 'success' ? '✅' : '❌';
            return `${icon} deploy.finished · ${p.status || ''} ${branch} ${commit}`.trim();
        }
        return ev;
    },
    system(p) {
        const ev = p.event_type || 'event';
        const who = p.username ? `${p.username} (${p.role || '?'})` : (p.role || '');
        return `👤 ${ev} · ${who}`.trim();
    },
    claude_session(p) {
        return `🖥 ${[p.event_type, p.project_label, p.role].filter(Boolean).join(' · ')}`;
    },
    agent(p) {
        return `🤖 ${[p.event_type, p.agent_name].filter(Boolean).join(' · ')}`;
    },
    llm(p) {
        const tokens = (p.tokens_input || p.tokens_output)
            ? `↑${p.tokens_input || 0} ↓${p.tokens_output || 0}` : '';
        return `💬 ${[p.event_type, p.model, tokens].filter(Boolean).join(' · ')}`;
    },
};

function formatEventSummary(type, payloadRaw) {
    let p = {};
    try { p = JSON.parse(payloadRaw || '{}'); } catch { return ''; }
    const fmt = EVENT_FORMATTERS[type] || (!type && p.username ? EVENT_FORMATTERS.system : null);
    return fmt ? fmt(p) : '';
}
