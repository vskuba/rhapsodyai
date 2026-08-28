"""
Спецификации задачи: что именно делаем, чем это считается сделанным.

Зачем. План — это порядок шагов («поправить роутер, потом шаблон»), и его хватает
тому, кто уже знает проект. Исполнителю не хватает: план не говорит, какой контракт у
точки API, что считается ошибкой, чем работа будет доказана. Эти ответы всякий раз
восстанавливались агентом заново, по-своему — и расходились между разработчиком и QA,
потому что каждый читал план и достраивал недостающее сам.

Спецификация закрывает разрыв: один документ, который читают оба, и в нём написано не
«что поправить», а «как это должно себя вести».

**Где лежит.** Файлом в каталоге строки, рядом с журналом (`task_log`): `.task-spec.md`.
Файлом, а не только в базе, потому что читает её агент — а он живёт в каталоге и
читает файлы, а не таблицы. Шаблон закрыт `.gitignore`, поэтому слиянию веток он не
мешает и в коммиты не попадает.

**Две высоты.** У подзадачи — своя, короткая: она покрывает ровно её работу и её
проверку. У родителя — сводная: та же информация по всем подзадачам плюс то, чего в
отдельных нет и быть не может — общая картина, порядок выполнения и зависимости между
ними. Отсюда и польза: по сводной видно, что план сходится как целое, а по частной —
что делать здесь и сейчас.

**Собирается из готового, а не выдумывается заново.** План, цели, зависимости и объём
уже посчитаны на планировании; спецификация их укладывает в один документ. Отдельного
похода в LLM для сборки не нужно — а вот проверка на связность это отдельный вопрос,
и её делает менеджер своим шагом (см. `task_spec_review_prompt`).

Живут ровно столько, сколько каталог: влили ветку — `task_worktree_merge` каталог
снимает, спецификация уходит с ним. Она про то, как работу делать, а у сделанной
работы это уже не спрашивают.
"""
import json
import os

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_depend import task_depend_of, task_depend_tree
from src.project.task.task_plan import task_plan_goals_normalize, task_plan_parse
from src.project.task.task_worktree import task_worktree_path

# Имя файла спецификации в каталоге строки. Рядом с `.task-log.md` и `.task-state.md`
# и по тем же правилам: точка в начале — файл служебный, закрыт `.gitignore`.
TASK_SPEC_FILE = '.task-spec.md'

# Сколько знаков спецификации отдаём странице. Документ читают глазами, и мегабайт
# в браузере не нужен никому; агенту файл достаётся целиком, он читает с диска.
TASK_SPEC_VIEW_MAX = 60000


async def task_spec_build(task_id: int) -> str:
    """
    Собрать спецификацию строки: текст в markdown. Пусто — строки нет.

    Родитель получает сводную (все подзадачи, порядок, зависимости), лист — свою.
    Различаем по наличию детей, а не по типу задачи: подзадача с внуками — тот же
    родитель для них, и сводная ей нужна ровно по той же причине.
    """
    task_id = int(task_id or 0)
    if not task_id:
        return ''

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, parent_id, title, description, goals, pipeline_plan, metadata '
            '  FROM project_task WHERE id = %s', (task_id,))
        task = await db.fetchone()
        if not task:
            return ''

        await db.execute(
            'SELECT id, title, description, goals, pipeline_plan, pipeline_state, position '
            '  FROM project_task WHERE parent_id = %s ORDER BY position, id', (task_id,))
        kids = list(await db.fetchall() or [])

    if kids:
        return await _spec_parent(task, kids)

    return await _spec_leaf(task)


async def task_spec_write(repo_dir: str, task_id: int) -> str:
    """
    Записать спецификацию в каталог строки. Returns: путь файла либо пустая строка.

    Зовётся после создания каталога — из того же места, где заводится сам каталог.
    Каталога нет (строку ещё не брали в работу) — молча ничего не делаем: файл лягут
    следующим кругом, а падать здесь незачем, спецификация не условие работы.

    Сбой записи круг не роняет по той же причине, что и журнал: агент прочтёт план,
    отработает и без неё — хуже, но не сорванно.
    """
    path = task_worktree_path(repo_dir, task_id)
    if not path or not os.path.isdir(path):
        return ''

    try:
        text = await task_spec_build(task_id)
        if not text:
            return ''

        file_path = os.path.join(path, TASK_SPEC_FILE)
        with open(file_path, 'w', encoding='utf-8') as fh:
            fh.write(text)

        return file_path
    except Exception as e:
        logger_info(f'task_spec: спецификация строки {task_id} не записана: '
                    f'{type(e).__name__}: {e}')

        return ''


