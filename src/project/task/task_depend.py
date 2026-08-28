"""
Зависимости между задачами: кто кого ждёт.

Зачем. План менеджера — плоский список подзадач, и конвейер брал их в работу разом,
как только план разложен. Но подзадачи планом не равноправны: «написать тесты
вкладки» не начать раньше, чем вкладка существует, а «проверить на стенде» — раньше
обеих. Живой повод: задача #2438 разложилась на три подзадачи, где третья явно
опиралась на первую, и все три ушли в работу одновременно.

Что меняется. Подзадача ждёт, пока не закрыты те, от кого она зависит; всё остальное
идёт параллельно, ровно как раньше. Параллельность не отменяется — из неё вычитаются
связи, и только они.

Откуда берутся связи. Их называет менеджер на разбиении: у каждой подзадачи плана
появилось поле `depends_on` — номера соседей по списку, без которых её не начать.
Номера в плане позиционные (1, 2, 3…), потому что id строк на момент планирования
ещё нет; в id их переводит `task_depend_set` при разборе плана на подзадачи.

Циклы ловятся здесь же, а не триггером в базе: план с циклом не выполнить в принципе,
и о нём нужно сказать человеку, а не тихо развернуть половину связей.

Соседний модуль — `task_claim`: там отбор работы, и условие «предшественники закрыты»
живёт в нём одной строкой SQL (`task_depend_ready_sql`), чтобы не разъехаться с этим
файлом.
"""
import os

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Состояния, в которых предшественник считается пройденным. `done` — работа сделана;
# `no_code_for_testing` — делать было нечего (код уже в master), и ждать такую
# подзадачу значит ждать вечно.
#
# `blocked` и `failed` сюда не входят намеренно: подзадача, упавшая насовсем, держит
# зависящих от неё — и правильно держит. Иначе следующая начала бы работу поверх
# кода, которого нет, и провалилась бы второй, унеся с собой ещё и попытку.
TASK_DEPEND_DONE_STATES = ('done', 'no_code_for_testing')


def task_depend_ready_sql(column: str = 'project_task.id') -> str:
    """
    Условие «все предшественники закрыты» для отбора работы.

    Подзапросом, а не join'ом: у большинства подзадач связей нет вовсе, и join
    размножал бы строки там, где проверять нечего. `NOT EXISTS` по индексу
    первичного ключа заканчивается на первом же незакрытом предшественнике.

    Строка без связей проходит условие всегда — так плоские планы, которых
    большинство, работают ровно как до появления зависимостей.

    `column` **обязан** быть с именем таблицы или её алиасом. Голое `id` MySQL
    разрешит в пользу таблицы подзапроса — а там оно своё, и условие тихо станет
    тождеством: подзадача уйдёт в работу раньше предшественника, ничего не сообщив.
    Поймано тестом `test_waiting_subtask_is_filtered_out`, и умолчание здесь
    квалифицированное именно поэтому.
    """
    states = ', '.join(f"'{state}'" for state in TASK_DEPEND_DONE_STATES)

    return (
        f'NOT EXISTS (SELECT 1 FROM project_task_depend dep '
        f'             JOIN project_task dep_p ON dep_p.id = dep.depends_on_id '
        f'            WHERE dep.task_id = {column} '
        f'              AND COALESCE(dep_p.pipeline_state, \'\') NOT IN ({states}))'
    )


async def task_depend_set(task_id: int, depends_on: list) -> int:
    """
    Записать зависимости подзадачи, заменив прежние. Returns: сколько связей записано.

    Замена, а не добавление: план пересматривают, и связи прошлого разбора не должны
    пережить новый — иначе подзадача ждала бы соседа, которого в плане уже нет.

    Себя из списка выбрасываем молча: менеджер иногда включает подзадачу в её же
    зависимости, и падать из-за этого незачем — смысла в такой связи нет никакого.

    Несуществующие номера тоже отсеиваем: FK отверг бы всю вставку целиком, и одна
    опечатка модели лишила бы связей весь план.
    """
    task_id = int(task_id or 0)
    if not task_id:
        return 0

    wanted = {int(x) for x in (depends_on or []) if str(x).strip().lstrip('-').isdigit()}
    wanted.discard(task_id)

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project_task_depend WHERE task_id = %s', (task_id,))
        if wanted:
            placeholders = ', '.join(['%s'] * len(wanted))
            await db.execute(
                f'SELECT id FROM project_task WHERE id IN ({placeholders})', tuple(sorted(wanted)))
            alive = {int(row['id']) for row in await db.fetchall() or []}
            rows = [(task_id, dep) for dep in sorted(alive)]
            if rows:
                await db.executemany(
                    'INSERT INTO project_task_depend (task_id, depends_on_id) VALUES (%s, %s)',
                    rows)
        await db.connection.commit()

    return len(wanted)


