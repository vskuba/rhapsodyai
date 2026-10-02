// Вкладка «Агенты»: журнал вызова LLM (`agent_session`).
//
// Строка здесь — не реплика, а запись вызова: промпт, ответ, обращение к
// инструменту, потраченные токены. Поэтому и отборы такие: агент,
// пользователь, тип записи.
//
// ⚠ Отбора по собеседнику тут нет и быть не может: столбец
// `agent_session.companion_id` снят миграцией, а фильтр на странице жил ещё
// месяцами после и не фильтровал ничего — выдача этого поля не возвращала, а
// тело запроса его не знало. Собеседник — на вкладке «Чат» (`chat.js`).

import {postData, deleteData} from '../api.js';
import {showNotification} from '../notification.js';
import {htmlEscape, labelClip, labelOf, selectFill, selectValueRestore} from './util.js';

// Отбор помним между заходами: с сессиями разбираются длинными заходами, и
// сбрасывать выбранного агента на каждый F5 — терять место, где остановились.
const AGENT_STORE_PREFIX = 'session_agent_';

// Типы записей, выбранные по умолчанию: диалог без служебной обвязки. Служебные
// (`llm-request` и прочие) включают руками — они нужны вопросу «что уехало в
// модель», а не вопросу «о чём говорили».
const AGENT_KIND_DEFAULT = ['user-prompt', 'response-final'];

// Сколько знаков имени агента влезает в строку списка рядом с датой, огрызком
// uuid и счётчиком. Посчитано по ширине поля (`css/session.css`): шире —
// обрежет сам `<select>`, и пропадёт хвост строки, а не имя.
const AGENT_NAME_MAX = 28;

// Номер последнего начатого запроса; ответ не своего номера выбрасывается.
// ⚠ Полная выдача списка — 780 КБ и доли секунды: за это время отбор успевают
// сменить дважды, и без счётчика список остаётся от первого запроса, а лента —
// от второго. Довод подробнее — в соседней вкладке (`chat.js`).
let agentRequest = 0;

const el = {};
const state = {
    // Полная выборка сессий — из неё строятся оба отбора со счётчиками.
    //
    // ⚠ Отфильтрованным результатом её перезаписывать нельзя: выбрав агента,
    // мы бы потеряли из списка всех остальных и вернуться к ним стало бы
    // нечем. На этом уже спотыкались — пустел список собеседников.
    sessions: [],
    agents: {},
    users: {},
    // Сообщения открытой сессии: тип записи отбирается на клиенте, и
    // перевыбор не должен стоить ещё одного запроса.
    messages: [],
};

export async function sessionAgentInit() {
    el.agent = document.getElementById('agentSessionAgent');
    el.user = document.getElementById('agentSessionUser');
    el.kind = document.getElementById('agentSessionKind');
    el.limit = document.getElementById('agentSessionLimit');
    el.list = document.getElementById('agentSessionSelect');
    el.remove = document.getElementById('agentSessionDelete');
    el.title = document.getElementById('agentSessionTitle');
    el.stream = document.getElementById('agentSessionStream');

    try {
        await Promise.all([dictionariesLoad(), kindsLoad()]);
        filtersBind();

        // ⚠ Без отбора список сессий — это та самая полная выборка, которую
        // уже принёс `dictionariesLoad`: второй такой запрос стоил бы ещё
        // 780 КБ на каждый заход. Прежняя страница платила их всегда — и
        // ровно за тот же ответ.
        if (filtersEmpty()) sessionsShow(state.sessions);
        else await sessionsLoad();
    } catch (e) {
        el.stream.innerHTML =
            `<div class="placeholder">Ошибка загрузки: ${htmlEscape(e.message)}</div>`;
    }
}

// ===================== Справочники и отборы =====================

async function dictionariesLoad() {
    const [agents, users, sessions] = await Promise.all([
        fetch('/agent/list').then(r => r.json()).catch(() => ({})),
        // ⚠ Не падаем без пользователей: `/user/list` требует своего права, и
        // роль без него должна видеть сессии, просто без имён в отборе.
        fetch('/user/list').then(r => r.json()).catch(() => ({})),
        postData('/session/list', {}),
    ]);

    (agents.result || []).forEach(one => {
        state.agents[one.id] = one;
    });
    (users.result || []).forEach(one => {
        state.users[one.id] = one;
    });
    state.sessions = sessions.result || [];

    agentFill();
    userFill();

    selectValueRestore(el.agent, sessionStorage.getItem(`${AGENT_STORE_PREFIX}agent_id`));
    // Список пользователей зависит от выбранного агента — перезаполняем после
    // восстановления, иначе запомненный агент сузил бы его только со второго
    // раза.
    userFill();
    selectValueRestore(el.user, sessionStorage.getItem(`${AGENT_STORE_PREFIX}user_id`));

    const limitSaved = sessionStorage.getItem(`${AGENT_STORE_PREFIX}limit`);

    selectValueRestore(el.limit, limitSaved);
}

