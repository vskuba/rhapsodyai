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
import {filterLoad, filterSave, htmlEscape, labelClip, labelOf, numberOf,
        selectFill, selectValueRestore, sumOf} from './util.js';

// Отбор помним между заходами: с сессиями разбираются длинными заходами, и
// сбрасывать выбранного агента на каждый F5 — терять место, где остановились.
//
// ⚠ «Между заходами» и означает долгое хранилище (`filterSave`) — то, на
// котором это стояло раньше, живёт в одной вкладке браузера, и обещанная здесь
// память кончалась на открытии «Сессий» в новой вкладке.
const AGENT_STORE_PREFIX = 'agent_';

// Типы записей, выбранные по умолчанию: диалог без служебной обвязки. Служебные
// (`llm-request` и прочие) включают руками — они нужны вопросу «что уехало в
// модель», а не вопросу «о чём говорили».
const AGENT_KIND_DEFAULT = ['user-prompt', 'response-final'];

// Сколько знаков имени агента влезает в строку списка рядом с датой, огрызком
// uuid и счётчиком. Посчитано по ширине поля (`css/session.css`): шире —
// обрежет сам `<select>`, и пропадёт хвост строки, а не имя.
const AGENT_NAME_MAX = 28;

// Номер последнего начатого запроса; ответ не своего номера выбрасывается.
// ⚠ За время ответа отбор успевают сменить дважды, и без счётчика список
// остаётся от первого запроса, а лента — от второго. Довод подробнее — в
// соседней вкладке (`chat.js`).
let agentRequest = 0;

const el = {};
const state = {
    // Пары «агент + пользователь» со счётом сессий — из них строятся отборы.
    //
    // ⚠⚠ Это НЕ список сессий. Прежде отборы собирались из полной выдачи
    // `/session/list`, но список стал страничным: собери их из страницы — и
    // в отборе останутся только те, кто говорил последним. Пар два десятка,
    // сессий двадцать восемь тысяч; спрашивать надо то, что нужно.
    pairs: [],
    // Сессий всего под правами — честное число от сервера, не сумма пар.
    sessionsTotal: 0,
    agents: {},
    users: {},
    // Сообщения открытой сессии: тип записи отбирается на клиенте, и
    // перевыбор не должен стоить ещё одного запроса.
    messages: [],
    // Страница списка: номер, сколько всего страниц и сессий под отбором.
    page: 1,
    pages: 1,
    total: 0,
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
    el.pagePrev = document.getElementById('agentSessionPrev');
    el.pageNext = document.getElementById('agentSessionNext');
    el.pageInfo = document.getElementById('agentSessionPageInfo');

    try {
        await Promise.all([dictionariesLoad(), kindsLoad()]);
        filtersBind();
        await sessionsLoad();
    } catch (e) {
        el.stream.innerHTML =
            `<div class="placeholder">Ошибка загрузки: ${htmlEscape(e.message)}</div>`;
    }
}

// ===================== Справочники и отборы =====================

async function dictionariesLoad() {
    const [agents, users, pairs] = await Promise.all([
        fetch('/agent/list').then(r => r.json()).catch(() => ({})),
        // ⚠ Не падаем без пользователей: `/api/users` требует своего права, и
        // роль без него должна видеть сессии, просто без имён в отборе.
        fetch('/api/users').then(r => r.json()).catch(() => ({})),
        fetch('/session/agent/list').then(r => r.json()),
    ]);

    (agents.result || []).forEach(one => {
        state.agents[one.id] = one;
    });
    ((users.result || {}).users || []).forEach(one => {
        state.users[one.id] = one;
    });
    state.pairs = pairs.result || [];
    // ⚠ Не сумма пар: сессия со строками под разными парами сложилась бы
    // дважды, и «всего» разошлось бы с числом под списком.
    state.sessionsTotal = pairs.total || 0;

    agentFill();
    userFill();

    selectValueRestore(el.agent, filterLoad(`${AGENT_STORE_PREFIX}agent_id`));
    // Список пользователей зависит от выбранного агента — перезаполняем после
    // восстановления, иначе запомненный агент сузил бы его только со второго
    // раза.
    userFill();
    selectValueRestore(el.user, filterLoad(`${AGENT_STORE_PREFIX}user_id`));

    const limitSaved = filterLoad(`${AGENT_STORE_PREFIX}limit`);

    selectValueRestore(el.limit, limitSaved);
}

function agentFill() {
    // ⚠ «Все агенты» первым вариантом — обязательно. Прежняя страница
    // открывалась на первом агенте и вернуться к полной выдаче не давала
    // вовсе: такого варианта в списке не было.
    selectFill(el.agent, [
        {value: '', text: `Все агенты (${state.sessionsTotal})`},
        ...entriesOf(state.pairs, 'agent_id', state.agents),
    ]);
}

