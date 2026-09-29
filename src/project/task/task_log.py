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
import re
from datetime import datetime

from datetime_.datetime_ import datetime_offset_apply
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_get
from src.project.task.task_log_shell import task_log_shell_events, task_log_shell_line
from src.project.task.task_log_summary import task_log_summary_many
from src.project.task.task_worktree import (TASK_WORKTREE_BASE_DIR,
                                            task_worktree_base_branch,
                                            task_worktree_git,
                                            TASK_WORKTREE_DIR_TEMPLATE,
                                            task_worktree_path)

# Имена файлов. Шаблон `.task-*.md` закрыт в `.gitignore`: это следы процесса, а
# не результат работы, и в коммит с merge request им нельзя.
TASK_LOG_FILE = '.task-log.md'
TASK_STATE_FILE = '.task-state.md'

# Хронология оболочки: когда задание ушло агенту и когда вернулось (`task_log_shell`).
# Отдельным файлом, а не строками в общем журнале, по одной причине: общий журнал
# читает следующий круг целиком, и «запрос ушёл / ответ получен» ему только шум —
# работу он ведёт не с оболочкой, а внутри неё. Человеку же это единственный способ
# увидеть, на чьей стороне затык, и на странице оба файла сливаются по времени.
TASK_SHELL_FILE = '.task-shell.md'

# Вопросы ролей и ответы человека (`task_log_decision`). Тоже отдельно, и по той
# же причине: решение уходит в промпт готовым блоком, и второй его экземпляр
# посреди хронологии роль читала бы как ещё одно требование. Человеку же оно
# нужно на своём месте во времени — между кругом, который упёрся в развилку, и
# кругом, который пошёл дальше.
TASK_DECISION_FILE = '.task-decision.md'

TASK_LOG_FILES = (TASK_LOG_FILE, TASK_STATE_FILE, TASK_SHELL_FILE, TASK_DECISION_FILE)

# Каталог и префикс имени берём у `task_worktree`: перебор каталогов обязан
# находить ровно то, что тот создаёт. Префикс — шаблон без подстановки, до
# номера строки.
TASK_LOG_WORKTREES_DIR = TASK_WORKTREE_BASE_DIR
TASK_LOG_WORKTREE_PREFIX = TASK_WORKTREE_DIR_TEMPLATE.split('{')[0]

# Сколько символов ответа шага уносим в строку журнала. Ответы у ролей бывают на
# десятки килобайт — простыня сделала бы журнал нечитаемым, а полный текст и так
# лежит в трассе (`/admin/workflow_trace`).
#
# Ставили 220 — оказалось мало: мысль не успевала дочитаться, строки рвались на
# «Второй раунд я …». Подняли до 600, но и там вердикты QA и отчёты разработчика
# упирались в потолок, теряя как раз перечень того, что не сошлось. 850 — это
# абзац с запасом: типичный итог круга умещается целиком. Обрезку помечаем
# многоточием (`TASK_LOG_CUT_MARK`): молчащая обрезка не даёт понять, кончилась
# фраза или её отрезали.
TASK_LOG_STEP_MAX_CHARS = 850
TASK_LOG_CUT_MARK = '…'

# Ключи ответа, в которых лежит смысл: их роли кладут в JSON-структуру шага.
# Порядок важен — первым идёт то, что короче и понятнее человеку.
TASK_LOG_ANSWER_KEYS = ('summary', 'verdict', 'plan_text', 'plan', 'error', 'report',
                        'critique', 'evidence')

# С этого слова начинается формулировка удачного исхода круга (`_log_run`).
# По нему `_outcome_line` выбирает ключевое слово строки журнала.
TASK_LOG_OUTCOME_OK = 'готово'

# Состояния, в которых над строкой действительно работают. Те же переходные
# состояния, что и у конвейера (`task_pipeline`): пока строка в них, её держит
# живой прогон.
TASK_LOG_STATES_IN_FLIGHT = ('planning', 'reviewing', 'developing', 'testing', 'bugfixing')

