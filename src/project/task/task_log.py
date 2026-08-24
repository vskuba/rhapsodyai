"""
Журнал работы по строке задачи: кто, когда и что сделал за каждый круг.

Зачем. Прогон агента обрывается по таймауту шага, конвейер уводит строку в повтор
и перезапускает оболочку — контекст гибнет, и следующий круг начинает с нуля.
Поймано живьём: подзадача #1028 закоммитила работу в первом круге, таймаут срубил
её на пуше, и второй круг потратил шестнадцать минут, чтобы заново выяснить, что
работа уже сделана.

**Журнал ведёт код, а не агент.** Просить агента писать его самому значило бы
добавить ещё одно требование в промпт, где их и так много, — а промпт с десятком
требований LLM выполняет через раз (ровно поэтому JSON у ролей спрашивается
отдельным шагом). Брать при этом неоткуда и не нужно: шаги workflow вместе с
ответами уже лежат в трассе, `task_log_write_run` их оттуда и перекладывает.

Времена показываются в поясе настройки `timezone`: трассу пишет MySQL, а он в
контейнере живёт по UTC (см. `.claude/docs-common/datetime_rules.md`).

Отсюда главное свойство: журнал переживает обрыв. У прогона, срубленного
таймаутом, ответа нет, но пройденные шаги в трассе остались — и попадут в журнал.
Агента промпт просит об одном: прочитать журнал прежде, чем лезть в проект.

Файлов два, у каждого своя роль:

* `.task-log.md`   — хронология, только дописывается. Строка на шаг:
                     `ЧЧ:ММ:СС ключевое-слово шаг [время]: суть ответа`.
                     Читается и человеком на вкладке «Журналы», и следующим кругом.
                     Файл дописывается по концу круга, поэтому `task_log_read`
                     подмешивает к нему шаги прогонов, которые идут прямо сейчас:
                     круг QA тянется часами, и всё это время страница была пуста.
* `.task-state.md` — состояние, перезаписывается целиком: последний круг, его итог
                     и что лежит в ветке. Короткое — чтобы возобновляющий круг
                     обошёлся одним чтением.

Где лежат — в корне каталога строки (`task_worktree`), там же работает агент.
Каталог заводится всем, кого берёт конвейер, включая задачу под менеджером: номера
строки для этого достаточно, а одно правило вместо двух избавляет от развилки
«у кого каталог есть, а у кого нет».

Живут ровно столько, сколько каталог. Влили ветку — `task_worktree_merge` каталог
снимает, журнал уходит с ним: он про ход работы, а у законченной работы ход уже
не спрашивают.

Роли пишут в один файл: конвейер держит строку либо в `developing`, либо в
`testing`, одновременной записи не бывает, а общая хронология ценнее разделённой —
QA видит, что делал разработчик, и наоборот.
"""
import ast
import json
import os
from datetime import datetime

from datetime_.datetime_ import datetime_offset_apply
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_get
from src.project.task.task_worktree import (TASK_WORKTREE_BASE_DIR,
                                            task_worktree_base_branch,
                                            task_worktree_git,
                                            TASK_WORKTREE_DIR_TEMPLATE,
                                            task_worktree_path)

# Имена файлов. Шаблон `.task-*.md` закрыт в `.gitignore`: это следы процесса, а
# не результат работы, и в коммит с merge request им нельзя.
TASK_LOG_FILE = '.task-log.md'
TASK_STATE_FILE = '.task-state.md'
TASK_LOG_FILES = (TASK_LOG_FILE, TASK_STATE_FILE)

# Каталог и префикс имени берём у `task_worktree`: перебор каталогов обязан
# находить ровно то, что тот создаёт. Префикс — шаблон без подстановки, до
# номера строки.
TASK_LOG_WORKTREES_DIR = TASK_WORKTREE_BASE_DIR
TASK_LOG_WORKTREE_PREFIX = TASK_WORKTREE_DIR_TEMPLATE.split('{')[0]

# Сколько символов ответа шага уносим в строку журнала. Строка обязана читаться
# глазами целиком, а ответы у ролей на десятки килобайт: в журнал идёт суть,
# полный текст остаётся в трассе (`/admin/workflow_trace`).
TASK_LOG_STEP_MAX_CHARS = 220