async def task_spec_read(repo_dir: str, task_id: int) -> dict:
    """
    Спецификация для показа человеку: `{'text', 'path', 'stored'}`.

    Читаем файл, а собираем заново только если его нет: файл — то, что видел агент, и
    показать человеку надо именно это. Пересобранная на лету спецификация отличалась
    бы от той, по которой работали, и разбор «почему сделано не так» шёл бы по чужому
    документу.

    `stored` — файл существует. False означает «собрано сейчас»: каталога ещё нет
    или его уже сняли после слияния.
    """
    path = task_worktree_path(repo_dir, task_id)
    file_path = os.path.join(path, TASK_SPEC_FILE) if path else ''

    if file_path and os.path.isfile(file_path):
        try:
            with open(file_path, encoding='utf-8', errors='replace') as fh:
                return {'text': fh.read()[:TASK_SPEC_VIEW_MAX], 'path': file_path,
                        'stored': True}
        except OSError:
            pass

    return {'text': (await task_spec_build(task_id))[:TASK_SPEC_VIEW_MAX],
            'path': file_path, 'stored': False}


def task_spec_review_prompt(spec: str, title: str) -> str:
    """
    Задание менеджеру: проверить спецификацию на связность. Пусто — проверять нечего.

    Проверку делает LLM, а не код: связность — про смысл. «Подзадача 3 проверяет
    поведение, которого не создаёт ни одна из предыдущих» — такое видно только тому,
    кто прочёл документ целиком.

    Промпт просит не переписывать, а назвать разрывы: переписанная спецификация
    разошлась бы с планом, по которому уже созданы подзадачи, и чинить пришлось бы
    оба документа.
    """
    spec = str(spec or '').strip()
    if not spec:
        return ''

    return (
        f'Прочти спецификацию задачи «{title}» и найди в ней разрывы. Код не трогай.\n\n'
        f'{spec}\n\n'
        'Что искать:\n'
        '- Цель, которую не закрывает ни одна подзадача: работа заявлена, делать её некому.\n'
        '- Подзадача, проверяющая поведение, которого не создаёт ни одна из предыдущих —\n'
        '  и при этом не названная в её зависимостях.\n'
        '- Две подзадачи, правящие одно и то же место: при слиянии веток это конфликт.\n'
        '- Цель, по которой нельзя ответить «да» или «нет»: QA нечем будет принять работу.\n'
        '- Порядок, в котором подзадача идёт раньше той, чей код ей нужен.\n\n'
        'Ответь коротко: списком найденных разрывов, по одному в строке, каждый с\n'
        'номером подзадачи. Разрывов нет — так и напиши одной строкой. Спецификацию\n'
        'не переписывай: по ней уже созданы подзадачи, и переписанная разошлась бы\n'
        'с ними.'
    )


async def _spec_leaf(task: dict) -> str:
    """Спецификация подзадачи: что делать здесь и чем это будет доказано."""
    plan_text, _ = task_plan_parse(task.get('pipeline_plan') or '')
    goals = task_plan_goals_normalize(task.get('goals'))
    deps = (await task_depend_of([int(task['id'])])).get(int(task['id']), [])

    lines = [f"# Спецификация подзадачи #{task['id']} — {task.get('title') or ''}", '']

    if task.get('description'):
        lines += ['## Что делаем', '', str(task['description']).strip(), '']

    if plan_text.strip():
        lines += ['## Порядок работы', '', plan_text.strip(), '']

    lines += ['## Чем считается сделанным', '']
    if goals:
        # Цели — не список пожеланий, а критерии приёмки: по ним QA отвечает «да»
        # или «нет». Поэтому в спецификации они чекбоксами, как в отчёте.
        lines += [f"- [ ] {g.get('text') or ''}" for g in goals]
    else:
        lines.append('_Цели не заданы — QA принимать работу нечем._')
    lines.append('')

    if deps:
        lines += ['## Зависит от', '',
                  'Работа не начнётся, пока не закрыты: '
                  + ', '.join(f'#{d}' for d in deps),
                  '',
                  'Их код приезжает в эту ветку слиянием перед началом круга, '
                  'поэтому файлы предшественников здесь уже есть.', '']

    context = _context_lines(task)
    if context:
        lines += ['## Объём', '', f'Оценка чтения: {context} строк кода.', '']

    return '\n'.join(lines).strip() + '\n'