# Потолок чтения. Журнал растёт кругами, а на страницу задач он идёт целиком в
# ответе API — отдаём хвост, а не весь файл.
TASK_LOG_READ_MAX_CHARS = 40000

# Потолок для хронологии оболочки — свой и больше общего. Ответы оболочки в неё
# кладутся целиком (`TASK_LOG_SHELL_ANSWER_MAX`), и одна строка там весит не
# двести символов, а тысячи: с общим потолком в хвост влезал бы последний круг, а
# предыдущие вытеснялись бы — при том, что смотрят в этот файл как раз чтобы
# сравнить круги между собой.
#
# Роль от этого не толстеет: файл идёт только на страницу (`task_log_read`), а
# промпт следующего круга собирается из `TASK_LOG_FILE`, у которого потолок общий.
TASK_LOG_READ_SHELL_MAX_CHARS = 150000

# Под каким ключом в наборе пересказов лежит итог круга. Шаги нумеруются с нуля, и
# отрицательное число с ними не столкнётся.
TASK_LOG_SUMMARY_OUTCOME_KEY = -1


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

    Хронологию оболочки (`.task-shell.md`) и решения человека (`.task-decision.md`)
    подмешиваем здесь же и только здесь: в общий журнал им нельзя — его целиком
    читает следующий круг, — а человеку они нужны ровно на своём месте по времени.
    Блоки круга и его оболочки подписаны одним заголовком и сходятся построчно;
    решение приходит между кругами и встаёт по дате своего заголовка.

    Returns:
        `{'log': str, 'state': str, 'dir': str, 'running': bool}` — пустые строки,
        если ни файла, ни идущего прогона нет. Это не ошибка: строка могла ещё не
        браться в работу, а каталог — уже уехать после слияния.
    """
    directory = task_log_dir(repo_dir, task_id)
    log = _blocks_merge(_read_tail(os.path.join(directory, TASK_LOG_FILE)),
                        _read_tail(os.path.join(directory, TASK_SHELL_FILE),
                                   TASK_LOG_READ_SHELL_MAX_CHARS),
                        _read_tail(os.path.join(directory, TASK_DECISION_FILE)))

    live = await _live_block(task_id)
    if live:
        log = f'{log}\n{live}' if log else live

    return {
        'log': log,
        'state': _read_tail(os.path.join(directory, TASK_STATE_FILE)),
        'dir': directory,
        'running': bool(live),
    }


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


async def task_log_rows_running() -> dict[int, str]:
    """
    Строки, по которым прогон идёт прямо сейчас: `{номер строки: роль}`.

    Нужны списку журналов. Сам список строится по файлам на диске, а файл
    появляется только по концу круга — строка, которую агент обрабатывает первый
    раз, в список не попадала вовсе, и найти её журнал было нельзя, хотя
    показывать там уже есть что.

    Номер берём из переменных прогона: у подзадачи `subtask_id`, у задачи под
    менеджером `task_id`. Приоритет у подзадачи — в её трассе лежит и номер
    родителя, и иначе работа приписалась бы задаче.

    **Одной трассы мало.** Статус `running` в ней держится, пока прогон её не
    закроет, — а закрыть он может не успеть: перезапуск контейнера, смерть
    процесса, оборванный воркер оставляют запись висеть навсегда. Живьём такие
    трассы от вчерашних кругов подсвечивали строку #1033 как работающую, хотя она
    стояла в `planned`.

    Поэтому сверяем с состоянием самой строки: работа идёт только тогда, когда
    конвейер держит её в переходном состоянии. Строка — источник правды, трасса
    отвечает лишь на вопрос «чей это прогон и какая роль».
    """
    async with mysql_get_db_async() as db:
        # ⚠ Номер строки берём колонками (`subtask_id`, `task_id` — считаются из
        # `variables_start`, миграция `20260929123812`), а роль — по-прежнему
        # разбором: своей колонки у неё нет, да и незачем. Читается `variables_start`
        # при этом только у работающих прогонов, а их единицы: отбор по `status`
        # теперь идёт индексом (`idx_workflow_run_status`), а не проходом по всей
        # таблице.
        #
        # Приоритет подзадачи сохранён как был: `COALESCE` берёт первое не-NULL,
        # а пустая строка в переменных в колонку не попадает (там `NULL`) — ровно
        # так же, как её пропускал прежний `or` в питоне.
        await db.execute(
            "SELECT COALESCE(subtask_id, task_id) AS task_id, variables_start "
            "  FROM agent_workflow_trace "
            " WHERE status = 'running' AND COALESCE(subtask_id, task_id) IS NOT NULL")
        rows = await db.fetchall() or []

        running: dict[int, str] = {}
        for row in rows:
            variables = _dict_parse(str(row.get('variables_start') or '')) or {}
            running[int(row['task_id'])] = str(variables.get('task_shell_role') or '')
        if not running:
            return {}

        placeholders = ', '.join(['%s'] * len(running))
        states = ', '.join(['%s'] * len(TASK_LOG_STATES_IN_FLIGHT))
        await db.execute(
            f"SELECT id FROM project_task "
            f" WHERE id IN ({placeholders}) AND pipeline_state IN ({states})",
            [*running, *TASK_LOG_STATES_IN_FLIGHT])
        alive = {int(row['id']) for row in await db.fetchall() or []}

    return {task_id: role for task_id, role in running.items() if task_id in alive}


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
        # Сорвавшийся по таймауту прогон номера сессии не отдаёт: агентная функция
        # уходит исключением, и результата с ним не возвращает вовсе. А это ровно
        # тот случай, ради которого журнал и заводили. Берём последнюю трассу этой
        # строки: её шаги дошли до обрыва и лежат нетронутыми.
        steps = await _trace_steps(await _trace_last_session(task_id))
    if not steps:
        return 0

    # События оболочки берём по окну прогона — до перевода времени, пока обе
    # стороны ещё в UTC: смещение к ним применяется тем же проходом, что и к шагам.
    shell = await task_log_shell_events(role, repo_dir,
                                        steps[0].get('created_at'), steps[-1].get('created_at'))

    # Время трассы пишет MySQL, а он в контейнере живёт по UTC. Человек сверяет
    # журнал с часами на стене, поэтому показываем в поясе настройки `timezone`.
    # Читаем её один раз на прогон: меток в круге десятки.
    offset = await setting_get('timezone', '+0')
    for item in (*steps, *shell):
        item['created_at'] = datetime_offset_apply(item.get('created_at'), offset)

    started = steps[0].get('created_at')
    head = (f"\n## круг {int(attempt_no or 0)} · {role}{_retry_mark(directory, attempt_no, role)} · "
            f"{started.strftime('%Y-%m-%d %H:%M') if started else ''}\n")

    shown = [step for step in steps if not _step_skip(step)]
    summaries = await _summaries_make(shown, outcome)

    lines = [head]
    for number, step in enumerate(shown):
        lines.append(_step_line(step, summaries.get(number, '')))
    lines.append(_outcome_line(steps[-1].get('created_at'), outcome,
                               summaries.get(TASK_LOG_SUMMARY_OUTCOME_KEY, '')))

    # Оболочку пишем в свой файл, а не в этот. Журнал читает следующий круг, и
    # «задание ушло, ответ пришёл» ему не говорит ничего: работу он ведёт не с
    # оболочкой, а внутри неё. Зато человеку это единственный способ увидеть, на
    # чьей стороне затык, — страница сливает оба файла по времени (`task_log_read`).
    _shell_write(directory, head, shell)

    try:
        with open(os.path.join(directory, TASK_LOG_FILE), 'a', encoding='utf-8') as fh:
            fh.write(''.join(lines))
    except OSError as e:
        # Журнал вспомогательный: не записался — круг всё равно состоялся.
        logger_info(f'task_log: журнал строки {task_id} не дописан: {type(e).__name__}: {e}')
        return 0

    await _state_write(directory, task_id, role, attempt_no, outcome, steps)

    return len(lines) - 1


async def _live_block(task_id) -> str:
    """
    Шаги прогонов строки, которые идут прямо сейчас.

    Собираются из трассы, а не из файла: файл пишется по концу круга, а увидеть,
    чем агент занят, человек хочет пока тот занят. Смещение читаем то же, что и
    у записанного, иначе живой блок разъехался бы с остальным журналом на часы.

    Здесь же — события оболочки, и ради идущего прогона они и заводились. Шаг
    `claude_shell_call` появляется в трассе только когда кончится, и всё это время
    журнал молчал; строка «задание ушло» без пары «ответ получен» показывает, что
    ждём агента, а пара без последующего шага — что ответ до движка не доехал.
    """
    if not await _row_in_flight(task_id):
        return ''

    runs = await _runs_active(task_id)
    if not runs:
        return ''

    offset = await setting_get('timezone', '+0')
    blocks = []
    for run in runs:
        steps = await _trace_steps(str(run.get('session_uuid') or ''))
        # Конец окна открыт: прогон идёт, и ответ может прийти в любую секунду.
        shell = await task_log_shell_events(str(run.get('role') or ''),
                                            str(run.get('work_dir') or ''),
                                            run.get('started_at'))
        for item in (*steps, *shell):
            item['created_at'] = datetime_offset_apply(item.get('created_at'), offset)

        started = datetime_offset_apply(run.get('started_at'), offset)
        lines = [f"\n## идёт сейчас · {run.get('role') or 'агент'} · "
                 f"{started.strftime('%Y-%m-%d %H:%M') if started else ''}\n"]
        lines += _lines_merge([step for step in steps if not _step_skip(step)], shell)
        # Шагов может не быть вовсе: прогон только начался. Сам заголовок при этом
        # новость — по нему видно, что строка не брошена, а в работе.
        blocks.append(''.join(lines))

    return ''.join(blocks)


async def _row_in_flight(task_id) -> bool:
    """
    Строка действительно в работе — по состоянию конвейера, а не по трассе.

    Трасса оборванного прогона навсегда остаётся в `running`: закрыть её некому,
    процесс умер. Без этой сверки журнал показывал бы «идёт сейчас» на прогоне,
    который встал час назад, — и человек ждал бы результата, которого не будет.
    Состояние строки ведёт сам конвейер, и оно тут единственный честный признак.
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT pipeline_state FROM project_task WHERE id = %s",
                         (int(task_id or 0),))
        row = await db.fetchone()

    return str((row or {}).get('pipeline_state') or '') in TASK_LOG_STATES_IN_FLIGHT


