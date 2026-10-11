// Кэш индекса «Undefined переменные» для списков, которые не могут его вычислить сами.
//
// ## ⚠⚠ Здесь сеть и кэш; правила здесь нет
//
// Правило «что такое неопределённая переменная» живёт в `variable-group.js` и
// только там. Этот модуль берёт то, чего правилу не хватает из стейта страницы:
// сырьё для **чужих** workflow (шаги, реестр, скрытые имена) — одним пакетом с
// бэкенда, и держит его в кэше, чтобы список слева и панель графа спрашивали
// имя столько раз, сколько видят, — а не столько раз, сколько workflow открыто.
//
// Для workflow, открытого в редакторе, сырьё берётся из стейта страницы
// (`state.allCurrentStepsData`, `state.allCurrentVariables`): оно всегда свежее
// пакета, который мог быть скачан до правки шага.

import {getData} from '../api.js';
import {topicActionNames, undefinedVariables} from './variable-group.js';
import {topicRoadIs} from './topic-roads.js';
import {state} from './state.js';
import {editorWorkflowId} from './utils.js';

// workflow id → сырьё из бэкенда: {steps, registryNames, hiddenNames}.
const _raw = new Map();
// workflow id → вычисленный Map<имя, [шаги]>; null — «данных нет» (не путать с
// пустой картой: пустая — это «данные есть, неопределённых нет»).
const _computed = new Map();

let _loadPromise = null;
const _listeners = new Set();

/**
 * Скрытые имена (proxy ноды, переменные агента) для чужого workflow из кэша.
 *
 * Правилу они нужны как «обеспеченные»: показывать их нельзя (указание
 * хозяина), но и кричать на них нечем. Пустой список — «данных нет», тогда
 * правило не считает имя обеспеченным и неопределённая показывает честно.
 */
export function hiddenNamesFor(workflowId) {
    return _raw.get(String(workflowId))?.hiddenNames || [];
}

/**
 * Один запрос на страницу: сырьё для всех workflow разом.
 *
 * Возврат — тот же промис, что и первый вызов, значит вторая и каждая дальняя
 * вкладка «Граф» ждёт сеть только впервой раз. Сбой не кэшим: следующий вызов
 * пробует снова.
 */
export function ensureUndefinedIndex() {
    if (!_loadPromise) {
        _loadPromise = getData('/workflow_variable/undefined_index')
            .then((res) => {
                const workflows = res?.result?.workflows || res?.workflows || {};
                Object.entries(workflows).forEach(([id, entry]) => {
                    _raw.set(String(id), {
                        steps: entry?.steps || [],
                        registryNames: entry?.registryNames || [],
                        hiddenNames: entry?.hiddenNames || [],
                    });
                });
                _computed.clear();
                return _raw.size;
            })
            .catch(e => {
                console.error('Не удалось загрузить индекс неопределённых переменных:', e);
                _loadPromise = null; // сбой — не отметка «готово»: следующий вызов пробует снова
                return null;
            });
    }
    return _loadPromise;
}

/**
 * Сброс кэша вычисления для workflow после правки его шагов/переменных + весть
 * подписчикам.
 *
 * ⚠ Зовётся на каждой дороге записи (сохранение шага, переменной, workflow):
 * списки берут значки из кэша вычисления, и без сброса они врали бы до первой
 * полной перезагрузки страницы.
 */
export function invalidateUndefinedIndex(workflowId) {
    _computed.delete(String(workflowId ?? editorWorkflowId()));
    _notify();
}

/**
 * Сброс вычисления **всем** workflow сразу + весть подписчикам.
 *
 * ⚠⚠ Нужен там, где изменилось не содержимое workflow, а ответ на вопрос о нём
 * со стороны: дорога шага `topic_action` правится в ОДНОМ workflow, а снимает
 * красный с `topic_action_*` у ДРУГОГО — у того подпотока, на который она
 * указала. Поимённый сброс тут промахивается мимо цели по устройству.
 */
export function invalidateUndefinedIndexAll() {
    _computed.clear();
    _notify();
}

/**
 * Неопределённые переменные workflow: вычисление с кэшем.
 *
 * Args:
 *     workflowId: id из `state.allWorkflows` / сырьё того же id.
 *
 * Returns:
 *     Promise<Map<имя, [шаг…]> | null>: null — данных нет (индекс не загружен),
 *     пустая карта — неопределённых нет.
 */
export async function workflowUndefinedEntries(workflowId) {
    await ensureUndefinedIndex();
    return _workflowUndefinedEntriesSync(workflowId);
}

/** Та же работа без ожидания сети: для отрисовки, идущей за `await ensureUndefinedIndex()`. */
export function workflowUndefinedEntriesSync(workflowId) {
    if (_loadPromise === null) return null; // индекс не догрузился — молча без значков
    return _workflowUndefinedEntriesSync(workflowId);
}

/** Подписка на «индекс догрузился / кэш сброшен»; возвращает функцию отписки. */
export function onUndefinedIndexChange(cb) {
    _listeners.add(cb);
    return () => _listeners.delete(cb);
}

// ── детали реализации ──────────────────────────────────────────────────────────
// Ниже — приватные функции модуля: наружу не торчат, зовутся по имени с
// префиксом `_` (code_rules.md §1.2, §3).

function _notify() {
    _listeners.forEach(cb => {
        try {
            cb();
        } catch (e) {
            console.error('Ошибка подписчика на индекс неопределённых переменных:', e);
        }
    });
}

function _workflowUndefinedEntriesSync(workflowId) {
    const key = String(workflowId);

    if (_computed.has(key)) return _computed.get(key);

    // Для открытого редактором workflow сырьё — из стейта: шаги и переменные
    // правятся на странице, и пакет бэкенда может быть снят до правки.
    const opened = editorWorkflowId();
    const fromEditor = opened && key === String(opened);

    let steps;
    let registryNames;
    let hiddenNames;

    if (fromEditor) {
        steps = state.allCurrentStepsData;
        // `allCurrentVariables` на старте страницы — `{}` (state.js), а не массив:
        // `(x || []).map` тут ронял бы отрисовку панели. Считаем только массив.
        registryNames = Array.isArray(state.allCurrentVariables)
            ? state.allCurrentVariables.map(one => one?.name) : [];
        hiddenNames = _raw.get(key)?.hiddenNames || [];
    } else {
        const entry = _raw.get(key);
        if (!entry) return null; // чужой workflow без данных: показывать нечего
        steps = entry.steps;
        registryNames = entry.registryNames;
        hiddenNames = entry.hiddenNames;
    }

    if (!Array.isArray(steps)) return null;

    const result = undefinedVariables(
        registryNames, steps, state.allWorkflows, state.allAvailableTools, hiddenNames);

    // ⚠⚠ У подпотока, который и есть дорога ветки, `topic_*` — не
    // «неопределённые»: записи в реестре у них нет по устройству, а значение
    // приедет от шага `branch` (`workflow_topic.md`).
    //
    // ⚠ Отсев стоит **здесь**, а не у читателя: `undefinedVariables` — общий
    // источник для троих (панель графа, значок ⚠️ в списке, группы переменных),
    // и отфильтруй я одного, двое других продолжали бы врать красным. Ровно это
    // и случилось: группу я сделал, а граф остался с «undefined».
    if (topicRoadIs(key)) {
        topicActionNames().forEach(name => result.delete(name));
    }

    _computed.set(key, result);
    return result;
}
