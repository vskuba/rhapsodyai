/**
 * Вкладка «Topic & Action» страницы Workflow: группы тем и темы внутри них.
 *
 * Группа — свод тем одного рода. Тема — запись внутри неё: метки-иглы, два
 * порога, вопросы и один текст инструкции.
 *
 * ⚠ Имена в коде остались `branch*` (файл, классы, ручки): переименование
 * видимых подписей и переименование кода — разные работы, и вторая трогает
 * ручки, которые зовёт ещё и шаг. Здесь сделана первая.
 *
 * ## Устройство страницы
 *
 * Слева — **дерево**: ветки, под каждой её темы локтями. Справа — настройки
 * **ровно того, что выбрано**: ветка или тема, не оба сразу.
 *
 * ⚠ Прежде темы стояли списком внутри карточки ветки, и выходило двойное
 * показывание: та же тема и в списке, и в форме правки под ним. Карточка росла
 * вниз, а выбранного места в ней было не найти.
 *
 * ⚠ Ветки принадлежат **ноде**, а не отдельному workflow: их читает шаг `branch`
 * любого workflow этой ноды. Поэтому список берётся по ноде, выбранной в левой
 * карусели страницы.
 *
 * ⚠⚠ Правил выбора темы здесь нет и быть не должно: их считает движок
 * (`src/ai/ai_workflow_topic_action.py`). Своя копия арифметики на странице разошлась
 * бы с ним на первой же правке.
 *
 * Устройство слоя — `.claude/docs/workflow_topic.md`.
 */

import {postData} from '../api.js';
import {showNotification} from '/static/js/notification.js';
import {textModalIcon} from './text-modal.js';
import {textTranslateGuess} from './text-translate.js';
import {topicRoadsLoad} from './topic-roads.js';

const PAGE_SIZE = 20;

// Языки перевода меток — те же три и в том же порядке, что у промптов
// (`text-translate.js`): английский первым, остальные два на обратную дорогу.
const TAG_LANGS = [
    {code: 'en', flag: '🇬🇧', word: 'английский'},
    {code: 'uk', flag: '🇺🇦', word: 'украинский'},
    {code: 'ru', flag: '🇷🇺', word: 'русский'},
];

const topicState = {
    nodeId: null,
    branches: [],
    topicsByBranch: {},
    page: 0,
    // Что открыто справа: `{kind: 'branch'|'topic'|null, id}`. Одно на двоих —
    // выбрано всегда что-то одно, и второго показывать нечего.
    picked: {kind: null, id: null},
    // Метки открытой темы, уже приведённые. Живут отдельно от карточки: поле
    // ввода перерисовывать нельзя, иначе уедет фокус.
    tags: [],
    // Вопросы открытой темы: `{question, is_enabled}` в порядке показа, он же
    // порядок номеров в промпте. Живут здесь по той же причине, что метки.
    questions: [],
};

async function topicApi(url, options) {
    const response = await fetch(url, options);
    let body = null;
    try {
        body = await response.json();
    } catch (e) {
        body = null;
    }
    if (!response.ok) {
        throw new Error((body && (body.detail || body.message)) || response.statusText);
    }
    return body;
}

function esc(text) {
    return String(text == null ? '' : text).replace(/[&<>"]/g, c => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]
    ));
}

function tagList(raw) {
    return String(raw || '').split(',').map(t => t.trim()).filter(Boolean);
}

/**
 * «2 темы», а не «2 тем».
 *
 * ⚠ Число рядом со словом читают глазами, и неверная форма видна сразу — а в
 * коде её не видно вовсе.
 */
function plural(count, one, few, many) {
    const tens = count % 100;
    if (tens >= 11 && tens <= 14) return `${count} ${many}`;
    const last = count % 10;
    if (last === 1) return `${count} ${one}`;
    if (last >= 2 && last <= 4) return `${count} ${few}`;
    return `${count} ${many}`;
}

function topicsOf(branchId) {
    return topicState.topicsByBranch[String(branchId)] || [];
}

function groupCurrent() {
    // ⚠⚠ У НОВОЙ темы номера ещё нет, и спросить её о группе нельзя: в списке
    // её не существует. Группу помнит сам выбор (`picked.groupId`) — её кладёт
    // тот, кто нажал «+ Тема», и только она отвечает, куда тему заводить.
    //
    // Пока этого поля не было, заведение падало на ровном месте: `groupCurrent()`
    // отдавал `null`, а `topicSave` читал у него `id` — «can't access property
    // "id", branch is null». Поймано на проде человеком.
    const picked = topicState.picked;
    const id = picked.kind === 'branch' ? picked.id
        : (topicCurrent() || {}).topic_group_id ?? picked.groupId;
    return topicState.branches.find(b => String(b.id) === String(id)) || null;
}