async def _runs_active(task_id) -> list[dict]:
    """
    Незакрытые трассы строки и чья это роль.

    Ищем по переменным прогона: у подзадачи это `subtask_id`, у задачи под
    менеджером — `task_id`. Разделять обязательно: в трассе подзадачи лежит и
    номер её родителя, и без второго условия задача забирала бы себе прогоны
    всех своих подзадач.

    Роль берём из тех же переменных (`task_shell_role`) — в самой трассе её нет.

    ⚠ Отбор идёт по колонкам `subtask_id`/`task_id` (считаются из
    `variables_start`, миграция `20260929123812`), а не подстрокой по LONGTEXT:
    `LIKE '%...%'` проиндексировать нечем, и такой поиск читал `variables_start`
    у всех строк таблицы — 639 мс на проде.

    ⚠⚠ **Заодно чинится тихая потеря прогонов.** Старый образец искал номер
    вместе с кавычками (`"subtask_id": "5219"`), а движок кладёт переменные как
    есть — и номер попадает в трассу то строкой, то **числом**
    (`"subtask_id": 5219`). По числовой записи образец не совпадал ни разу, и
    такие прогоны не находились вовсе: ни здесь, ни в замерах
    (`task_metric._trace_last_session`). Знал об этом только `task_abort`, там
    номер приводили к числу явно. Сверка на образцах обеих форм показала ровно
    это: старый отбор терял `{"subtask_id": 7004}`, новый находит.

    ⚠ Условие «у задачи нет подзадачи» теперь `subtask_id IS NULL` вместо
    прежнего `NOT LIKE '%"subtask_id": "%'`. Разница ровно в одном случае: ключ
    есть, но пустой. Прежний отбор такой прогон исключал, новый — берёт, и это
    не расхождение, а совпадение с питоном рядом: `variables.get('subtask_id')
    or variables.get('task_id')` пустую строку тоже пропускает и считает прогон
    задачиным.
    """
    task_id = int(task_id or 0)
    if not task_id:
        return []

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT session_uuid, started_at, variables_start "
            "  FROM agent_workflow_trace "
            " WHERE status = 'running' "
            "   AND (subtask_id = %s OR (task_id = %s AND subtask_id IS NULL)) "
            " ORDER BY id",
            (task_id, task_id))
        rows = await db.fetchall() or []

    runs = []
    for row in rows:
        variables = _dict_parse(str(row.get('variables_start') or '')) or {}
        runs.append({'session_uuid': row.get('session_uuid'),
                     'started_at': row.get('started_at'),
                     'role': str(variables.get('task_shell_role') or ''),
                     # Второй половиной адреса оболочки: роли в командах разных
                     # проектов зовутся одинаково (`task_agent_manager`).
                     'work_dir': str(variables.get('task_shell_work_dir') or '')})

    return runs


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

    # «Задача», а не «строка»: внутри кода строкой зовётся и задача, и подзадача —
    # там это удобно, потому что конвейер обращается с ними одинаково. Но читает
    # файл человек и агент, и для них «строка» — это строка текста.
    #
    # «Круг N завершился», а не «последний круг N»: файл пишется по концу круга,
    # и это единственное, что о нём достоверно известно. Читающий круг узнаёт
    # сразу и номер, и то, что предыдущий заход уже отработал.
    text = (f'# Задача #{task_id} · круг {int(attempt_no or 0)} завершился · {role}\n\n'
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


async def _trace_last_session(task_id) -> str:
    """
    Сессия последней трассы строки — запасной путь, когда номер потерялся.

    Теряется он при обрыве: агентная функция уходит исключением по таймауту и
    результата, в котором номер лежал бы, не возвращает. Трасса при этом на месте
    и остаётся в `running` — её никто уже не закроет.

    Отбор тот же, что у идущих прогонов: `subtask_id` у подзадачи, `task_id` у
    задачи под менеджером — и обязательно без `subtask_id`, иначе задача забрала
    бы себе прогон своей же подзадачи.

    Берём именно последнюю, и это верно только потому, что зовут её сразу после
    обрыва: строка в этот момент заблокирована конвейером, новый прогон по ней
    начаться не успел. Позвать позже — и «последняя» окажется уже следующим
    кругом, а в журнал уедет его копия.
    """
    task_id = int(task_id or 0)
    if not task_id:
        return ''

    async with mysql_get_db_async() as db:
        # Отбор по колонкам, а не подстрокой по LONGTEXT: та же замена и та же
        # оговорка про пустой `subtask_id`, что в `_runs_active` выше.
        await db.execute(
            "SELECT session_uuid FROM agent_workflow_trace "
            " WHERE subtask_id = %s OR (task_id = %s AND subtask_id IS NULL) "
            " ORDER BY id DESC LIMIT 1",
            (task_id, task_id))
        row = await db.fetchone()

    return str((row or {}).get('session_uuid') or '')


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


async def _summaries_make(steps: list, outcome: str) -> dict:
    """
    Пересказать то, что не влезает в строку журнала. Ключ — номер шага в `steps`.

    Пересказываем только длинное. Короткий ответ уже и есть суть: звать модель
    ради него значит платить временем за переписывание готового, а строка от
    этого не станет понятнее.

    Итог круга идёт наравне с шагами, под своим ключом: он такой же длинный текст
    и обрезался ровно так же — а читают его первым, это последняя строка блока.

    Сбой пересказа не сбой журнала: `task_log_summary_many` возвращает пустой
    набор, и все строки уходят в обрезку, как раньше.
    """
    items = []
    for number, step in enumerate(steps):
        text = _one_line(step.get('error') or '') or _answer_text(step.get('output'))
        if len(text) <= TASK_LOG_STEP_MAX_CHARS:
            continue
        items.append({'key': number, 'title': str(step.get('step_title') or 'шаг'),
                      'kind': 'затык' if _step_failed(step) else 'сделал', 'text': text})

    outcome_text = _one_line(outcome)
    if len(outcome_text) > TASK_LOG_STEP_MAX_CHARS:
        items.append({'key': TASK_LOG_SUMMARY_OUTCOME_KEY, 'title': 'итог круга',
                      'kind': 'готово' if outcome_text.startswith(TASK_LOG_OUTCOME_OK) else 'затык',
                      'text': outcome_text})

    if not items:
        return {}

    return await task_log_summary_many(items, TASK_LOG_STEP_MAX_CHARS)


def _lines_merge(steps: list, shell: list, summaries: dict | None = None) -> list[str]:
    """
    Шаги workflow и события оболочки одной хронологией, по времени.

    Двумя списками их держать нельзя: смысл именно в чередовании. «Задание ушло в
    17:03, ответ вернулся в 17:17, а шаг закрылся в 17:18 без ответа» — читается
    только когда три строки стоят подряд.

    Сортировка устойчивая, и при равном времени шаг идёт первым: у события
    оболочки и породившего его шага метки совпадают до секунды, а причина
    (шаг начался) логически раньше следствия (задание ушло).

    `summaries` — пересказы длинных ответов шагов по их номеру; у событий оболочки
    пересказа не бывает, они и так короткие.
    """
    summaries = summaries or {}
    items = [(step.get('created_at'), 0, _step_line(step, summaries.get(number, '')))
             for number, step in enumerate(steps)]
    items += [(event.get('created_at'), 1, task_log_shell_line(event)) for event in shell]

    # Без метки времени строку не поставить в ряд — отдаём её в конец, а не роняем
    # сортировку: пустая метка возможна у оборванного шага.
    items.sort(key=lambda item: (item[0] is None, item[0], item[1]))

    return [line for _, _, line in items]


def _shell_write(directory: str, head: str, shell: list) -> None:
    """
    Дописать хронологию оболочки за круг в её собственный файл.

    Заголовок круга тот же, что у общего журнала, — по нему страница и сводит два
    файла в одну ленту (`_blocks_merge`). Пустой список круга всё равно пишем
    заголовком: «оболочку не звали вовсе» — это тоже ответ на вопрос, где затык.

    Сбой записи не сбой круга: файл вспомогательный, и роль его не читает.
    """
    lines = [head] + [task_log_shell_line(event) for event in shell]
    try:
        with open(os.path.join(directory, TASK_SHELL_FILE), 'a', encoding='utf-8') as fh:
            fh.write(''.join(lines))
    except OSError as e:
        logger_info(f'task_log: хронология оболочки не дописана: {type(e).__name__}: {e}')


def _blocks_merge(*sources: str) -> str:
    """
    Свести несколько файлов журнала в одну ленту: по блокам, блоки — по времени.

    Файлов у строки три, и у каждого своя причина жить отдельно: круги пишет
    конвейер и читает следующий круг, хронологию оболочки читает только человек,
    решения человека приходят между кругами. Показывать их надо вместе.

    Склеиваем поблочно, а не файл к файлу: строка несёт только `ЧЧ:ММ:СС`, дата
    живёт в заголовке — за пределами своего блока такую метку не с чем сравнивать.
    Блоки с одинаковым заголовком (круг и его же оболочка) сливаются построчно.

    Порядок блоков — по дате в заголовке, а не по порядку файлов. Решение
    человека случается между кругами, и приписать его в конец значило бы сказать,
    что отвечали после всей работы, — а по нему как раз и видно, что круг после
    ответа пошёл иначе. Заголовок без даты (обрезанный хвост файла) держим
    первым: он про то, что было раньше всего показанного.
    """
    blocks: list[tuple[str, list[str]]] = []
    for source in sources:
        if not source or not source.strip():
            continue
        for head, lines in _blocks_split(source):
            same = next((item for item in blocks if item[0] == head and head), None)
            if same:
                same[1].extend(lines)
            else:
                blocks.append((head, list(lines)))

    blocks.sort(key=lambda item: _block_time(item[0]))

    return ''.join(_block_join(head, lines) for head, lines in blocks)


def _block_time(head: str) -> str:
    """
    Дата и время из заголовка блока — ключ сортировки. Нет их — пустая строка.

    Пустая сортируется первой, и это верно: заголовка без даты не бывает у
    записанного блока, он остаётся только у обрезанного хвоста файла.

    Сравниваем строкой, а не датой: формат `ГГГГ-ММ-ДД ЧЧ:ММ` при лексическом
    сравнении и так идёт по возрастанию, а разбор дал бы лишний способ уронить
    показ журнала из-за опечатки в заголовке.
    """
    found = _BLOCK_TIME_RE.search(head or '')

    return found.group(0) if found else ''


_BLOCK_TIME_RE = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}')