function userFill() {
    const agentId = numberOf(el.agent.value);
    // Пользователи сужаются выбранным агентом, а агенты пользователем — нет.
    // Сужение в обе стороны выглядит разумным ровно до первого применения:
    // каждый отбор переписывает соседний, и вернуть «всех» становится нечем.
    const scoped = agentId
        ? state.pairs.filter(one => one.agent_id === agentId)
        : state.pairs;

    selectFill(el.user, [
        {value: '', text: `Все пользователи (${sumOf(scoped, 'sessions')})`},
        ...entriesOf(scoped, 'user_id', state.users),
    ]);
}

async function kindsLoad() {
    const data = await fetch('/session/kind_type/list').then(r => r.json());
    const saved = JSON.parse(filterLoad(`${AGENT_STORE_PREFIX}kinds`) || 'null');

    el.kind.innerHTML = '';
    (data.result || []).forEach(kind => {
        const option = new Option(kind, kind);

        option.selected = saved ? saved.includes(kind)
            : AGENT_KIND_DEFAULT.includes(kind);
        el.kind.add(option);
    });
}

function filtersBind() {
    // ⚠ Смена отбора возвращает на первую страницу. Иначе «страница 40» под
    // новым отбором либо пуста, либо показывает чужую середину — и то и
    // другое читается как «фильтр сломался».
    el.agent.onchange = async () => {
        filterSave(`${AGENT_STORE_PREFIX}agent_id`, el.agent.value);
        userFill();
        filterSave(`${AGENT_STORE_PREFIX}user_id`, el.user.value);
        await sessionsLoad(1);
    };

    el.user.onchange = async () => {
        filterSave(`${AGENT_STORE_PREFIX}user_id`, el.user.value);
        await sessionsLoad(1);
    };

    el.pagePrev.onclick = () => sessionsLoad(state.page - 1);
    el.pageNext.onclick = () => sessionsLoad(state.page + 1);

    el.kind.onchange = () => {
        filterSave(`${AGENT_STORE_PREFIX}kinds`,
            JSON.stringify(kindsSelected()));
        messagesRender();
    };

    el.limit.onchange = () => {
        filterSave(`${AGENT_STORE_PREFIX}limit`, el.limit.value);

        if (el.list.value) messagesLoad(el.list.value);
    };

    el.list.onchange = () => messagesLoad(el.list.value);
    el.remove.onclick = sessionRemove;
}

// ===================== Сессии =====================

async function sessionsLoad(page = 1) {
    const request = ++agentRequest;

    el.list.innerHTML = '<option>Загрузка...</option>';

    const data = await postData('/session/list', {
        agent_id: numberOf(el.agent.value) || null,
        user_id: numberOf(el.user.value) || null,
        page: Math.max(1, page),
    });

    if (request !== agentRequest) return;

    state.page = data.page || 1;
    state.pages = data.pages || 1;
    state.total = data.total || 0;
    pagerShow();

    await sessionsShow(data.result || []);
}

/** Листалка под списком: где мы и сколько всего. */
function pagerShow() {
    // Всего сессий, а не страниц, — главное число: по нему видно, насколько
    // узок отбор. Номер страницы рядом отвечает «куда я забрёл».
    el.pageInfo.textContent = state.total
        ? `${state.page} / ${state.pages} · сессий ${state.total}`
        : '—';
    el.pagePrev.disabled = state.page <= 1;
    el.pageNext.disabled = state.page >= state.pages;
}

/** Показать страницу списка и открыть верхнюю сессию. */
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
        // Остаёмся на той же странице: удалили одну из пятидесяти, и
        // прыжок в начало списка потерял бы место, где человек работал.
        await sessionsLoad(state.page);
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

/** Варианты отбора «запись (сколько сессий)», отсортированные по названию.
 *
 * ⚠ Складывает `sessions` строк-пар, а не считает сами строки: пара «агент +
 * пользователь» одна, а сессий за ней могут быть сотни.
 */
function entriesOf(pairs, field, dictionary) {
    const counts = {};

    pairs.forEach(one => {
        if (one[field]) {
            counts[one[field]] = (counts[one[field]] || 0)
                + Number(one.sessions || 0);
        }
    });

    return Object.keys(counts)
        .map(id => ({
            value: id,
            text: `${labelOf(dictionary[id], id)} (${counts[id]})`,
        }))
        .sort((a, b) => a.text.localeCompare(b.text));
}