function topicCurrent() {
    if (topicState.picked.kind !== 'topic') return null;
    for (const rows of Object.values(topicState.topicsByBranch)) {
        const found = rows.find(t => String(t.id) === String(topicState.picked.id));
        if (found) return found;
    }
    return null;
}

/**
 * Открыть вкладку: загрузить ветки выбранной ноды и нарисовать дерево.
 *
 * @param {object|null} node нода из карусели страницы; без неё рисуется подсказка.
 */
export async function openWorkflowTopic(node) {
    const host = document.getElementById('workflowTopic');
    host.style.display = 'block';

    if (!node || !node.id) {
        host.innerHTML = '<div class="topic-empty">Выберите ноду слева: '
            + 'группы тем принадлежат ноде, а не отдельному workflow</div>';
        return;
    }

    if (topicState.nodeId !== node.id) {
        topicState.nodeId = node.id;
        topicState.picked = {kind: null, id: null};
        topicState.page = 0;
    }

    host.innerHTML = `
      <div class="topic-body">
        <div class="topic-sidebar">
          <div class="topic-sidebar-head">
            <span class="topic-node-name">${esc(node.name)}</span>
            <button type="button" class="btn-branch btn-topic-primary" id="groupNew">+ Группа</button>
          </div>
          <div class="topic-list" id="groupList"></div>
          <div class="topic-pager">
            <button type="button" class="btn-branch" id="groupPagePrev">Назад</button>
            <span id="groupPageLabel">0</span>
            <button type="button" class="btn-branch" id="groupPageNext">Вперёд</button>
          </div>
        </div>
        <div class="topic-detail" id="branchDetail">
          <div class="topic-empty">Выберите группу или тему слева</div>
        </div>
      </div>`;

    document.getElementById('groupNew').onclick = groupNew;
    document.getElementById('groupPagePrev').onclick = () => {
        if (topicState.page > 0) {
            topicState.page -= 1;
            treeRender();
        }
    };
    document.getElementById('groupPageNext').onclick = () => {
        if ((topicState.page + 1) * PAGE_SIZE < topicState.branches.length) {
            topicState.page += 1;
            treeRender();
        }
    };

    await treeLoad();
    await topicRoadsLoad(topicState.nodeId);
    detailRender();
}

/**
 * Ветки и все их темы — двумя запросами на всё дерево.
 *
 * ⚠ Темы берутся одной ручкой по ноде, а не по ветке в цикле: дерево показывает
 * их сразу все, и запрос на каждую ветку означал бы десяток походов на отрисовку.
 */
async function treeLoad() {
    topicState.branches = (await topicApi(
        `/workflow_topic/list?node_id=${topicState.nodeId}`)).result || [];

    const topics = (await topicApi(
        `/workflow_topic/topic/list?node_id=${topicState.nodeId}`)).result || [];

    topicState.topicsByBranch = {};
    topics.forEach(topic => {
        const key = String(topic.topic_group_id);
        (topicState.topicsByBranch[key] = topicState.topicsByBranch[key] || []).push(topic);
    });

    if (topicState.page * PAGE_SIZE >= topicState.branches.length) topicState.page = 0;
    treeRender();
}