def _blocks_split(text: str) -> list[tuple[str, list[str]]]:
    """
    Текст журнала на блоки: `[(заголовок круга, [строки])]`.

    Пустые строки выбрасываем: разделение между блоками рисует `_block_join`, а
    попав в общий список, пустая строка уехала бы сортировкой в начало блока.

    Строки до первого заголовка (обрезанный хвост файла) отдаём под пустым
    заголовком — так они остаются на месте и не притворяются частью первого круга.
    """
    blocks: list[tuple[str, list[str]]] = [('', [])]
    for line in text.splitlines(keepends=True):
        if line.startswith('## '):
            blocks.append((line, []))
        elif line.strip():
            blocks[-1][1].append(line)

    return [block for block in blocks if block[0] or block[1]]


def _block_join(head: str, lines: list[str]) -> str:
    """
    Блок обратно в текст: пустая строка, заголовок, строки по времени.

    Сортируем сами строки, а не разобранные метки: формат у всех один и начинается
    с `ЧЧ:ММ:СС`, поэтому обычный лексикографический порядок и есть порядок по
    времени — и он устойчив, то есть при равной секунде порядок внутри блока
    сохраняется таким, каким его собрали.
    """
    body = ''.join(sorted(lines))

    return f'\n{head}{body}' if head else body