# Ключи ответа, в которых лежит смысл: их роли кладут в JSON-структуру шага.
# Порядок важен — первым идёт то, что короче и понятнее человеку.
TASK_LOG_ANSWER_KEYS = ('summary', 'verdict', 'plan_text', 'plan', 'error', 'report',
                        'critique', 'evidence')

# Потолок чтения. Журнал растёт кругами, а на страницу задач он идёт целиком в
# ответе API — отдаём хвост, а не весь файл.
TASK_LOG_READ_MAX_CHARS = 40000


def task_log_dir(repo_dir: str, task_id) -> str:
    """Каталог строки, где лежат журнал и состояние."""
    root = str(repo_dir or '').strip().rstrip('/') or os.getcwd()

    return task_worktree_path(root, int(task_id or 0))


async def task_log_read(repo_dir: str, task_id) -> dict:
    """
    Журнал и состояние строки для страницы задач — вместе с идущим прогоном.

    Файл дописывается по концу круга, и одного его человеку мало: круг QA идёт
    часами, а на странице всё это время было пусто — «QA работает постоянно, а в
    журнале ничего». Поэтому к записанному добавляем шаги прогонов, которые прямо
    сейчас в работе: их трасса уже пишется движком пошагово, и брать её оттуда
    ничего не стоит.

    Задвоения не будет: живьём показываем только незакрытые трассы, а закрытая
    приходит из файла.

    Returns:
        `{'log': str, 'state': str, 'dir': str, 'running': bool}` — пустые строки,
        если ни файла, ни идущего прогона нет. Это не ошибка: строка могла ещё не
        браться в работу, а каталог — уже уехать после слияния.
    """
    directory = task_log_dir(repo_dir, task_id)
    log = _read_tail(os.path.join(directory, TASK_LOG_FILE))

    live = await _live_block(task_id)
    if live:
        log = f'{log}\n{live}' if log else live

    return {
        'log': log,
        'state': _read_tail(os.path.join(directory, TASK_STATE_FILE)),
        'dir': directory,
        'running': bool(live),
    }


async def _live_block(task_id) -> str:
    """
    Шаги прогонов строки, которые идут прямо сейчас.

    Собираются из трассы, а не из файла: файл пишется по концу круга, а увидеть,
    чем агент занят, человек хочет пока тот занят. Смещение читаем то же, что и
    у записанного, иначе живой блок разъехался бы с остальным журналом на часы.
    """
    runs = await _runs_active(task_id)
    if not runs:
        return ''

    offset = await setting_get('timezone', '+0')
    blocks = []
    for run in runs:
        steps = await _trace_steps(str(run.get('session_uuid') or ''))
        for step in steps:
            step['created_at'] = datetime_offset_apply(step.get('created_at'), offset)

        started = datetime_offset_apply(run.get('started_at'), offset)
        lines = [f"\n## идёт сейчас · {run.get('role') or 'агент'} · "
                 f"{started.strftime('%Y-%m-%d %H:%M') if started else ''}\n"]
        lines += [_step_line(step) for step in steps if not _step_skip(step)]
        # Шагов может не быть вовсе: прогон только начался. Сам заголовок при этом
        # новость — по нему видно, что строка не брошена, а в работе.
        blocks.append(''.join(lines))

    return ''.join(blocks)


async def _runs_active(task_id) -> list[dict]:
    """
    Незакрытые трассы строки и чья это роль.

    Ищем по переменным прогона: у подзадачи это `subtask_id`, у задачи под
    менеджером — `task_id`. Разделять обязательно: в трассе подзадачи лежит и
    номер её родителя, и без второго условия задача забирала бы себе прогоны
    всех своих подзадач.

    Роль берём из тех же переменных (`task_shell_role`) — в самой трассе её нет.
    """
    task_id = int(task_id or 0)
    if not task_id:
        return []

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT session_uuid, started_at, variables_start "
            "  FROM agent_workflow_trace "
            " WHERE status = 'running' "
            "   AND (variables_start LIKE %s "
            "        OR (variables_start LIKE %s AND variables_start NOT LIKE %s)) "
            " ORDER BY id",
            (f'%"subtask_id": "{task_id}"%',
             f'%"task_id": "{task_id}"%', '%"subtask_id": "%'))
        rows = await db.fetchall() or []

    runs = []
    for row in rows:
        variables = _dict_parse(str(row.get('variables_start') or '')) or {}
        runs.append({'session_uuid': row.get('session_uuid'),
                     'started_at': row.get('started_at'),
                     'role': str(variables.get('task_shell_role') or '')})

    return runs