function treeRender() {
    const list = document.getElementById('groupList');
    if (!list) return;

    if (!topicState.branches.length) {
        list.innerHTML = '<div class="topic-empty">Веток нет</div>';
        document.getElementById('groupPageLabel').textContent = '0';
        return;
    }

    const activeBranchId = String((groupCurrent() || {}).id || '');
    const from = topicState.page * PAGE_SIZE;

    list.innerHTML = topicState.branches.slice(from, from + PAGE_SIZE).map(branch => {
        const topics = topicsOf(branch.id);
        const isActiveBranch = topicState.picked.kind === 'branch'
            && String(topicState.picked.id) === String(branch.id);
        // «+ Тема» показываем только у ветки, с которой сейчас работают: у
        // каждой она была бы шумом в дереве
        const showAdd = String(branch.id) === activeBranchId;

        const children = topics.map((topic, index) => {
            const last = index === topics.length - 1 && !showAdd;
            const isActiveTopic = topicState.picked.kind === 'topic'
                && String(topicState.picked.id) === String(topic.id);
            return `
              <div class="tree-child ${last ? 'is-last' : ''} ${isActiveTopic ? 'is-active' : ''}"
                   data-topic="${topic.id}">
                <span class="topic-dot ${topic.is_enabled ? 'is-on' : ''}"></span>
                <span class="tree-child-main">
                  <span class="tree-child-title">${esc(topic.title)}</span><br>
                  <span class="topic-row-name">${esc(topic.name)}</span>
                </span>
                <span class="topic-count">${plural(
                    tagList(topic.tags).length, 'метка', 'метки', 'меток')}</span>
              </div>`;
        }).join('');

        const addRow = showAdd ? `
          <div class="tree-child is-last tree-add" data-add="${branch.id}">
            <span class="tree-add-text">+ Тема</span>
          </div>` : '';

        return `
          <div class="tree-branch">
            <div class="topic-row ${isActiveBranch ? 'is-active' : ''}" data-branch="${branch.id}">
              <span class="topic-dot ${branch.is_enabled ? 'is-on' : ''}"></span>
              <span class="topic-row-main">
                <span class="topic-row-title">${esc(branch.title)}</span><br>
                <span class="topic-row-name">${esc(branch.name)}</span>
              </span>
              <span class="topic-row-count">${plural(
                  topics.length, 'тема', 'темы', 'тем')}</span>
            </div>
            ${children}${addRow}
          </div>`;
    }).join('');

    list.querySelectorAll('[data-branch]').forEach(row => {
        row.onclick = () => pick('branch', Number(row.dataset.branch));
    });
    list.querySelectorAll('[data-topic]').forEach(row => {
        row.onclick = () => pick('topic', Number(row.dataset.topic));
    });
    list.querySelectorAll('[data-add]').forEach(row => {
        // ⚠ Группа берётся из самой строки: «+ Тема» стоит у конкретной группы,
        // и у новой темы это единственный ответ на вопрос «куда заводим».
        row.onclick = () => pick('topic', null, Number(row.dataset.add));
    });

    const pages = Math.ceil(topicState.branches.length / PAGE_SIZE);
    document.getElementById('groupPageLabel').textContent = `${topicState.page + 1} / ${pages}`;
}

function pick(kind, id, groupId = null) {
    topicState.picked = {kind, id, groupId};
    treeRender();
    detailRender();
}

// ── Правая колонка: ровно то, что выбрано ───────────────────────────────────

function detailRender() {
    const detail = document.getElementById('branchDetail');
    if (!detail) return;

    if (topicState.picked.kind === 'topic') {
        topicCardRender(detail);
        return;
    }
    if (topicState.picked.kind === 'branch') {
        groupCardRender(detail);
        return;
    }
    detail.innerHTML = '<div class="topic-empty">Выберите группу или тему слева</div>';
}

function groupCardRender(detail) {
    const branch = groupCurrent();
    if (!branch) {
        detail.innerHTML = '<div class="topic-empty">Выберите группу или тему слева</div>';
        return;
    }

    detail.innerHTML = `
      <div class="topic-card">
        <div class="topic-card-head">Группа тем</div>
        <div class="topic-form-row">
          <div class="topic-field"><label>Название</label>
            <input class="topic-control" id="g_title" value="${esc(branch.title)}"></div>
          <div class="topic-field topic-field-check">
            <label class="topic-check">
              <input type="checkbox" id="g_is_enabled" ${branch.is_enabled ? 'checked' : ''}>
              Включена
            </label>
          </div>
        </div>
        <div class="topic-hint" style="margin-top:4px">
          Пороги живут <b>у темы</b>, а не здесь: у каждой свои метки и свои вопросы,
          и судится она независимо от соседей.
        </div>
        <div class="topic-hint" style="margin-top:4px">
          Своя дорога (subflow) выбирается <b>на шаге</b>, на вкладке «Шаги», — там же,
          где настраиваются карты вызова. Здесь её нет намеренно: карты принадлежат паре
          «шаг + подпоток», и смена дороги из другого места оставила бы карты от прежней
          молча. Одна и та же группа в соседних шагах может идти разными путями.
        </div>
        <div class="topic-actions">
          <button type="button" class="btn-branch btn-topic-primary" id="g_save">Сохранить</button>
          <button type="button" class="btn-branch" id="g_topic_new">+ Тема</button>
          <button type="button" class="btn-branch btn-topic-danger" id="g_delete">Удалить группу</button>
        </div>
      </div>`;

    document.getElementById('g_save').onclick = groupSave;
    document.getElementById('g_delete').onclick = groupDelete;
    document.getElementById('g_topic_new').onclick =
        () => pick('topic', null, branch.id);
}