function agentFill() {
    // ⚠ «Все агенты» первым вариантом — обязательно. Прежняя страница
    // открывалась на первом агенте и вернуться к полной выдаче не давала
    // вовсе: такого варианта в списке не было.
    selectFill(el.agent, [
        {value: '', text: `Все агенты (${state.sessions.length})`},
        ...entriesOf(state.sessions, 'agent_id', state.agents),
    ]);
}

function userFill() {
    const agentId = numberOf(el.agent.value);
    // Пользователи сужаются выбранным агентом, а агенты пользователем — нет.
    // Сужение в обе стороны выглядит разумным ровно до первого применения:
    // каждый отбор переписывает соседний, и вернуть «всех» становится нечем.
    const scoped = agentId
        ? state.sessions.filter(one => one.agent_id === agentId)
        : state.sessions;

    selectFill(el.user, [
        {value: '', text: `Все пользователи (${scoped.length})`},
        ...entriesOf(scoped, 'user_id', state.users),
    ]);
}

async function kindsLoad() {
    const data = await fetch('/session/kind_type/list').then(r => r.json());
    const saved = JSON.parse(sessionStorage.getItem(`${AGENT_STORE_PREFIX}kinds`) || 'null');

    el.kind.innerHTML = '';
    (data.result || []).forEach(kind => {
        const option = new Option(kind, kind);

        option.selected = saved ? saved.includes(kind)
            : AGENT_KIND_DEFAULT.includes(kind);
        el.kind.add(option);
    });
}

function filtersBind() {
    el.agent.onchange = async () => {
        sessionStorage.setItem(`${AGENT_STORE_PREFIX}agent_id`, el.agent.value);
        userFill();
        sessionStorage.setItem(`${AGENT_STORE_PREFIX}user_id`, el.user.value);
        await sessionsLoad();
    };

    el.user.onchange = async () => {
        sessionStorage.setItem(`${AGENT_STORE_PREFIX}user_id`, el.user.value);
        await sessionsLoad();
    };

    el.kind.onchange = () => {
        sessionStorage.setItem(`${AGENT_STORE_PREFIX}kinds`,
            JSON.stringify(kindsSelected()));
        messagesRender();
    };

    el.limit.onchange = () => {
        sessionStorage.setItem(`${AGENT_STORE_PREFIX}limit`, el.limit.value);

        if (el.list.value) messagesLoad(el.list.value);
    };

    el.list.onchange = () => messagesLoad(el.list.value);
    el.remove.onclick = sessionRemove;
}

// ===================== Сессии =====================

async function sessionsLoad() {
    const request = ++agentRequest;

    el.list.innerHTML = '<option>Загрузка...</option>';

    const data = await postData('/session/list', {
        agent_id: numberOf(el.agent.value) || null,
        user_id: numberOf(el.user.value) || null,
    });

    if (request !== agentRequest) return;

    await sessionsShow(data.result || []);
}

/** Показать список сессий и открыть верхнюю. */
async function sessionsShow(sessions) {
    el.list.innerHTML = '';
    sessions.forEach(one => {
        // Имя агента в строке — иначе список под отбором «Все агенты» это
        // столбец одинаковых огрызков uuid, по которому не выбрать ничего.
        //
        // ⚠ Огрызок uuid остаётся и после имени не лишний: у одного агента
        // бывают сотни сессий (567 у «Task: пересказ шага»), и без него
        // соседние строки различала бы только минута.
        //
        // ⚠ Имя обрезается явно (`AGENT_NAME_MAX`), потому что счётчик стоит
        // ПОСЛЕ него: обрежь строку сам `<select>` — и у длинного имени
        // пропало бы именно число реплик, ради которого в строку смотрят.
        const option = new Option(
            `${fmtTz(one.last_message_at)} ${one.session_uuid.substring(0, 8)}`
            + ` ${labelClip(labelOf(state.agents[one.agent_id], one.agent_id),
                            AGENT_NAME_MAX)}`
            + ` 💬${one.dialog_count ?? 0}`,
            one.session_uuid);

        // Полное описание — в подсказке: в строке списка 300 пикселей, а
        // сказать надо и агента, и пользователя, и объём журнала.
        option.title = [
            `Агент: ${labelOf(state.agents[one.agent_id], one.agent_id)}`,
            `Пользователь: ${labelOf(state.users[one.user_id], one.user_id)}`,
            `Реплик: ${one.dialog_count ?? 0}, записей журнала: ${one.msg_count}`,
            one.session_uuid,
        ].join('\n');
        el.list.add(option);
    });

    if (!el.list.options.length) {
        el.remove.disabled = true;
        el.title.textContent = 'Нет сессий под этот отбор';
        el.stream.innerHTML = '<div class="placeholder">Нет сессий</div>';
        state.messages = [];

        return;
    }

    // Сервер отдаёт свежие первыми — открываем верхнюю.
    el.list.selectedIndex = 0;
    el.remove.disabled = false;
    await messagesLoad(el.list.value);
}