def task_log_list(repo_dir: str) -> list[dict]:
    """
    Строки, у которых есть журнал: что показывать на странице логов без выбора задачи.

    Идём по каталогам подзадач, а не по таблице: журнал живёт на диске, и таблица о
    нём ничего не знает. Заодно это честный ответ на вопрос «какие логи сейчас
    вообще есть» — влитые подзадачи оттуда пропадают вместе с каталогом.

    Returns: `[{'task_id', 'bytes', 'updated_at'}]`, свежие первыми. Названия задач
    подставляет вызывающий: имена лежат в БД, а этот модуль про файлы.
    """
    root = str(repo_dir or '').strip().rstrip('/') or os.getcwd()
    base = os.path.join(root, TASK_LOG_WORKTREES_DIR)
    if not os.path.isdir(base):
        return []

    items = []
    for name in os.listdir(base):
        if not name.startswith(TASK_LOG_WORKTREE_PREFIX):
            continue
        task_id = name[len(TASK_LOG_WORKTREE_PREFIX):]
        if not task_id.isdigit():
            continue

        newest, total = 0.0, 0
        for file_name in TASK_LOG_FILES:
            try:
                info = os.stat(os.path.join(base, name, file_name))
            except OSError:
                continue
            newest = max(newest, info.st_mtime)
            total += info.st_size

        if not total:
            continue
        items.append({'task_id': int(task_id), 'bytes': total,
                      'updated_at': datetime.fromtimestamp(newest).strftime('%Y-%m-%d %H:%M:%S')})

    return sorted(items, key=lambda item: item['updated_at'], reverse=True)


async def task_log_write_run(repo_dir: str, task_id, session_uuid: str,
                             role: str, attempt_no: int, outcome: str) -> int:
    """
    Дописать в журнал строки о только что закончившемся прогоне роли.

    Пишет код, а не агент, и это осознанно. Просить агента вести журнал самому
    значит добавить ещё одну просьбу в промпт, где их и так много, — а промпт с
    десятком требований LLM выполняет через раз (ровно поэтому JSON у ролей
    спрашивается отдельным шагом). Здесь же брать нечего: шаги workflow вместе с
    ответами уже лежат в трассе, остаётся переложить их в журнал.

    Главное следствие — журнал переживает обрыв. Прогон, срубленный таймаутом,
    ответа не вернул, но шаги, что успели пройти, в трассе есть: у сорвавшегося
    круга подзадачи #1028 там остались и проверка среды, и весь разбор.

    Args:
        session_uuid: по нему находится трасса прогона. Агентные модули отдают
            его в результате, потому что сами же и заводят.
        outcome: чем кончился круг, человеческой строкой — она станет последней
            записью.

    Returns: сколько строк дописали. Ноль — трассы не нашлось или каталога нет.
    """
    directory = task_log_dir(repo_dir, task_id)
    if not directory or not os.path.isdir(directory):
        return 0

    steps = await _trace_steps(str(session_uuid or ''))
    if not steps:
        return 0

    # Время трассы пишет MySQL, а он в контейнере живёт по UTC. Человек сверяет
    # журнал с часами на стене, поэтому показываем в поясе настройки `timezone`.
    # Читаем её один раз на прогон: меток в круге десятки.
    offset = await setting_get('timezone', '+0')
    for step in steps:
        step['created_at'] = datetime_offset_apply(step.get('created_at'), offset)

    started = steps[0].get('created_at')
    head = (f"\n## круг {int(attempt_no or 0)} · {role}{_retry_mark(directory, attempt_no, role)} · "
            f"{started.strftime('%Y-%m-%d %H:%M') if started else ''}\n")

    lines = [head]
    for step in steps:
        if _step_skip(step):
            continue
        lines.append(_step_line(step))
    lines.append(_outcome_line(steps[-1].get('created_at'), outcome))

    try:
        with open(os.path.join(directory, TASK_LOG_FILE), 'a', encoding='utf-8') as fh:
            fh.write(''.join(lines))
    except OSError as e:
        # Журнал вспомогательный: не записался — круг всё равно состоялся.
        logger_info(f'task_log: журнал строки {task_id} не дописан: {type(e).__name__}: {e}')
        return 0

    await _state_write(directory, task_id, role, attempt_no, outcome, steps)

    return len(lines) - 1