function topicCardRender(detail) {
    const branch = groupCurrent();
    const topic = topicCurrent() || {
        name: '', title: '', tags: '', instructions: '', is_enabled: 1,
        tags_qty_accept: 2, questions_qty_yes_accept: 1,
    };
    const isNew = !topicCurrent();

    detail.innerHTML = `
      <div class="topic-card">
        <div class="topic-card-head">
          <span class="topic-head-name">
            <span class="topic-crumb">${esc((branch || {}).title || '')}</span>
            ${isNew ? 'новая тема' : 'тема'}
            <label class="topic-check topic-head-check">
              <input type="checkbox" id="t_is_enabled" ${topic.is_enabled ? 'checked' : ''}>
              Включена
            </label>
          </span>
          <span class="topic-head-actions">
            <button type="button" class="btn-branch btn-topic-primary" id="t_save">Сохранить тему</button>
            ${isNew ? '' : '<button type="button" class="btn-branch btn-topic-danger topic-trash"'
                           + ' id="t_delete" title="Удалить тему" aria-label="Удалить тему">🗑</button>'}
          </span>
        </div>
        <div class="topic-cols">
          <div class="topic-col topic-col-main">
            <div class="topic-form-row">
              <div class="topic-field"><label>Название</label>
                <input class="topic-control" id="t_title" value="${esc(topic.title)}"></div>
              <div class="topic-field"><label>Код</label>
                <input class="topic-control" id="t_name" value="${esc(topic.name)}"></div>
            </div>
            <div class="topic-hint topic-hint-row">Код: под ним тема видна в журнале
                 прогона и приезжает агенту переменной
                 <code>%topic_action_name%</code>.</div>
            <div class="topic-field topic-field-grow">
              <div class="instr-head">
                <label>Инструкция</label>
                <span class="instr-big" id="t_instructions_big"></span>
              </div>
              <textarea class="topic-control instr-area" id="t_instructions"
                        placeholder="Что делать, когда тема поднята: как отвечать, куда вести разговор, чего нельзя"
                        >${esc(topic.instructions)}</textarea>
              <div class="topic-hint">Весь текст уезжает агенту переменной
                   <code>%topic_action_instructions%</code> — и в генерацию ответа, и к судье.</div>
            </div>
          </div>
          <div class="topic-col topic-col-rules">
            <div class="topic-field">
              <div class="tag-head">
                <label>Метки <span class="tag-counter" id="t_tags_count"></span></label>
                <div class="tag-langs" id="t_tags_langs"></div>
              </div>
              <div class="tag-editor" id="t_tags_box">
                <input class="tag-input" id="t_tags_input" placeholder="добавить метку и Enter…">
              </div>
              <div class="topic-hint">Ищутся в тексте разговора <b>словом целиком</b>, поэтому
                   метка — короткое слово, которое человек вправду пишет (<code>photo</code>,
                   <code>send</code>), и каждая форма своя: <code>photo</code> не найдёт
                   <code>photos</code>. Точность даёт не метка, а вопрос ниже.</div>
            </div>
            <div class="topic-form-row">
              <div class="topic-field">
                <label>Минимум разных меток</label>
                <input class="topic-control" id="t_tags_qty_accept" type="number" min="1" max="20"
                       value="${Number(topic.tags_qty_accept) || 1}">
                <div class="topic-hint">Сколько <b>разных</b> меток нашлось — тогда тему
                     проверяют вопросами. Повтор одной метки считается за одну.</div>
              </div>
              <div class="topic-field">
                <label>Минимум ответов «yes»</label>
                <input class="topic-control" id="t_questions_qty_yes_accept" type="number" min="1" max="20"
                       value="${Number(topic.questions_qty_yes_accept) || 1}">
                <div class="topic-hint">Сколько ответов «yes» означают, что тема поднята.
                     Вопросов нет — хватает одних меток.</div>
              </div>
            </div>
            <div class="topic-field">
              <div class="tag-head">
                <label>Вопросы <span class="tag-counter" id="t_questions_count"></span></label>
                <div class="tag-langs" id="t_questions_langs"></div>
              </div>
              <div id="t_questions_box"></div>
              <button type="button" class="btn-branch" id="t_question_add">+ Вопрос</button>
              <div class="topic-hint">Ответ на вопрос — только «yes» или «no», и спрашивают
                   о том, что в тексте вправду написано. ⚠ Вопрос обязан проверять <b>ту же</b>
                   тему, что и метки: метка ловит слово, вопрос — смысл за ним. Список пуст —
                   модель не зовут вовсе.</div>
            </div>
          </div>
        </div>
      </div>`;

    tagsEditorInit(tagList(topic.tags));
    questionsEditorInit(topic.questions);
    instructionsBigInit();

    document.getElementById('t_save').onclick = () => topicSave(isNew ? null : topic.id);
    const removeButton = document.getElementById('t_delete');
    if (removeButton) removeButton.onclick = () => topicDelete(topic.id);
}

