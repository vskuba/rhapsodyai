/**
 * Дороги веток ноды: какие подпотоки кто-то зовёт своей дорогой.
 *
 * ## ⚠⚠ Вопрос здесь ОБРАТНЫЙ, и потому модуль существует
 *
 * «Какая дорога у этого шага» спрашивать не надо — она лежит в метаданных самого
 * шага, и граф читает её там же, где движок. Здесь отвечают на другое: **открытый
 * workflow — он чья-то дорога?** Ответ на это лежит в ЧУЖИХ шагах, в других
 * workflow той же ноды, которых страница не грузит; собрать его может только
 * сервер (`/workflow_topic/road/list`).
 *
 * Спрашивают двое, и оба про одно: список переменных — показывать ли группу
 * «🌿 Branch переменные», и сторож «Undefined» — снимать ли с `topic_*` красный.
 *
 * ⚠ Прежде источником был реестр веток (`branch.workflow_id`), и карта была
 * «ветка → подпоток». Дорога переехала на шаг, и у ветки спрашивать стало нечего.
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

const roads = {nodeId: null, workflowIds: new Set()};

/** Прочитать дороги ноды. Молчит при отказе: нет ответа — нет и дорог. */
export async function topicRoadsLoad(nodeId) {
    roads.nodeId = nodeId || null;
    roads.workflowIds = new Set();

    if (!nodeId) return;

    try {
        const response = await fetch(`/workflow_topic/road/list?node_id=${nodeId}`);
        const body = await response.json();
        (body.result || []).forEach(id => roads.workflowIds.add(String(id)));
    } catch (e) {
        // Ответа нет — ни группы, ни снятия красного, а страница работает дальше
    }
}

/** Этот workflow — дорога какого-нибудь шага `branch`? */
export function topicRoadIs(workflowId) {
    return roads.workflowIds.has(String(workflowId));
}