async function sessionRemove() {
    const uuid = el.list.value;

    if (!uuid) return;

    const label = el.list.options[el.list.selectedIndex]?.text || uuid;

    if (!confirm(`Удалить сессию "${label}"?`
        + ' Вся переписка будет удалена без возможности восстановления.')) {
        return;
    }

    el.remove.disabled = true;

    try {
        await deleteData(`/session/${uuid}`);
        showNotification('Сессия удалена', 'success');
        await sessionsLoad();
    } catch (e) {
        showNotification(`Ошибка удаления: ${e.message}`, 'error');
        el.remove.disabled = false;
    }
}

// ===================== Лента сообщений =====================

async function messagesLoad(uuid) {
    const request = ++agentRequest;

    el.title.textContent = `Сессия: ${uuid}`;
    el.stream.innerHTML = '<div class="placeholder">Загрузка...</div>';

    try {
        const data = await postData('/session/messages', {
            session_uuid: uuid,
            limit: parseInt(el.limit.value, 10),
        });

        if (request !== agentRequest) return;

        state.messages = data.result || [];
        messagesRender();
    } catch (e) {
        el.stream.innerHTML =
            `<div class="placeholder">Ошибка загрузки: ${htmlEscape(e.message)}</div>`;
    }
}

function messagesRender() {
    const kinds = kindsSelected();
    // Пустой отбор — это «все типы», а не «ничего». Снятая последняя галка
    // иначе отвечала бы «нет сообщений» на сессию, в которой они есть.
    const shown = kinds.length
        ? state.messages.filter(one => kinds.includes(one.kind_type))
        : state.messages;

    // ⚠ Сколько записей скрыто — видно всегда. Предел считается по РЕПЛИКАМ
    // (`/session/messages`), и выбрав один служебный тип, человек получает
    // обвязку только последних N реплик. Без этой строки картина читалась бы
    // как «в сессии всего три записи».
    el.title.innerHTML = `Сессия: ${htmlEscape(el.list.value)}`
        + `<span class="detail-header-note">показано ${shown.length}`
        + ` из ${state.messages.length} записей</span>`;

    if (!shown.length) {
        el.stream.innerHTML = '<div class="placeholder">Нет записей выбранного типа</div>';

        return;
    }

    el.stream.innerHTML = shown.map(one => `
        <div class="admin-msg-box">
            <div class="chips-container">
                <span class="chip role-${htmlEscape(one.role)}">${htmlEscape(one.role)}</span>
                <span class="chip chip-kind">${htmlEscape(one.kind_type)}</span>
                ${one.llm_name ? `<span class="chip chip-llm">${htmlEscape(one.llm_name)}</span>` : ''}
                ${one.token ? `<span class="chip chip-token">Токены: ${htmlEscape(one.token)}</span>` : ''}
                <span class="chip chip-request-id">${htmlEscape(one.request_uuid)}</span>
                <span class="chip-date">${fmtTz(one.created_at)}</span>
            </div>
            <div class="admin-msg-content">${htmlEscape(one.content)}</div>
        </div>
    `).join('');
}

// ===================== Мелочь =====================

function kindsSelected() {
    return [...el.kind.selectedOptions].map(one => one.value);
}

function filtersEmpty() {
    return !numberOf(el.agent.value) && !numberOf(el.user.value);
}

function numberOf(value) {
    const number = parseInt(value, 10);

    return isNaN(number) ? 0 : number;
}

/** Варианты отбора «запись (сколько сессий)», отсортированные по названию. */
function entriesOf(sessions, field, dictionary) {
    const counts = {};

    sessions.forEach(one => {
        if (one[field]) counts[one[field]] = (counts[one[field]] || 0) + 1;
    });

    return Object.keys(counts)
        .map(id => ({
            value: id,
            text: `${labelOf(dictionary[id], id)} (${counts[id]})`,
        }))
        .sort((a, b) => a.text.localeCompare(b.text));
}