// ── Инструкция темы ─────────────────────────────────────────────────────────
//
// ⚠⚠ Текст ОДИН, и прежде их было три — «разрешено / желательно / запрещено»
// вкладками. Деление оказалось вымышленным: человек пишет инструкцию целиком, а
// раскладывать её по трём коробкам мог только гадая, в какую ляжет «соглашайся,
// но не обещай часа». Вкладки при этом прятали написанное — заполненность
// приходилось показывать точкой на корешке, и всё равно два поля из трёх были
// не видны.

function instructionsBigInit() {
    // Иконка большого окна — общая `textModalIcon`, та же, что у промптов шага.
    const bigHost = document.getElementById('t_instructions_big');
    const area = document.getElementById('t_instructions');
    if (!bigHost || !area) return;

    bigHost.innerHTML = '';
    bigHost.appendChild(textModalIcon(area, 'Инструкция темы'));
}

// ── Редактор меток: чипсы вместо строки через запятую ───────────────────────
//
// ⚠ Строкой их было не прочитать: восьми меток не хватало ширины поля, и хвост
// уезжал за край. А метка — единица отбора темы, и смотрят на них поштучно:
// «есть ли такая», «не завелась ли дважды».

/** Приведение — **то же**, что у движка (`ai_workflow_topic_action_tags_split`).
 *
 * ⚠ Нижний регистр и схлопнутые пробелы: сравнение идёт приведёнными, и человек
 * должен видеть ровно то, что будет сравниваться. Покажи мы «Обмен Письмами»,
 * а сравнивай «обмен письмами» — вышли бы две метки, неразличимые на глаз.
 */
function tagNormalize(raw) {
    return String(raw || '').trim().replace(/\s+/g, ' ').toLowerCase();
}

/**
 * Перевести **все** метки темы разом.
 *
 * ⚠⚠ По одной метке за запрос, а не списком одной строкой. Список модель
 * склеивает и перенумеровывает — у соседа это записано прямо: «переносы строк
 * модель съедает». Метка короткая, восемь запросов уходят разом (`Promise.all`)
 * и стоят по времени одного.
 *
 * ⚠⚠ Не перевелась хоть одна — **не меняем ничего**. То же правило, что у
 * промптов: половина переведённых меток хуже непереведённых, потому что словарь
 * станет смешанным незаметно.
 *
 * ⚠ Перевод не сохраняется сам: человек смотрит на него и жмёт «Сохранить
 * тему». Промахнулся языком — ушёл с темы, и ничего не случилось.
 */
/**
 * Перевести список строк целиком — либо все, либо ни одной.
 *
 * ⚠⚠ Общая часть для меток и вопросов, и держать её надо в одном месте.
 * Отличия у них всего два — приведение после перевода и схлопывание
 * повторов, — а одинакового много: определение исходного языка, отказ от
 * перевода «на тот же язык», параллельные запросы, занятая кнопка и правило
 * «не перевелась одна — не трогаем ничего».
 *
 * ⚠ Частичный перевод хуже отказа: половина меток на английском, половина на
 * русском — это тема, которая не ловится ни на одном языке, и человек видит
 * зелёное «переведено».
 *
 * @param {string[]} items что переводим.
 * @param {object} lang язык из `TAG_LANGS`.
 * @param {HTMLElement} button кнопка-флаг: её занимаем на время работы.
 * @param {object} words слова для сообщений: `{empty, already, done}`.
 * @returns {Promise<string[]|null>} переведённое либо `null` — делать нечего.
 */