async def _state_write(directory: str, task_id, role: str, attempt_no: int,
                       outcome: str, steps: list[dict]) -> None:
    """
    Перезаписать состояние: с чего начинать следующему кругу.

    Отдельно от журнала, потому что читается иначе. Журнал длинный и растёт, а
    сюда возобновляющий круг заглядывает один раз: последний исход и что лежит в
    ветке. Перезаписью, а не дописыванием: устаревшее состояние хуже пустого —
    по нему круг пойдёт доделывать сделанное.

    Что осталось, кодом не вывести — это суждение. Зато видно объективное: где
    круг встал и какие коммиты уже есть. Остальное следующий круг возьмёт из
    журнала, ссылку на который тут и оставляем.
    """
    done = [step for step in steps if not _step_failed(step) and not _step_skip(step)]
    last = done[-1] if done else None
    commits = await _branch_commits(directory)

    text = (f'# Строка {task_id} · последний круг {int(attempt_no or 0)} · {role}\n\n'
            f'## Итог круга\n{_one_line(outcome) or "—"}\n\n'
            f'## Докуда дошли\n'
            f'{_one_line(last.get("step_title")) if last else "ни один шаг не завершился"}\n\n'
            f'## Что лежит в ветке\n{commits or "коммитов нет"}\n\n'
            f'Подробности по шагам — в {TASK_LOG_FILE}.\n')

    try:
        with open(os.path.join(directory, TASK_STATE_FILE), 'w', encoding='utf-8') as fh:
            fh.write(text)
    except OSError as e:
        logger_info(f'task_log: состояние строки {task_id} не записано: {type(e).__name__}: {e}')


async def _branch_commits(directory: str) -> str:
    """
    Коммиты ветки строки поверх главной — самое честное «что уже сделано».

    Через `task_worktree_git`: там решены запуск от владельца каталога (иначе git
    отвечает «dubious ownership») и обход uvloop, который не принимает `user` у
    `create_subprocess_exec`. Сбой git — пустая строка: состояние вспомогательное.
    """
    base = await task_worktree_base_branch(directory)
    code, out = await task_worktree_git(directory, 'log', '--oneline', '--no-decorate',
                                        f'{base}..HEAD')

    return out.strip() if code == 0 else ''


def _retry_mark(directory: str, attempt_no, role: str) -> str:
    """
    Пометка «повтор N», когда круг с тем же номером уже есть в журнале.

    Технический повтор круг не жжёт — счётчик попыток при нём не растёт, и это
    правильно: работы не было, жечь нечего. Но в журнале два блока подряд
    оказывались одинаково подписаны «круг 1 · developer», и человек не понимал,
    почему одно и то же случилось дважды. Считаем прежние блоки и подписываем.
    """
    head = f'## круг {int(attempt_no or 0)} · {role}'
    try:
        with open(os.path.join(directory, TASK_LOG_FILE), encoding='utf-8') as fh:
            seen = fh.read().count(head)
    except OSError:
        return ''

    return f' · повтор {seen + 1}' if seen else ''


async def _trace_steps(session_uuid: str) -> list[dict]:
    """Шаги трассы прогона по его сессии, в порядке выполнения."""
    if not session_uuid:
        return []

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT s.step_title, s.status, s.duration_ms, s.output, s.error, s.created_at "
            "  FROM agent_workflow_trace_step s "
            "  JOIN agent_workflow_trace r ON r.id = s.run_id "
            " WHERE r.session_uuid = %s ORDER BY s.exec_index",
            (session_uuid,))
        return [dict(row) for row in (await db.fetchall() or [])]