def _step_line(step: dict, summary: str = '') -> str:
    """
    Шаг трассы одной строкой журнала: время, ключевое слово, шаг, время, суть.

    Ключевых слов шесть, те же, что разбирает вкладка «Журналы». Ошибка шага и
    сорвавшийся вызов оболочки — `затык`: по нему следующий круг и ищет, обо что
    споткнулся прошлый.

    `summary` — готовый пересказ длинного ответа (`task_log_summary`). Пуст —
    режем по потолку, как раньше: пересказ вспомогательный и отказывать умеет.
    """
    at = step.get('created_at')
    stamp = at.strftime('%H:%M:%S') if at else '--:--:--'
    text = _one_line(step.get('error') or '') or _answer_text(step.get('output'))
    keyword = 'затык' if _step_failed(step) else 'сделал'

    seconds = int((step.get('duration_ms') or 0) / 1000)
    spent = f' [{seconds // 60} мин]' if seconds >= 60 else (f' [{seconds}с]' if seconds else '')
    title = str(step.get('step_title') or 'шаг')

    return f'{stamp}  {keyword:<9} {title}{spent}: {summary or _cut_text(text)}\n'


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

    **`ok: false` сам по себе затыком не считается.** Роль отвечает так и когда
    работала честно: «переименовал девять функций, но остановился на развилке» —
    это состоявшийся ход с содержанием, и помечать его наравне с мёртвой
    оболочкой значит врать. Отрицательный исход круга и так виден отдельной
    строкой «итог круга» в конце блока.

    Затык здесь только у шага-заглушки «роль недоступна»: она возвращает тот же
    `ok: false`, но без содержания — пустой отчёт и текст ошибки вместо работы.
    По содержанию их и различаем.
    """
    if str(step.get('status') or '') == 'error':
        return True

    output = str(step.get('output') or '')

    if any(f"'status': '{bad}'" in output or f'"status": "{bad}"' in output
           for bad in ('timeout', 'failed', 'no_session', 'busy')):
        return True

    if "'ok': false" not in output.lower() and '"ok": false' not in output.lower():
        return False

    return not _answer_has_substance(output)


def _answer_has_substance(output: str) -> bool:
    """
    В ответе есть работа, а не только признание, что её не было.

    Смотрим на ключи смысла (`TASK_LOG_ANSWER_KEYS`) — тот же список, по которому
    журнал достаёт суть ответа. Есть непустой `summary` или `report` — роль что-то
    сделала и рассказала об этом; нет ничего, кроме `error`, — это заглушка
    несостоявшегося прогона.

    `error` из списка исключаем намеренно: он есть и у заглушки, и по нему как раз
    ничего не отличить.
    """
    text = _answer_text(output)
    if not text:
        return False

    data = _dict_parse(str(output or '').removeprefix('json:').strip())
    if data is None:
        return bool(text)

    # Спускаемся сквозь обёртку из одного ключа: роли отвечают
    # `{"dev_report_json": {...}}`, и содержание лежит внутри, а не снаружи. Тот
    # же спуск делает `_inner_text`, когда достаёт из ответа человеческий текст.
    while isinstance(data, dict) and len(data) == 1:
        inner = next(iter(data.values()))
        if not isinstance(inner, dict):
            break
        data = inner

    if isinstance(data.get('report'), dict):
        data = data['report']

    return any(str((data or {}).get(key) or '').strip()
               for key in TASK_LOG_ANSWER_KEYS if key != 'error')


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


def _outcome_line(at, outcome: str, summary: str = '') -> str:
    """
    Итог круга — последняя строка блока: с неё начинает следующий круг.

    Удачный исход `task_pipeline._log_run` формулирует с этого слова — «готово»
    или «готово, с замечаниями: …». Договорённость строковая, зато исход круга и
    его текст остаются одним значением: разошлись бы они — и в журнале появился
    бы «затык» с текстом об успехе.
    """
    stamp = at.strftime('%H:%M:%S') if at else '--:--:--'
    text = _one_line(outcome)
    keyword = 'готово' if text.startswith(TASK_LOG_OUTCOME_OK) else 'затык'

    return f'{stamp}  {keyword:<9} итог круга: {summary or _cut_text(text)}\n'


def _cut_text(text: str) -> str:
    """Текст до потолка строки журнала; обрезанное помечаем многоточием."""
    if len(text) <= TASK_LOG_STEP_MAX_CHARS:
        return text

    return text[:TASK_LOG_STEP_MAX_CHARS].rstrip() + TASK_LOG_CUT_MARK


def _one_line(text) -> str:
    """
    Ответ шага в одну строку: журнал читают построчно, переносы его ломают.

    Литеральный «\\n» убираем наравне с настоящим переводом строки: в repr
    словаря перенос остаётся двумя символами и в строке журнала выглядел бы
    мусором посреди фразы.
    """
    return ' '.join(str(text or '').replace('\\n', ' ').replace('\\t', ' ').split())


def _read_tail(path: str, limit: int = TASK_LOG_READ_MAX_CHARS) -> str:
    """
    Хвост файла до потолка. Нет файла или не читается — пустая строка.

    Потолок параметром, потому что у хронологии оболочки он свой: строки там
    длиннее на порядок, а читает её только человек.

    Обрезаем по границе строки, а не по символу: разрезанное посередине событие
    теряет метку времени, и `_blocks_merge` уносит его огрызок сортировкой в
    случайное место блока — читается это как чужой обрывок текста.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return ''

    if len(text) <= limit:
        return text

    tail = text[-limit:]

    return '…начало журнала обрезано…\n' + tail[tail.find('\n') + 1:]