async function listTranslate(items, lang, button, words) {
    if (!items.length) {
        showNotification(words.empty, 'error');
        return null;
    }

    const source = textTranslateGuess(items.join(' '));
    if (source === lang.code) {
        showNotification(`${words.already} ${lang.word}`, 'info');
        return null;
    }

    const was = button.textContent;
    button.disabled = true;
    button.textContent = '…';

    try {
        const done = await Promise.all(items.map(async (item) => {
            const answer = await postData('/translate', {
                text: item,
                language_from: source,
                language_to: lang.code,
            });
            return String(answer.result || '').trim();
        }));

        const lostAt = done.findIndex(one => !one);
        if (lostAt >= 0) {
            showNotification(
                `Не перевелось: «${items[lostAt]}» — оставлено как было`, 'error');
            return null;
        }
        return done;
    } catch (e) {
        showNotification(`Не перевелось: ${e.message}`, 'error');
        return null;
    } finally {
        button.disabled = false;
        button.textContent = was;
    }
}

async function tagsTranslate(lang, button) {
    const done = await listTranslate(topicState.tags, lang, button, {
        empty: 'Меток нет',
        already: 'Метки и так на',
    });
    if (!done) return;

    // ⚠ Приведение и схлопывание — ТОЛЬКО у меток: это множество, и перевод
    // вправду может свести две в одну («письмо» и «письма» → «letter»).
    // У вопросов так нельзя: два одинаковых вопроса — ошибка человека, и
    // молча убрать один значит скрыть её.
    const kept = [];
    done.map(tagNormalize).forEach(tag => {
        if (tag && !kept.includes(tag)) kept.push(tag);
    });
    topicState.tags = kept;
    tagsEditorRender();

    showNotification(`Метки на ${lang.word}. Не забудьте «Сохранить тему»`, 'success');
}

/**
 * Перевести вопросы темы на выбранный язык.
 *
 * ⚠ Переводятся и выключенные: выключатель — про «не спрашивать сейчас», а не
 * про «это черновик». Оставь их на прежнем языке, и включённый назавтра вопрос
 * придёт в промпт чужой речью.
 */
async function questionsTranslate(lang, button) {
    const texts = topicState.questions.map(one => one.question.trim());
    const done = await listTranslate(texts.filter(Boolean), lang, button, {
        empty: 'Вопросов нет',
        already: 'Вопросы и так на',
    });
    if (!done) return;

    let at = 0;
    topicState.questions.forEach(one => {
        if (one.question.trim()) one.question = done[at++];
    });
    questionsEditorRender();

    showNotification(`Вопросы на ${lang.word}. Не забудьте «Сохранить тему»`, 'success');
}

function tagsLangsRender() {
    langsRender('t_tags_langs', 'перевести все метки на', tagsTranslate);
}

function questionsLangsRender() {
    langsRender('t_questions_langs', 'перевести все вопросы на', questionsTranslate);
}

/**
 * Ряд флагов-переводчиков в указанный контейнер.
 *
 * ⚠ Один код на метки и вопросы: ряды одинаковы до последнего класса, и две
 * копии разошлись бы на первой правке подсказки или порядка языков.
 */
function langsRender(hostId, hint, translate) {
    const host = document.getElementById(hostId);
    if (!host) return;

    host.innerHTML = '';
    TAG_LANGS.forEach(lang => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'tag-lang';
        button.textContent = lang.flag;
        button.title = `${hint} ${lang.word}`;
        button.onclick = () => translate(lang, button);
        host.appendChild(button);
    });
}

// ── Вопросы темы ────────────────────────────────────────────────────────────
//
// ⚠⚠ Строками с полем ввода, а не чипсами, как метки. Метка — слово, вопрос —
// предложение: в чипс он не помещается и правится целиком, а не заводится
// заново. Отсюда же своё состояние и свои кнопки.
//
// ⚠ Порядок строк = порядок номеров в промпте. Модель отвечает ключом-номером,
// поэтому перестановка строк меняет нумерацию — это видно глазами, и так и надо.

function questionsEditorInit(questions) {
    topicState.questions = (questions || []).map(item => ({
        question: String(item.question || ''),
        is_enabled: Number(item.is_enabled ?? 1) ? 1 : 0,
    }));
    questionsLangsRender();
    questionsEditorRender();

    const add = document.getElementById('t_question_add');
    if (add) add.onclick = () => {
        topicState.questions.push({question: '', is_enabled: 1});
        questionsEditorRender();
        // Фокус в только что заведённую строку: кнопку нажали, чтобы писать
        const rows = document.querySelectorAll('.question-text');
        if (rows.length) rows[rows.length - 1].focus();
    };
}

