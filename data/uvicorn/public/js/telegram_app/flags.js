/**
 * flags.js — чекбоксы фаз: to_planning, to_development, to_testing + approve
 *
 * Ключи metadata из task.html (строки 3676-3678):
 *   'to_planning' — включить задачу у менеджера; умолчание: нет ключа = включено
 *   'to_development' — одноразовый триггер утверждения плана; true = согласен
 *   'to_testing' — автоматически отправить на QA; умолчание: нет ключа = включено
 *
 * Умолчание «на отсутствие ключа» — причина, по которой снятие и включение пишутся
 * неодинаково: выключенное приходится хранить явным `false`, а включённое — стирать
 * (`null`), иначе карточка всегда рисует один и тот же снятый флажок. Тот же порядок,
 * что в `toggleDevFlag` админки: `checked ? true : null`.
 */

import { postData } from '/static/js/api.js';

const ENDPOINT = (id) => `/telegram-app/task/${id}/metadata`;
const APPROVE_ENDPOINT = (id) => `/telegram-app/task/${id}/pipeline/approve`;

// --- Флажки корневой задачи ---

/**
    Собрать три чипа-флажка для карточки задачи.

    Пустая строка у подзадачи: флаги принадлежат родителю, у ветки дерева свой ход, и
    включать её в фазу отдельно от ствола нельзя.
    */
export function renderRootFlags(task) {
    if (task.parent_id) return '';   // флаги только у корневой задачи — подзадача едет с родителем
    const meta = task.metadata || {};
    const parts = [];
    // «в планирование» — умолчание включено; выключенное хранится явным false
    parts.push(flagChipHtml(
        task.id, 'flag_plan', meta['to_planning'] !== false,
        '_tg_flag_plan',
        'Задача у менеджера. Снять — планирование прекратится',
        _failed[`${task.id}:flag_plan`] || ''
    ));
    // «в разработку» — одноразовый триггер: план утверждать не потребуется,
    // как только он будет готов, задача сменит тип и уйдёт в работу. Умолчание — выключено
    parts.push(flagChipHtml(
        task.id, 'flag_dev', meta['to_development'] === true,
        '_tg_flag_dev',
        'План утверждать не потребуется: задача сама уйдёт в разработку, когда план будет готов',
        _failed[`${task.id}:flag_dev`] || ''
    ));
    // «в тестирование» — умолчание включено; выключенное хранится явным false
    parts.push(flagChipHtml(
        task.id, 'flag_test', meta['to_testing'] !== false,
        '_tg_flag_test',
        'Готовую работу отправить на QA автоматически',
        _failed[`${task.id}:flag_test`] || ''
    ));
    return parts.join('');
}

/**
    Утвердить план (`pipeline_state=plan_approval`).

    Ошибку не глотаем: кнопка сидит в карточке и по умолчанию остаётся нажатой —
    вызывающий (`tasks.js`) сам решает, вернуть её или снять. Список перезагружаем
    и при отказе: если конвейер уже успел сдвинуть состояние, карточка обязана
    показать настоящее, а не то, что было в момент нажатия.
    */
export async function approvePlan(id) {
    let error = null;
    try {
        await postData(APPROVE_ENDPOINT(id));
    } catch (e) {
        error = e;
    }
    await _reloadTasks();
    if (error) {
        alert(_reason(error) || 'Не удалось утвердить план');
        throw error;
    }
}

// --- Обработчики чипов ---

// «В планирование»: снимаем — пишем false, возвращаем — стираем ключ (умолчание)
window._tg_flag_plan = function(inputEl) { return _writeFlag(inputEl, 'to_planning'); };

// «В разработку»: одноразовый триггер, включённое хранится явным true
window._tg_flag_dev = function(inputEl) { return _writeFlag(inputEl, 'to_development'); };

// «В тестирование»: та же инверсия, что у «в планирование»
window._tg_flag_test = function(inputEl) { return _writeFlag(inputEl, 'to_testing'); };

// --- Служебное ниже публичного ---

/** Метка флажка по ключу */
function flagLabel(key) {
    switch (key) {
        case 'flag_plan': return 'В планирование';
        case 'flag_dev': return 'В разработку';
        case 'flag_test': return 'В тестирование';
        default: return key;
    }
}

