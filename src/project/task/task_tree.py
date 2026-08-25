"""
Дерево задач: правила, которые должны выполняться независимо от того, кто меняет
`task.parent_id` — форма, drag-n-drop или будущий импорт.

Дерево общее с конвейером: подзадачи из утверждённого плана — такие же дети, только
с меткой `pipeline_from_plan = 1`. Правила ниже про человеческую декомпозицию
«эпик → подзадачи» произвольной глубины и действуют на любых детей одинаково.

Функции принимают уже открытый `db`, а не открывают соединение сами: вызывающий
код держит транзакцию, и вложенный захват из пула на маленьком пуле рискует
встать намертво.
"""

MAX_DEPTH = 5  # глубже дерево перестаёт читаться в таблице, да и смысл теряет


async def task_tree_parent_check(db, task_id: int | None, parent_id: int | None) -> int | None:
    """
    Проверить, что `parent_id` годится в родители для `task_id`.

    `task_id` = None при создании новой задачи — тогда проверять цикл не от чего.

    Returns:
        Нормализованный parent_id (None для корневой задачи).

    Raises:
        ValueError: родителя нет, он в другом проекте, это сама задача, её же
                    потомок (цикл) или уровень вложенности исчерпан.
    """
    if parent_id in (None, '', 0):
        return None

    parent_id = int(parent_id)
    if task_id is not None and parent_id == int(task_id):
        raise ValueError('задача не может быть родителем самой себе')

    await db.execute("SELECT id, project_id, parent_id FROM project_task WHERE id = %s", (parent_id,))
    parent = await db.fetchone()
    if not parent:
        raise ValueError(f'родительская задача #{parent_id} не найдена')

    if await task_tree_depth(db, parent_id) + 1 >= MAX_DEPTH:
        raise ValueError(f'слишком глубокая вложенность (максимум {MAX_DEPTH} уровней)')

    # Цикл: новый родитель не должен лежать в поддереве самой задачи. Идём вверх
    # от родителя — путь к корню короткий, а рекурсивный обход вниз не нужен.
    if task_id is not None:
        current = parent
        for _ in range(MAX_DEPTH + 1):
            if current['parent_id'] is None:
                break
            if int(current['parent_id']) == int(task_id):
                raise ValueError('нельзя перенести задачу внутрь её собственной подзадачи')
            await db.execute("SELECT id, parent_id FROM project_task WHERE id = %s", (current['parent_id'],))
            current = await db.fetchone()
            if not current:
                break

    return parent_id


async def task_tree_depth(db, task_id: int) -> int:
    """Уровень задачи: 0 — корневая, 1 — её подзадача и так далее."""
    depth = 0
    await db.execute("SELECT parent_id FROM project_task WHERE id = %s", (task_id,))
    row = await db.fetchone()
    while row and row['parent_id'] is not None and depth <= MAX_DEPTH:
        depth += 1
        await db.execute("SELECT parent_id FROM project_task WHERE id = %s", (row['parent_id'],))
        row = await db.fetchone()
    return depth


async def task_tree_position_next(db, project_id: int | None, parent_id: int | None) -> int:
    """
    Следующая позиция в пределах своего уровня.

    Позиции нумеруются внутри родителя, а не сквозь весь проект: иначе подзадача,
    добавленная последней, уезжала бы в конец таблицы вместо своей ветки.

    Сравнение проекта NULL-безопасное: «без проекта» хранится как NULL, а обычное
    равенство с NULL не совпадает ни с чем — все такие задачи получали бы позицию 0
    и слипались в одну строку списка.
    """
    if parent_id is None:
        await db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM project_task "
            " WHERE project_id <=> %s AND parent_id IS NULL", (project_id,))
    else:
        await db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM project_task WHERE parent_id = %s", (parent_id,))
    row = await db.fetchone()
    return int(row['pos']) if row else 0

async def task_tree_descendants(db, task_id: int) -> list[int]:
    """
    Строка и всё, что висит под ней, — сверху вниз.

    Нужно перед удалением: `DELETE` уносит поддерево каскадом по `parent_id`, и
    после него спросить, кто там был, уже не у кого. А спросить надо — за каждой
    строкой стоит рабочий каталог на диске, который каскад не убирает.

    Обходим уровнями, а не рекурсивным запросом: глубина дерева ограничена
    (`task_tree_depth`), уровней получается единицы, и обычный `IN` понятнее
    рекурсивного CTE, которого в этой схеме больше нигде нет.
    """
    found = [int(task_id)]
    level = [int(task_id)]
    while level:
        placeholders = ', '.join(['%s'] * len(level))
        await db.execute(
            f"SELECT id FROM project_task WHERE parent_id IN ({placeholders})", level)
        level = [int(row['id']) for row in await db.fetchall() or []]
        found.extend(level)

    return found