function questionsEditorRender() {
    const host = document.getElementById('t_questions_box');
    if (!host) return;

    host.innerHTML = '';
    topicState.questions.forEach((item, index) => {
        const row = document.createElement('div');
        row.className = 'question-row';

        const number = document.createElement('span');
        number.className = 'question-no';
        number.textContent = `${index + 1}.`;
        row.appendChild(number);

        const text = document.createElement('input');
        text.className = 'topic-control question-text';
        text.value = item.question;
        text.placeholder = 'Does either of them offer to send a photo?';
        // ⚠ Пишем в состояние на каждый знак, а не перерисовываем строку: иначе
        // уедет курсор. Та же причина, что у поля ввода меток.
        text.oninput = () => { topicState.questions[index].question = text.value; };
        row.appendChild(text);

        const enabled = document.createElement('label');
        enabled.className = 'topic-check question-enabled';
        enabled.title = 'выключенный вопрос модели не показывается';
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.checked = !!item.is_enabled;
        box.onchange = () => {
            topicState.questions[index].is_enabled = box.checked ? 1 : 0;
            questionsEditorRender();
        };
        enabled.appendChild(box);
        row.appendChild(enabled);

        const drop = document.createElement('button');
        drop.type = 'button';
        drop.className = 'btn-branch btn-topic-danger question-drop';
        drop.textContent = '×';
        drop.title = 'убрать вопрос';
        drop.onclick = () => {
            topicState.questions.splice(index, 1);
            questionsEditorRender();
        };
        row.appendChild(drop);

        if (!item.is_enabled) row.classList.add('question-row-off');
        host.appendChild(row);
    });

    const counter = document.getElementById('t_questions_count');
    if (counter) {
        const live = topicState.questions.filter(one => one.is_enabled
            && one.question.trim()).length;
        counter.textContent = live
            ? plural(live, 'вопрос', 'вопроса', 'вопросов') : '';
    }
}

function tagsEditorInit(tags) {
    topicState.tags = tags.map(tagNormalize).filter(Boolean);
    tagsLangsRender();

    const input = document.getElementById('t_tags_input');
    if (!input) return;

    input.onkeydown = (event) => {
        if (event.key === 'Enter' || event.key === ',') {
            event.preventDefault();
            tagsAdd(input.value);
            input.value = '';
            tagsEditorRender();
        } else if (event.key === 'Backspace' && !input.value && topicState.tags.length) {
            // Привычное поведение поля с чипсами: пустой ввод и Backspace
            // снимают последнюю метку
            topicState.tags.pop();
            tagsEditorRender();
        }
    };

    // Вставка из буфера: там обычно вся строка через запятую — разбираем сразу,
    // не дожидаясь Enter
    input.oninput = () => {
        if (!input.value.includes(',')) return;
        tagsAdd(input.value);
        input.value = '';
        tagsEditorRender();
    };

    // Набрал и ушёл мышью — метка не должна пропасть
    input.onblur = () => {
        if (!input.value.trim()) return;
        tagsAdd(input.value);
        input.value = '';
        tagsEditorRender();
    };

    document.getElementById('t_tags_box').onclick = (event) => {
        if (event.target.id === 't_tags_box') input.focus();
    };

    tagsEditorRender();
}

function tagsAdd(raw) {
    String(raw || '').split(',').forEach(part => {
        const tag = tagNormalize(part);
        // Повтор молча не добавляется: в словаре он всё равно схлопнется
        if (tag && !topicState.tags.includes(tag)) topicState.tags.push(tag);
    });
}

function tagsEditorRender() {
    const box = document.getElementById('t_tags_box');
    const input = document.getElementById('t_tags_input');
    if (!box || !input) return;

    // ⚠ Перерисовываем только чипсы, а поле ввода оставляем на месте: пересборка
    // всего блока уносила бы фокус и набранный текст на каждой метке
    box.querySelectorAll('.tag-chip').forEach(node => node.remove());

    topicState.tags.forEach((tag, index) => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = tag;

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'tag-x';
        remove.textContent = '×';
        remove.title = 'убрать метку';
        remove.onclick = () => {
            topicState.tags.splice(index, 1);
            tagsEditorRender();
        };

        chip.appendChild(remove);
        box.insertBefore(chip, input);
    });

    const counter = document.getElementById('t_tags_count');
    if (counter) {
        counter.textContent = topicState.tags.length
            ? plural(topicState.tags.length, 'метка', 'метки', 'меток') : '';
    }
}

// ── Правки ──────────────────────────────────────────────────────────────────