async def task_depend_of(task_ids: list) -> dict[int, list[int]]:
    """Кого ждёт каждая из строк: `{task_id: [depends_on_id, ...]}`."""
    ids = [int(x) for x in (task_ids or []) if int(x or 0)]
    if not ids:
        return {}

    async with mysql_get_db_async() as db:
        placeholders = ', '.join(['%s'] * len(ids))
        await db.execute(
            f'SELECT task_id, depends_on_id FROM project_task_depend '
            f' WHERE task_id IN ({placeholders}) ORDER BY depends_on_id', tuple(ids))
        rows = await db.fetchall() or []

    out: dict[int, list[int]] = {}
    for row in rows:
        out.setdefault(int(row['task_id']), []).append(int(row['depends_on_id']))

    return out


async def task_depend_tree(parent_id: int) -> dict:
    """
    Граф зависимостей дерева задачи — для страницы и для проверки плана.

    Returns:
        nodes: `[{'id', 'title', 'state', 'depends_on': [...], 'blocks': [...]}]`
            в порядке позиции; `blocks` — кого разблокирует закрытие этой строки.
        waves: список списков id — что можно вести параллельно. Первая волна ни от
            кого не зависит, вторая ждёт первую и так далее.
        cycle: список id, замкнутых в кольцо, либо пустой список.

    Волны считаются здесь, а не в отборе работы: отбору достаточно «предшественники
    закрыты», а волны нужны человеку — по ним видно, во сколько заходов пойдёт план и
    что чему мешает.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, title, pipeline_state, position FROM project_task '
            ' WHERE parent_id = %s ORDER BY position, id', (int(parent_id),))
        rows = await db.fetchall() or []

    nodes = {int(r['id']): {'id': int(r['id']), 'title': str(r['title'] or ''),
                            'state': str(r['pipeline_state'] or ''),
                            'depends_on': [], 'blocks': []} for r in rows}
    if not nodes:
        return {'nodes': [], 'waves': [], 'cycle': []}

    depends = await task_depend_of(list(nodes))
    for task_id, deps in depends.items():
        if task_id not in nodes:
            continue
        # Связь наружу дерева (подзадача ждёт чужую задачу) в графе не рисуем: узла
        # для неё здесь нет, а выдумывать его значит показывать половину чужого дерева.
        inside = [dep for dep in deps if dep in nodes]
        nodes[task_id]['depends_on'] = inside
        for dep in inside:
            nodes[dep]['blocks'].append(task_id)

    return {'nodes': list(nodes.values()), **_waves_build(nodes)}


async def task_depend_blocked_by(task_id: int) -> list[dict]:
    """
    Незакрытые предшественники строки: `[{'id', 'title', 'state'}]`.

    Нужен странице и отчёту: «ждёт #2465» понятнее, чем просто «ждёт». Пусто — путь
    свободен, и если работа всё равно не идёт, дело не в зависимостях.
    """
    states = ', '.join(['%s'] * len(TASK_DEPEND_DONE_STATES))
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT p.id, p.title, p.pipeline_state FROM project_task_depend d '
            '  JOIN project_task p ON p.id = d.depends_on_id '
            f' WHERE d.task_id = %s AND COALESCE(p.pipeline_state, \'\') NOT IN ({states}) '
            ' ORDER BY p.position, p.id',
            (int(task_id), *TASK_DEPEND_DONE_STATES))
        rows = await db.fetchall() or []

    return [{'id': int(r['id']), 'title': str(r['title'] or ''),
             'state': str(r['pipeline_state'] or '')} for r in rows]


def task_depend_plan_links(subtasks: list) -> dict[int, list[int]]:
    """
    Перевести `depends_on` плана из позиций в позиции же, отсеяв негодное.

    Менеджер называет зависимости номерами по списку (1, 2, 3…): id строк на момент
    планирования ещё не существует. Здесь только чистка — перевод в id делает
    `task_depend_apply`, когда строки уже созданы и их номера известны.

    Возвращаем `{позиция: [позиции]}`, нумерация с нуля — как в самом списке.

    Что отсеиваем: себя (связь ни о чём), номера вне списка (опечатка модели) и
    ссылки вперёд. Последнее — не придирка: `depends_on` описывает порядок работы, и
    ссылка на подзадачу, идущую позже, означает, что менеджер сам не решил, что за
    чем; принять её значит завести цикл на ровном месте.
    """
    links: dict[int, list[int]] = {}
    for index, item in enumerate(subtasks or []):
        raw = item.get('depends_on') if isinstance(item, dict) else None
        if isinstance(raw, str):
            raw = [part for part in raw.replace(',', ' ').split() if part]
        wanted = []
        for value in (raw or []):
            try:
                number = int(str(value).strip())
            except (TypeError, ValueError):
                continue
            # Номера в плане с единицы — так их пишет менеджер и так их читает человек.
            position = number - 1
            if 0 <= position < index:
                wanted.append(position)
        if wanted:
            links[index] = sorted(set(wanted))

    return links


async def task_depend_apply(parent_id: int, links: dict) -> int:
    """
    Разложить позиционные связи плана на созданные строки. Returns: сколько записано.

    Зовётся сразу после `task_state_subtasks_create`: строки уже есть, их порядок —
    тот же `position`, что и в плане, и по нему позиции переводятся в id.

    Сбой связей план не отменяет: подзадачи созданы, работа пойдёт — просто вся разом,
    как до появления зависимостей. Это хуже задуманного, но лучше развёрнутого плана.
    """
    if not links:
        return 0

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT id, position FROM project_task '
                ' WHERE parent_id = %s AND pipeline_from_plan = 1 ORDER BY position, id',
                (int(parent_id),))
            rows = await db.fetchall() or []

        by_position = {int(row['position']): int(row['id']) for row in rows}
        written = 0
        for position, deps in links.items():
            task_id = by_position.get(int(position))
            if not task_id:
                continue
            ids = [by_position[d] for d in deps if d in by_position]
            if ids:
                written += await task_depend_set(task_id, ids)

        if written:
            logger_info(f'[task] task#{parent_id}: записано {written} зависимостей между подзадачами')

        return written
    except Exception as e:
        logger_info(f'[task] task#{parent_id}: зависимости не записаны: {type(e).__name__}: {e}')

        return 0


def _waves_build(nodes: dict) -> dict:
    """
    Разложить граф на волны и найти цикл, если он есть.

    Волна — то, что можно вести параллельно: первая ни от кого не зависит, вторая
    ждёт первую. Обход Кана: на каждом шаге берём всё, у чего не осталось незакрытых
    входящих связей.

    Не разошлось — остаток замкнут в кольцо, и он же уходит в `cycle`: показать
    человеку, какие подзадачи ссылаются друг на друга, полезнее, чем сказать «план
    неверен».
    """
    pending = {node_id: set(node['depends_on']) for node_id, node in nodes.items()}
    waves, guard = [], 0
    while pending and guard <= len(nodes):
        guard += 1
        ready = sorted(node_id for node_id, deps in pending.items() if not deps)
        if not ready:
            break
        waves.append(ready)
        for node_id in ready:
            pending.pop(node_id, None)
        for deps in pending.values():
            deps.difference_update(ready)

    return {'waves': waves, 'cycle': sorted(pending)}


async def task_depend_merge_upstream(repo_dir: str, task_id: int) -> dict:
    """
    Влить в ветку подзадачи код тех, от кого она зависит. Returns: что получилось.

    Зачем. Зависимость — это про код: подзадача «написать тесты вкладки» опирается на
    файлы, которых до соседней подзадачи не существует. Ждать её закрытия мало —
    работа предшественника лежит в **его** ветке, а не в master, и исполнитель без
    слияния увидит пустое место там, где рассчитывал на готовое.

    Почему слияние, а не выкладка от чужой ветки. У каждой подзадачи свой каталог со
    своими журналами, состоянием и спецификациями; заводить его от соседа значило бы
    тащить и их. А рабочий код накладывается ровно слиянием — служебные файлы
    (`.task-log.md`, `.task-state.md` и соседи) закрыты `.gitignore` и в коммиты не
    попадают, поэтому поперёк слияния не встают.

    Конфликт не разрешаем и не гадаем: откатываем слияние и говорим об этом. Две
    подзадачи, поправившие одно место, — это ошибка разбиения, и чинить её должен
    менеджер переразбиением, а не разработчик посреди круга.

    Returns:
        merged: имена веток, которые влились.
        skipped: те, чья ветка ещё не существует (предшественник не писал кода).
        conflict: ветка, на которой слияние развернули; пустая строка — конфликта нет.
        error: текст ошибки git, если она была.
    """
    from src.project.task.task_worktree import (task_worktree_branch, task_worktree_git,
                                                task_worktree_path)

    result = {'merged': [], 'skipped': [], 'conflict': '', 'error': ''}
    path = task_worktree_path(repo_dir, task_id)
    if not path or not os.path.isdir(path):
        return result

    deps = (await task_depend_of([int(task_id)])).get(int(task_id), [])
    if not deps:
        return result

    for dep_id in deps:
        branch = task_worktree_branch(dep_id)
        if not branch:
            continue

        # Ветки может не быть вовсе: предшественник закрылся как `no_code_for_testing`
        # — работа была уже в master, и вливать нечего.
        code, _ = await task_worktree_git(path, 'rev-parse', '--verify', branch)
        if code:
            result['skipped'].append(branch)
            continue

        code, out = await task_worktree_git(
            path, 'merge', '--no-edit', '-m', f'Код подзадачи #{dep_id}', branch)
        if not code:
            result['merged'].append(branch)
            continue

        # Слияние не прошло — разворачиваем, чтобы каталог остался рабочим: круг
        # начнётся, упрётся в отсутствие кода и честно вернёт «не сошлось», а не
        # утонет в конфликтных маркерах посреди файлов.
        await task_worktree_git(path, 'merge', '--abort')
        result['conflict'] = branch
        result['error'] = str(out or '')[:400]
        logger_info(f'[task] subtask#{task_id}: ветка {branch} не влилась, конфликт')
        break

    if result['merged']:
        logger_info(f"[task] subtask#{task_id}: влиты ветки предшественников: "
                    f"{', '.join(result['merged'])}")

    return result
