/**
 * Дороги веток ноды: `номер ветки → номер подпотока`.
 *
 * ⚠⚠ Один источник на троих. У шага `branch` номера подпотока в метаданных
 * **нет** — там только номер ветки, а дорогу задаёт реестр. Спрашивают это
 * трое: граф (нарисовать подпоток за шагом), список переменных (показать ли
 * группу «Branch») и сама вкладка. Вторая копия карты разошлась бы с первой
 * молча — ровно так, как уже бывало с правилами отбора.
 *
 * ## ⚠⚠ Почему отдельным файлом, а не внутри `branch.js`
 *
 * Карту читает `variable-undefined.js`, а его **гоняют тестами через node**
 * (`tests/test_workflow_undefined_index.py` и соседние — 23 теста). Лежи карта
 * во вкладке, импорт потянул бы за собой `/static/js/notification.js` — путь
 * браузерной раздачи, которого в node нет вовсе, и все 23 падали бы на
 * `ERR_MODULE_NOT_FOUND`. Так и случилось, пока файл был один.
 *
 * ⚠ Отсюда правило для этого модуля: **никаких импортов**. `fetch` — глобальный
 * и в браузере, и в node; больше ничего здесь быть не должно.
 */

const roads = {nodeId: null, byBranch: {}, workflowIds: new Set()};

/** Прочитать реестр веток ноды. Молчит при отказе: нет реестра — нет и дорог. */
export async function branchRoadsLoad(nodeId) {
    roads.nodeId = nodeId || null;
    roads.byBranch = {};
    roads.workflowIds = new Set();

    if (!nodeId) return;

    try {
        const response = await fetch(`/workflow_branch/list?node_id=${nodeId}`);
        const body = await response.json();
        (body.result || []).forEach(branch => {
            if (!branch.workflow_id) return;
            roads.byBranch[String(branch.id)] = String(branch.workflow_id);
            roads.workflowIds.add(String(branch.workflow_id));
        });
    } catch (e) {
        // Реестр недоступен — ни группы, ни стрелки, а страница работает дальше
    }
}

/** Подпоток ветки по её номеру; `null` — ветка сужает общий ответ. */
export function branchRoadOf(branchId) {
    return roads.byBranch[String(branchId)] || null;
}

/** Этот workflow — дорога какой-нибудь ветки? */
export function branchRoadIs(workflowId) {
    return roads.workflowIds.has(String(workflowId));
}
