"""
Остановка задачи человеком — снятый флажок «в разработку» рядом со статусом на
странице задач.

Человек видит «В работе» и хочет, чтобы работа прекратилась: агент замолчал, строка
вернулась в «Ожидает» и сама собой в работу больше не пошла. Снимает остановку он же —
возвратом того же флажка или флажка фазы «в разработку»/«в тестирование».

Почему запрет живёт в `metadata`, а не в человеческом `status`: отбор работы
(`task_claim`) на `status` не смотрит вовсе, он ходит по `pipeline_state`, и
«Ожидает», выставленное руками, следующий тик перебил бы через секунду. Пометка
`TASK_METADATA_KEY_STOP` — тот же запрет, но в том месте, куда захват смотрит.

Порядок шагов важен и обратному не подлежит:

1. пометка — первой, до всего остального: пока она не легла, тик вправе забрать
   строку заново, и остановка обернулась бы перезапуском;
2. возврат строк из «в полёте» — работы у них не было, разбор тот же, что у брошенной
   блокировки, поэтому и карта та же (`TASK_CLAIM_STATE_RECLAIM`);
3. перезапуск оболочек — только тех ролей, что нашлись среди этих строк: карточка одна
   на роль и проект, и перезапуск «на всякий случай» снёс бы ход соседней задачи;
4. отчёт — последним, когда всё уже случилось.

Прогон, которому строку отняли на ходу, доигрывает свой конец в воркере и пишет
результат уже после остановки. Его записи безвредны: `task_state_kanban_sql` не трогает
статус остановленной строки, а следующий захват её не возьмёт.
"""
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE
from src.project.task.task_agent_qa import TASK_QA_ROLE
from src.project.task.task_claim import (
    TASK_CLAIM_INFLIGHT_STATES,
    TASK_CLAIM_STATE_RECLAIM,
    TASK_CLAIM_SUBTASK_STATE_RECLAIM,
)
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_BUGFIX,
    TASK_METADATA_KEY_DEV,
    TASK_METADATA_KEY_STOP,
    TASK_METADATA_KEY_TEST,
    task_metadata_parse,
    task_metadata_update,
)
from src.project.task.task_report import task_report_write
from src.project.task.task_role import (
    TASK_ROLE_TITLE,
    task_role_of_task,
    task_role_project_work_dir,
)
from src.project.team.team_session import team_session_restart_role

# Кто работает над строкой в этом состоянии. Только для подзадач: роль корневой задачи
# по состоянию не угадывается — планирует её тот, за кем закреплён тип задачи.
_TASK_STOP_STATE_ROLE = {'developing': TASK_DEVELOPER_ROLE, 'testing': TASK_QA_ROLE}


async def task_stop_apply(task_id: int, username: str = '') -> dict:
    """
    Остановить задачу: запретить захват, вернуть работу, погасить оболочки.

    Останавливаем задачу целиком — вместе с подзадачами плана. У строки в `processing`
    своей работы нет, вся она идёт у детей, и без них кнопка на родителе не
    останавливала бы ничего.

    Флажок фазы снимаем тот, который человек на этой вкладке и видит: «в разработку»
    у задачи менеджера, «в тестирование» у задачи разработчика. Иначе снятая остановка
    тут же сработала бы повторно — флажок остался бы стоять и увёл задачу дальше по
    конвейеру сам.

    Returns:
        Пустой dict — задачи нет. Иначе `task_id`, `released` (какие строки вернули и
        куда), `roles` (кому ушёл маркер перезапуска).
    """
    task = await _task_stop_task_get(task_id)
    if not task:
        return {}

    role = await task_role_of_task(task)
    await task_metadata_update(task_id, _task_stop_patch(task, role))

    rows = await _task_stop_inflight_get(task_id)
    released = await _task_stop_release(rows)
    roles = sorted({_task_stop_row_role(row, role) for row in rows})
    await _task_stop_status_pending(task_id)

    if roles:
        work_dir = await task_role_project_work_dir(task.get('project_id'))
        for shell_role in roles:
            await team_session_restart_role(shell_role, work_dir, wait=False)

    who = username or 'пользователь'
    titles = ', '.join(TASK_ROLE_TITLE.get(r, r) for r in roles)
    await task_report_write(task_id, f'{who} остановил задачу'
                                     + (f': работа снята с ролей {titles}' if titles else ''), ok=False)
    for row in released:
        if row['id'] != task_id:
            await task_report_write(row['id'], f'{who} остановил задачу #{task_id} — работа снята', ok=False)

    logger_info(f'[task] task#{task_id}: остановлена ({who}), '
                f'возвращено строк: {len(released)}, оболочки: {", ".join(roles) or "-"}')
    return {'task_id': task_id, 'released': released, 'roles': roles}


async def task_stop_clear(task_id: int, username: str = '') -> bool:
    """
    Снять остановку: строка снова видна захвату.

    Сама ничего не запускает — просто убирает запрет, а работу задаче отдаст ближайший
    тик оркестратора по её же `pipeline_state`, тому самому, куда её вернула остановка.

    Возвращает False, если задача и не была остановлена: зовётся из общего обработчика
    флажков, и без этой проверки отчёт зарастал бы строкой «снял остановку» на каждое
    нажатие любого флажка.
    """
    if not task_id or not await task_stop_is_stopped(task_id):
        return False

    await task_metadata_update(task_id, {TASK_METADATA_KEY_STOP: None})
    who = username or 'пользователь'
    await task_report_write(task_id, f'{who} снял остановку — задача снова в работе', ok=None)
    logger_info(f'[task] task#{task_id}: остановка снята ({who})')
    return True