def _step_line(step: dict) -> str:
    """
    Шаг трассы одной строкой журнала: время, ключевое слово, шаг, время, суть.

    Ключевых слов шесть, те же, что разбирает вкладка «Журналы». Ошибка шага и
    сорвавшийся вызов оболочки — `затык`: по нему следующий круг и ищет, обо что
    споткнулся прошлый.
    """
    at = step.get('created_at')
    stamp = at.strftime('%H:%M:%S') if at else '--:--:--'
    text = _one_line(step.get('error') or '') or _answer_text(step.get('output'))
    keyword = 'затык' if _step_failed(step) else 'сделал'

    seconds = int((step.get('duration_ms') or 0) / 1000)
    spent = f' [{seconds // 60} мин]' if seconds >= 60 else (f' [{seconds}с]' if seconds else '')
    title = str(step.get('step_title') or 'шаг')

    return f'{stamp}  {keyword:<9} {title}{spent}: {text[:TASK_LOG_STEP_MAX_CHARS]}\n'


def _step_skip(step: dict) -> bool:
    """
    Служебный шаг, которому в журнале не место.

    Шаги сборки промпта и счётчиков ничего не делают с точки зрения работы: они
    подставляют переменные и возвращают пустоту. В журнале они дают строку без
    содержания на каждую вторую позицию и топят в себе настоящие события.
    """
    if _one_line(step.get('error')):
        return False

    output = _one_line(step.get('output'))
    # Счётчик круга возвращает голое число: для движка это состояние, для журнала —
    # строка без содержания между двумя настоящими событиями.
    return not output or output.isdigit()


def _step_failed(step: dict) -> bool:
    """
    Шаг не сработал — включая случай, когда движок счёл его успешным.

    Вызов оболочки возвращает свой статус внутри ответа: агент не ответил за
    отведённое время — это `timeout`, мёртвая оболочка — `failed` или
    `no_session`. Для движка шаг при этом успешен, инструмент же отработал; для
    журнала — затык, и человек ищет в журнале именно его.
    """
    if str(step.get('status') or '') == 'error':
        return True

    output = str(step.get('output') or '')

    if any(f"'status': '{bad}'" in output or f'"status": "{bad}"' in output
           for bad in ('timeout', 'failed', 'no_session', 'busy')):
        return True

    # Шаг-заглушка «роль недоступна» возвращает готовый отчёт с `ok: false`:
    # для движка это успешная подстановка, для работы — несостоявшийся прогон.
    return "'ok': false" in output.lower() or '"ok": false' in output.lower()


def _answer_text(output) -> str:
    """
    Суть ответа шага: из результата инструмента достаём то, что сказал агент.

    Разбираем, а не выковыриваем регулярным выражением. Ответ вызова оболочки —
    это repr словаря, внутри которого `response` сам бывает JSON-ом, да ещё в
    markdown-заборе. Регулярка на таком спотыкалась о первую же кавычку внутри
    значения, и в журнал уезжала одна скобка вместо плана на восемь шагов.

    Разбор не удался (ответ обрезан трассой, формат неожиданный) — отдаём текст
    как есть: журнал вспомогательный, ронять его из-за формата незачем.
    """
    raw = str(output or '').strip()
    if not raw:
        return ''
    if raw.lower().startswith('json:'):
        raw = raw[5:].strip()

    data = _dict_parse(raw)
    if data is None:
        return _one_line(raw)

    for key in ('response', 'error'):
        value = str(data.get(key) or '').strip()
        if value:
            return _one_line(_inner_text(value))

    # Ответ шага бывает и самой структурой, без обёртки вызова оболочки: так
    # отвечает «Вернуть результат». Разбирать её тем же `_inner_text`, что и
    # вложенный ответ, — иначе в журнал уезжает сырой JSON плана на восемь шагов.
    return _tool_text(data) or _inner_text(raw) or _one_line(raw)


def _dict_parse(raw: str):
    """
    Словарь из repr или JSON. `None` — не разобралось.

    `literal_eval` вместо `eval`: разбирает только литералы и ничего не исполняет,
    а в трассу попадает чужой текст.
    """
    if not raw.startswith('{'):
        return None

    for parse in (ast.literal_eval, json.loads):
        try:
            value = parse(raw)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        if isinstance(value, dict):
            return value

    return None