async def _spec_parent(task: dict, kids: list) -> str:
    """
    Сводная спецификация: все подзадачи, порядок и зависимости в одном документе.

    Здесь есть то, чего нет ни в одной частной: как куски складываются в целое и в
    каком порядке идут. Ради этого сводную и заводят — по ней видно, сходится ли план,
    а не только каждый его кусок по отдельности.
    """
    goals = task_plan_goals_normalize(task.get('goals'))
    plan_text, _ = task_plan_parse(task.get('pipeline_plan') or '')
    graph = await task_depend_tree(int(task['id']))
    by_id = {int(k['id']): k for k in kids}

    lines = [f"# Спецификация задачи #{task['id']} — {task.get('title') or ''}", '',
             f'Подзадач: {len(kids)}. Документ сводный: то же, что в спецификациях '
             f'подзадач, плюс порядок и связи между ними.', '']

    if task.get('description'):
        lines += ['## Задача целиком', '', str(task['description']).strip(), '']

    if plan_text.strip():
        lines += ['## Общий план', '', plan_text.strip(), '']

    if goals:
        lines += ['## Цели задачи', '']
        lines += [f"- [ ] {g.get('text') or ''}" for g in goals]
        lines.append('')

    waves = graph.get('waves') or []
    if waves:
        lines += ['## Порядок выполнения', '']
        if len(waves) == 1:
            lines.append('Все подзадачи независимы — идут параллельно, '
                         'настолько, насколько хватает оболочек и моделей.')
        else:
            lines.append('Волна — то, что идёт параллельно; следующая ждёт предыдущую.')
            lines.append('')
            for number, wave in enumerate(waves, 1):
                names = ', '.join(f"#{i} {by_id.get(i, {}).get('title') or ''}".strip()
                                  for i in wave)
                lines.append(f'{number}. {names}')
        lines.append('')

    if graph.get('cycle'):
        lines += ['## Кольцо зависимостей', '',
                  'Эти подзадачи ссылаются друг на друга и не начнутся никогда: '
                  + ', '.join(f'#{i}' for i in graph['cycle']),
                  '', 'План нужно переразбить.', '']

    lines += ['## Подзадачи', '']
    depends = await task_depend_of([int(k['id']) for k in kids])
    for kid in kids:
        kid_id = int(kid['id'])
        kid_goals = task_plan_goals_normalize(kid.get('goals'))
        kid_plan, _ = task_plan_parse(kid.get('pipeline_plan') or '')
        deps = depends.get(kid_id, [])

        lines.append(f"### #{kid_id} — {kid.get('title') or ''}")
        lines.append('')
        if kid.get('description'):
            lines += [str(kid['description']).strip(), '']
        if deps:
            lines += [f"Ждёт: {', '.join(f'#{d}' for d in deps)}", '']
        if kid_plan.strip():
            lines += ['Порядок работы:', '', kid_plan.strip(), '']
        lines.append('Чем считается сделанным:')
        lines.append('')
        if kid_goals:
            lines += [f"- [ ] {g.get('text') or ''}" for g in kid_goals]
        else:
            lines.append('_Цели не заданы — QA принимать работу нечем._')
        lines.append('')

    return '\n'.join(lines).strip() + '\n'


def _context_lines(task: dict) -> int:
    """Оценка объёма чтения из мешка подзадачи. Ноль — менеджер её не дал."""
    try:
        meta = task.get('metadata')
        meta = json.loads(meta) if isinstance(meta, str) and meta.strip() else (meta or {})

        return int(meta.get('context_lines') or 0)
    except (TypeError, ValueError):
        return 0
