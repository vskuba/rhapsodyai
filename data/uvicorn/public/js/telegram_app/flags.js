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
        'Задача у менеджера. Снять — планирование прекратится'
    ));
    // «в разработку» — одноразовый триггер: план утверждать не потребуется,
    // как только он будет готов, задача сменит тип и уйдёт в работу. Умолчание — выключено
    parts.push(flagChipHtml(
        task.id, 'flag_dev', meta['to_development'] === true,
        '_tg_flag_dev',
        'План утверждать не потребуется: задача сама уйдёт в разработку, когда план будет готов'
    ));
    // «в тестирование» — умолчание включено; выключенное хранится явным false
    parts.push(flagChipHtml(
        task.id, 'flag_test', meta['to_testing'] !== false,
        '_tg_flag_test',
        'Готовую работу отправить на QA автоматически'
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

/** HTML одного флажка: title идёт в атрибут — кавычки экранируем, чтобы не сломать разметку */
function flagChipHtml(id, key, checked, handler, title) {
    const safeTitle = (title || '').replace(/"/g, '&quot;');
    const cls = checked ? '' : 'task-flag-off';
    return `<label class="task-flag ${cls}" data-flag="${key}" onclick="event.stopPropagation()" title="${safeTitle}">
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
    let error = null;
    try {
        await postData(ENDPOINT(id), { patch: { [key]: _flagValue(key, inputEl.checked) } });
    } catch (e) {
        error = e;
        inputEl.checked = was;   // сервер ничего не принял — рисуем обратно принятое
    }
    await _reloadTasks();
    if (error) _markFailed(inputEl, error);
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

/** Попытка не удалась: гасим чип и кладём причину в его заголовок */
function _markFailed(inputEl, error) {
    const chip = inputEl.closest('.task-flag');
    if (!chip) return;
    chip.classList.add('task-flag-failed');
    chip.title = _reason(error) || 'Не сохранено';
}

/** Причина человеческой строкой: у 404 своего текста нет, и `e.message` пуст */
function _reason(error) {
    if (!error) return '';
    return error.message || (error.status === 404 ? 'Точка сохранения ещё не заведена' : String(error));
}