async function groupSave() {
    const branch = groupCurrent();
    try {
        await topicApi(`/workflow_topic/${branch.id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            // ⚠ Кода здесь нет: он служебный и правке не подлежит — на нём
            // держатся имя скелета подпотока и поиск ветки в миграциях-сидах
            // ⚠ `match_min` больше не шлётся: порог уехал к теме, и колонка у
            // ветки доживает до сноса второй выкладкой
            body: JSON.stringify({
                title: document.getElementById('g_title').value.trim(),
                is_enabled: document.getElementById('g_is_enabled').checked ? 1 : 0,
            }),
        });
        await treeLoad();
        detailRender();
        showNotification(`Группа «${branch.title}» сохранена`, 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

async function groupDelete() {
    const branch = groupCurrent();
    // ⚠ Удаление необратимо и уносит темы каскадом — спрашиваем всегда
    if (!confirm(`Удалить группу «${branch.title}» вместе с её темами?`)) return;

    try {
        await topicApi(`/workflow_topic/${branch.id}`, {method: 'DELETE'});
        topicState.picked = {kind: null, id: null};
        await treeLoad();
        detailRender();
        showNotification(`Группа «${branch.title}» удалена`, 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

function topicBody() {
    // ⚠ Недонабранное в поле ввода тоже уходит в метки: человек напечатал
    // «скинь фотку» и нажал «Сохранить тему», не нажав Enter, — потерять это
    // молча хуже всего
    const input = document.getElementById('t_tags_input');
    if (input && input.value.trim()) {
        tagsAdd(input.value);
        input.value = '';
        tagsEditorRender();
    }

    return {
        name: document.getElementById('t_name').value.trim(),
        title: document.getElementById('t_title').value.trim(),
        tags: topicState.tags.join(', '),
        // ⚠ Пороги — у темы: у каждой свои метки и свои вопросы, и судится
        // она независимо от соседей. `|| 1` держит низ: ноль в поле означал бы
        // «подходит всегда», а это не порог
        tags_qty_accept: Number(document.getElementById('t_tags_qty_accept').value) || 1,
        questions_qty_yes_accept:
            Number(document.getElementById('t_questions_qty_yes_accept').value) || 1,
        // ⚠ Пустые строки отбрасываются здесь, а не на сервере: человек нажал
        // «+ Вопрос» и передумал — это не повод отказывать в сохранении темы.
        questions: topicState.questions
            .filter(one => one.question.trim())
            .map(one => ({question: one.question.trim(), is_enabled: one.is_enabled})),
        instructions: document.getElementById('t_instructions').value,
        is_enabled: document.getElementById('t_is_enabled').checked ? 1 : 0,
    };
}

async function topicSave(topicId) {
    const headers = {'Content-Type': 'application/json'};
    const payload = topicBody();
    const body = JSON.stringify(payload);
    const title = payload.title || payload.name || 'тема';
    const branch = groupCurrent();
    try {
        if (topicId) {
            await topicApi(`/workflow_topic/topic/${topicId}`, {method: 'PUT', headers, body});
            await treeLoad();
            detailRender();
            showNotification(`Тема «${title}» сохранена`, 'success');
        } else {
            const created = await topicApi(`/workflow_topic/${branch.id}/topic`,
                                            {method: 'POST', headers, body});
            await treeLoad();
            topicState.picked = {kind: 'topic', id: created.result.id};
            treeRender();
            detailRender();
            showNotification(`Тема «${title}» заведена`, 'success');
        }
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

async function topicDelete(topicId) {
    const topic = topicCurrent();
    const title = (topic && topic.title) || 'тема';
    if (!confirm(`Удалить тему «${title}»?`)) return;

    const branch = groupCurrent();
    try {
        await topicApi(`/workflow_topic/topic/${topicId}`, {method: 'DELETE'});
        // После удаления темы показываем её ветку: пустая правая колонка
        // выглядела бы так, будто выбор сбросился сам
        topicState.picked = branch ? {kind: 'branch', id: branch.id} : {kind: null, id: null};
        await treeLoad();
        detailRender();
        showNotification(`Тема «${title}» удалена`, 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

async function groupNew() {
    // ⚠ Один вопрос, а не два: код ветки собирает сервер из названия
    // («Договориться» → `dogovoritsya`). Спрашивать его у человека значило бы
    // просить придумать то, чего он нигде не увидит.
    const title = prompt('Название группы тем (например «Темы общения»)');
    if (!title) return;
    try {
        const created = await topicApi('/workflow_topic', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({node_id: topicState.nodeId, title: title.trim()}),
        });
        await treeLoad();
        pick('branch', created.result.id);
        showNotification(`Группа «${created.result.title}» заведена`, 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}