def _inner_text(value: str) -> str:
    """
    Ответ агента человеческим текстом, даже когда он завёрнут в JSON.

    Шаги «Ответ JSON: …» просят у агента структуру, и в журнале от неё нужен
    смысл, а не фигурные скобки: план, вердикт, причина отказа. Обычный текст
    возвращаем нетронутым.
    """
    text = value.strip()
    # Обёртки, в которые агент кладёт структуру: markdown-забор и префикс `json:`
    # из шага `return_response_text`.
    if text.startswith('```'):
        text = text.strip('`')
        text = text[4:] if text.lower().startswith('json') else text
    if text.lower().startswith('json:'):
        text = text[5:]

    data = _dict_parse(text.strip())
    if data is None:
        return text

    # Шаги «Ответ JSON: …» заворачивают ответ в один ключ (`task_plan_json`,
    # `qa_report_json`): сам ключ человеку не говорит ничего, спускаемся внутрь.
    while len(data) == 1:
        inner = next(iter(data.values()))
        # Список внутри обёртки — это перечень (цели, подзадачи): нумеруем, иначе
        # в журнал уехал бы сырой массив в квадратных скобках.
        if isinstance(inner, list):
            return ' · '.join(f'{i}) {_one_line(item)}' for i, item in enumerate(inner, 1)
                              if str(item or '').strip())
        if not isinstance(inner, dict) or not inner:
            break
        data = inner

    parts = []
    for key in TASK_LOG_ANSWER_KEYS:
        found = data.get(key)
        if isinstance(found, dict):
            found = (found.get('summary') or found.get('plan_text')
                     or found.get('error') or found.get('verdict'))
        found = str(found or '').strip()
        if found:
            parts.append(found)

    if parts:
        return ' · '.join(parts)

    # Известных ключей нет — показываем сам словарь парами «ключ: значение».
    # Читается заметно лучше сырого JSON, а терять его содержимое незачем: у
    # ролей там вердикты вида `qa_goal_ok: yes`.
    pairs = [f'{key}: {_one_line(val)}' for key, val in data.items()
             if not isinstance(val, (dict, list)) and str(val or '').strip()]

    return ' · '.join(pairs) if pairs else text


def _tool_text(data: dict) -> str:
    """
    Результат инструмента человеческой строкой.

    Инструменты возвращают словари под движок, и в журнале они выглядели как
    `{'goal_has': 'yes', 'goal_index': 0, …}` — читать невозможно. Известные
    формы переписываем словами; неизвестные вызывающий отдаст как есть.
    """
    if 'env_ok' in data:
        return ('среда готова' if str(data.get('env_ok')) == 'yes'
                else f"среда не готова: {data.get('env_error') or 'причина не названа'}")

    if 'goal_done_count' in data:
        return (f"целей закрыто {data.get('goal_done_count')} из {data.get('goal_total')}, "
                f"осталось {data.get('goal_open_count')}")

    if 'goal_has' in data:
        if str(data.get('goal_has')) != 'yes':
            return 'цели кончились'
        return (f"взял цель {data.get('goal_number')} из {data.get('goal_total')}: "
                f"{data.get('goal_text')}")

    return ''


def _outcome_line(at, outcome: str) -> str:
    """Итог круга — последняя строка блока: с неё начинает следующий круг."""
    stamp = at.strftime('%H:%M:%S') if at else '--:--:--'
    text = _one_line(outcome)
    keyword = 'затык' if not text.startswith('готово') else 'готово'

    return f'{stamp}  {keyword:<9} итог круга: {text[:TASK_LOG_STEP_MAX_CHARS]}\n'


def _one_line(text) -> str:
    """
    Ответ шага в одну строку: журнал читают построчно, переносы его ломают.

    Литеральный «\\n» убираем наравне с настоящим переводом строки: в repr
    словаря перенос остаётся двумя символами и в строке журнала выглядел бы
    мусором посреди фразы.
    """
    return ' '.join(str(text or '').replace('\\n', ' ').replace('\\t', ' ').split())


def _read_tail(path: str) -> str:
    """Хвост файла до потолка. Нет файла или не читается — пустая строка."""
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return ''

    if len(text) <= TASK_LOG_READ_MAX_CHARS:
        return text

    return '…начало журнала обрезано…\n' + text[-TASK_LOG_READ_MAX_CHARS:]