/**
    HTML одного флажка: title идёт в атрибут — кавычки экранируем, чтобы не сломать разметку.

    Причина отказа (`fail`) нарисована здесь, а не подвешена потом к узлу: список
    перезаписывает карточку целиком, и висящая на узле метка исчезла бы вместе с ним.
    Отметка переживает перезагрузку списком `_failed`, а не ссылкой на элемент.
    */
function flagChipHtml(id, key, checked, handler, title, fail = '') {
    const safeTitle = (fail || title || '').replace(/"/g, '&quot;');
    const cls = (checked ? '' : ' task-flag-off') + (fail ? ' task-flag-failed' : '');
    return `<label class="task-flag${cls}" data-flag="${key}" onclick="event.stopPropagation()" title="${safeTitle}">
        <input type="checkbox" ${checked ? 'checked' : ''}
               onchange="${handler}(this)" data-handler="${handler}">
        <span>${flagLabel(key)}</span>
    </label>`;
}

/**
    Записать флажок и показать настоящее состояние задачи.

    Три чипа отличаются только значением, поэтому тело одно: включённое для
    `to_planning`/`to_testing` — это снятый ключ, для `to_development` — явное true
    (см. шапку файла). Пока PATCH в пути, чекбокс дизейблим: повторный клик записал бы
    в сервер вторую волю человека.

    При отказе чекбокс возвращаем назад и подсвечиваем чип: иначе карточка осталась бы
    с тем, чего сервер не принял, — а это ровно тот случай, когда точка `/metadata`
    ещё не нарисована соседней подзадачей. Список перезагружаем в любом случае:
    запись могла пройти и без ответа.
    */
async function _writeFlag(inputEl, key) {
    const card = inputEl.closest('.task-card');
    const id = Number(card?.dataset.id);
    const was = !inputEl.checked;
    if (!id) return;

    inputEl.disabled = true;
    // Метка отказа — по имени чипа, не по ключу metadata: карточка перерисовывается
    // именем чипа (`data-flag`), и искать подсветку по `to_planning` было бы нечем.
    const chip = inputEl.closest('.task-flag')?.dataset.flag || key;
    let error = null;
    try {
        await postData(ENDPOINT(id), { patch: { [key]: _flagValue(key, inputEl.checked) } });
        delete _failed[`${id}:${chip}`];        // прошлый отказ снят: запись прошла
    } catch (e) {
        error = e;
        inputEl.checked = was;   // сервер ничего не принял — рисуем обратно принятое
        _failed[`${id}:${chip}`] = _reason(error) || 'Не сохранено';
    }
    await _reloadTasks();
    // Список перезаписал карточку: если он не вернулся (списка нет), подсветить всё равно надо
    if (error && document.contains(inputEl)) _markFailed(inputEl);
}

/** Значение ключа по состоянию чекбокса — зеркально админке */
function _flagValue(key, checked) {
    if (key === 'to_development') return checked ? true : null;
    return checked ? null : false;
}

/**
    Перезагрузить список после записи.

    Список объявляет себя сам: `initTasks` вешает коллбек на window. Импорт же
    закрутил бы кольцо — карточки рисует `tasks.js`, а он тянет панель вопросов.
    Без коллбека запись всё равно состоялась: молчать правильнее, чем падать.
    */
function _reloadTasks() {
    return Promise.resolve(window._tg_reload_tasks?.()).catch(() => {});
}

/**
    Неудачная запись чипа: `{«задача:флажок»: причина}`.

    Живёт отдельно от разметки, потому что карточка после перезагрузки списка
    собирается заново — на старом узле ничего удержать нельзя. Чистится своей же
    записью: удалось — ключ сняли.
    */
let _failed = {};

/** Тот же чип, что человек не успел потерять: подсветить и положить причину в заголовок */
function _markFailed(inputEl) {
    const chip = inputEl.closest('.task-flag');
    if (!chip) return;
    chip.classList.add('task-flag-failed');
    const id = chip.closest('.task-card')?.dataset.id;
    chip.title = _failed[`${id}:${chip.dataset.flag}`] || 'Не сохранено';
}

/** Причина человеческой строкой: у 404 своего текста нет, и `e.message` пуст */
function _reason(error) {
    if (!error) return '';
    return error.message || (error.status === 404 ? 'Точка сохранения ещё не заведена' : String(error));
}