async def task_stop_is_stopped(task_id: int) -> bool:
    """Остановлена ли строка. Родителя не смотрит — это про саму строку."""
    if not task_id:
        return False

    async with mysql_get_db_async() as db:
        await db.execute('SELECT metadata FROM project_task WHERE id = %s', (task_id,))
        row = await db.fetchone()

    return bool(row) and task_metadata_parse(row['metadata']).get(TASK_METADATA_KEY_STOP) is True


def _task_stop_patch(task: dict, role: str) -> dict:
    """
    Патч пометок для остановки: сам запрет плюс снятый флажок фазы.

    Флажок снимаем тот, который человек на своей вкладке и видит: «в багфикс» у бага,
    «в тестирование» у задачи разработчика, «в разработку» у задачи менеджера. Иначе
    снятая остановка сработала бы повторно — оставшийся флажок увёл бы задачу дальше
    сам, тем же тиком.

    Значения разные не для красоты: у `to_bugfix` и `to_testing` умолчание «включено»,
    и снять их можно только явным `false`; у `to_development` умолчание «выключено»,
    и снятие — это стирание ключа (`None` в JSON_MERGE_PATCH).
    """
    patch = {TASK_METADATA_KEY_STOP: True}
    if role == TASK_BUGFIXER_ROLE:
        patch[TASK_METADATA_KEY_BUGFIX] = False
    elif role == TASK_DEVELOPER_ROLE:
        if not task.get('parent_id'):
            patch[TASK_METADATA_KEY_TEST] = False
    else:
        patch[TASK_METADATA_KEY_DEV] = None
    return patch


async def _task_stop_task_get(task_id: int) -> dict | None:
    if not task_id:
        return None

    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, project_id, parent_id, task_type_id, pipeline_state '
                         '  FROM project_task WHERE id = %s', (task_id,))
        return await db.fetchone()


async def _task_stop_inflight_get(task_id: int) -> list[dict]:
    """Строки задачи и её подзадач, за которыми прямо сейчас думает агент."""
    placeholders = ', '.join(['%s'] * len(TASK_CLAIM_INFLIGHT_STATES))
    async with mysql_get_db_async() as db:
        await db.execute(f'SELECT id, parent_id, pipeline_from_plan, task_type_id, pipeline_state '
                         f'  FROM project_task '
                         f' WHERE (id = %s OR parent_id = %s) AND pipeline_state IN ({placeholders})',
                         (task_id, task_id, *TASK_CLAIM_INFLIGHT_STATES))
        return list(await db.fetchall() or [])


async def _task_stop_release(rows: list[dict]) -> list[dict]:
    """
    Вернуть захваченные строки в состояние, из которого их снова возьмут.

    Блокировку снимаем той же правкой: строка больше не занята, и оставленный
    `pipeline_locked_by` только вводил бы в заблуждение страницу задач.

    `status` правим прямой строкой, а не `task_state_kanban_sql`: тот у остановленной
    строки статус как раз не трогает — на то и заведён.

    Карту возврата выбирает `pipeline_from_plan`, а не наличие родителя. Дочерняя строка
    бывает двух разных пород: строка плана (её и берут Developer/QA) и обычная задача
    дерева, у которой родитель есть, а к плану она отношения не имеет. Вторая живёт по
    состояниям задачи (`planning`, `reviewing`), и по родителю ей досталась бы карта
    подзадач, где таких ключей нет: строка молча пропускалась и оставалась захваченной
    до протухания блокировки — с обещанной остановкой, которой не произошло.
    Слить карты в одну нельзя: `testing` у задачи — фаза «на проверке», а у строки
    плана — захваченная работа, и возвращать их надо в разное.
    """
    released = []
    async with mysql_get_db_async() as db:
        for row in rows:
            state_map = (TASK_CLAIM_SUBTASK_STATE_RECLAIM if row.get('pipeline_from_plan')
                         else TASK_CLAIM_STATE_RECLAIM)
            state_to = state_map.get(row['pipeline_state'])
            if not state_to:
                continue

            await db.execute("UPDATE project_task "
                             "   SET pipeline_state = %s, status = 'pending', "
                             "       pipeline_locked_at = NULL, pipeline_locked_by = '' "
                             " WHERE id = %s AND pipeline_state = %s",
                             (state_to, row['id'], row['pipeline_state']))
            released.append({'id': row['id'], 'state_from': row['pipeline_state'], 'state_to': state_to})

        await db.connection.commit()

    return released


async def _task_stop_status_pending(task_id: int) -> None:
    """
    Человеческий статус остановленной строки — «Ожидает», чем бы она ни была занята.

    Отдельным запросом, а не в `_task_stop_release`: у строки в `processing` (и у
    закрытых состояний вроде `testing` корневой задачи) возвращать нечего — работы в
    полёте у неё своей нет, — а статус человек всё равно ждёт увидеть изменившимся.
    """
    async with mysql_get_db_async() as db:
        await db.execute("UPDATE project_task SET status = 'pending' "
                         " WHERE id = %s AND status NOT IN ('done', 'cancelled')", (task_id,))
        await db.connection.commit()


def _task_stop_row_role(row: dict, task_role: str) -> str:
    """Кто работает над строкой: у подзадачи роль видна по состоянию, у задачи — по типу."""
    return _TASK_STOP_STATE_ROLE.get(row['pipeline_state'], task_role) if row['parent_id'] else task_role
