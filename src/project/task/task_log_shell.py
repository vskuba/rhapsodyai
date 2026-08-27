"""
События оболочки для журнала строки: когда задание ушло агенту и когда вернулось.

Зачем отдельно от шагов workflow. Шаг `claude_shell_call` в трассе — одна запись,
и появляется она только когда вызов кончился. Пока агент думает, в журнале пусто,
а когда вызов срывается — видно лишь «шаг шёл 878 секунд и не получил ответа».
Поймано живьём на планировании #1027: оболочка ответ выдала, человек видел его на
экране, а шаг разведки всё равно ушёл в «Менеджер недоступен» — и по журналу
нельзя было сказать, где потерялся ответ: не дошёл до оболочки, не снялся с
экрана или не доехал обратно к движку.

Поэтому оболочку журналируем сама по себе: «запрос ушёл» в одну строку, «ответ
получен» в другую, каждая со своим временем. Разошлись эти два времени с временем
шага — затык видно сразу, и видно, на чьей он стороне.

Откуда берём. Ничего писать не нужно: очередь оболочки (`ai_claude_session`) уже
хранит и текст задания, и ответ, и обе отметки времени. Этот модуль их только
читает и раскладывает на события.

Как события привязываются к прогону. Прямой ссылки «строка очереди → задача» нет:
номер строки очереди (`inbox_id`) возвращает сам вызов, то есть уже после того,
как всё кончилось, — а нужны события как раз у незакончившегося. Поэтому
привязываем по адресу и времени: чья роль, в каком каталоге и попало ли задание в
окно прогона. Этого хватает, потому что конвейер держит по одному кругу на роль в
проекте (`task_setting_parallel`), и двух прогонов одной роли в одном окне не
бывает.

Каталог сверяем префиксом, а не равенством: прогон знает каталог проекта, а
оболочка роли живёт в каталоге подзадачи внутри него (`.claude/worktrees/...`).
"""
from datetime import timedelta

from mysql_.mysql_ import mysql_get_db_async

# Ключевые слова строк. Свои, а не общие «сделал»/«затык»: событие оболочки — это
# не шаг работы, и в общей хронологии его нужно отличать глазом. Те же слова
# разбирает вкладка «Журналы» (`LOG_KEYWORDS` в `admin/project/task.html`).
TASK_LOG_SHELL_KEYWORD_SENT = 'запрос'
TASK_LOG_SHELL_KEYWORD_ANSWER = 'ответ'
TASK_LOG_SHELL_KEYWORD_FAIL = 'затык'

# Статусы строки очереди. Значения те же, что пишет оболочка через
# `/telegram-app/claude/respond` (см. `claude_message`).
TASK_LOG_SHELL_STATUS_ANSWERED = 'answered'
TASK_LOG_SHELL_STATUS_FAILED = 'failed'

# Сколько символов задания уносим в строку. Задание собирает движок по шаблону
# шага, и в ленте от него нужно одно: какой шаг ушёл и когда. Полный текст лежит
# в очереди и в трассе шага.
TASK_LOG_SHELL_SENT_MAX = 200

# Ответ не режем вовсе.
#
# Резали и на 200 символах теряли ровно то, ради чего в журнал и смотрят: вердикт
# QA обрывался на «а цель требует п…», JSON-отчёт — на середине первого поля.
# Понять по такому огрызку, что произошло, нельзя, а собрать по нему вопрос
# человеку — тем более: вопрос задают как раз тогда, когда роль упёрлась, и
# упёрлась она в то, что в обрезанный хвост не влезло.
#
# Дорого это не обходится. Файл читает только человек — роль его не видит
# (`TASK_SHELL_FILE` в `task_log`), так что в контекст следующего круга длинные
# строки не попадают. От неограниченного роста файл держит `_read_tail`: показ
# берёт последние `TASK_LOG_READ_MAX_CHARS` символов.
TASK_LOG_SHELL_ANSWER_MAX = 0

# Метка агентного сообщения в начале задания (`CLAUDE_SHELL_AGENT_MARKER`).
# Обрезаем: она служебная, и без неё в строку влезает больше сути.
TASK_LOG_SHELL_MARKER = '[[agent]]'

# Служебные команды оболочке — не задания агенту, а управление самой оболочкой.
# В ленте они нужны: перезапуск посреди круга и есть та причина, по которой ответ
# агента теряется («Оболочка перезапущена, ответ на сообщение потерян»). Но
# показывать их сырым `__RESTART_WATCH__` незачем — переводим на человеческий.
TASK_LOG_SHELL_SERVICE = {
    '__RESTART_WATCH__': 'оболочка перезапущена',
}

# Запас окна по краям. Задание кладётся в очередь на долю секунды раньше, чем
# движок отмечает шаг, а ответ доезжает чуть позже конца прогона — без запаса
# крайние события выпадали бы из своего же круга.
TASK_LOG_SHELL_WINDOW_SLACK = timedelta(seconds=30)


async def task_log_shell_events(role: str, work_dir: str, since, until=None) -> list[dict]:
    """
    События оболочки роли за окно прогона.

    Args:
        role: чья оболочка — `manager`, `developer`, `qa`, `bugfixer`.
        work_dir: каталог проекта прогона. Сверяется префиксом: оболочка роли
            работает в каталоге подзадачи внутри каталога проекта. Пустая строка —
            не сверяем вовсе (задача без проекта).
        since: начало окна — время старта прогона.
        until: конец окна. `None` — прогон ещё идёт, берём всё до сих пор.

    Returns:
        `[{'created_at', 'keyword', 'title', 'text', 'seconds'}]` в порядке
        времени. Два события на строку очереди: уход задания и приход ответа.
        Ответа ещё нет — второго события тоже нет, и это само по себе новость:
        в журнале видно задание без ответа.
    """
    role = str(role or '').strip()
    if not role or not since:
        return []

    rows = await _rows_window(role, str(work_dir or '').strip(), since, until)

    events = []
    for row in rows:
        content = str(row.get('content') or '')
        service = TASK_LOG_SHELL_SERVICE.get(content.strip())

        events.append({
            'created_at': row.get('created_at'),
            'keyword': TASK_LOG_SHELL_KEYWORD_SENT,
            'title': f'оболочка {role}: {service}' if service else f'оболочка {role} ← задание',
            'text': '' if service else _text_cut(_marker_strip(content), TASK_LOG_SHELL_SENT_MAX),
            'seconds': 0,
        })
        # У служебной команды ответа не ждут: она ничего не спрашивает.
        if service:
            continue

        answered_at = row.get('responded_at')
        if not answered_at:
            continue

        failed = str(row.get('status') or '') == TASK_LOG_SHELL_STATUS_FAILED
        events.append({
            'created_at': answered_at,
            'keyword': TASK_LOG_SHELL_KEYWORD_FAIL if failed else TASK_LOG_SHELL_KEYWORD_ANSWER,
            'title': f'оболочка {role} → ответ',
            'text': _text_cut(str(row.get('response') or ''), TASK_LOG_SHELL_ANSWER_MAX) or 'пусто',
            'seconds': _seconds_between(row.get('created_at'), answered_at),
        })

    return sorted(events, key=lambda item: item['created_at'])


def task_log_shell_line(event: dict) -> str:
    """
    Событие оболочки одной строкой журнала — в том же формате, что и шаг.

    Формат общий намеренно: обе хронологии сливаются в один файл и читаются
    подряд, а разбирает строки один и тот же код на вкладке «Журналы».
    """
    at = event.get('created_at')
    stamp = at.strftime('%H:%M:%S') if at else '--:--:--'
    keyword = str(event.get('keyword') or TASK_LOG_SHELL_KEYWORD_SENT)

    seconds = int(event.get('seconds') or 0)
    spent = f' [{seconds // 60} мин]' if seconds >= 60 else (f' [{seconds}с]' if seconds else '')

    title = str(event.get('title') or 'оболочка')
    # Двоеточие ставим только когда за ним что-то есть: у служебной команды текста
    # нет вовсе, и висящее в конце двоеточие читалось бы как потерянное значение.
    text = str(event.get('text') or '')

    return f"{stamp}  {keyword:<9} {title}{spent}{f': {text}' if text else ''}\n"


async def _rows_window(role: str, work_dir: str, since, until) -> list[dict]:
    """
    Строки очереди этой роли, попавшие в окно прогона.

    Роль и каталог лежат не в самой очереди, а в реестре сессий: очередь знает
    только номер сессии. Отсюда соединение — по нему же отсекаются чужие проекты.

    Каталог сверяем префиксом, потому что оболочка роли работает в каталоге
    подзадачи внутри каталога проекта. Через `LOCATE(...) = 1`, а не `LIKE`:
    в пути постоянно встречаются `_` и `%`, для `LIKE` это шаблонные символы, и
    `feature_task_1027` совпал бы с `feature-task-1027`. Экранировать их можно, но
    сравнение без шаблона обходится вовсе без правил экранирования.
    """
    where = ["s.created_at >= %s"]
    params: list = [since - TASK_LOG_SHELL_WINDOW_SLACK]

    if until:
        where.append("s.created_at <= %s")
        params.append(until + TASK_LOG_SHELL_WINDOW_SLACK)

    where.append("r.role = %s")
    params.append(role)

    if work_dir:
        where.append("LOCATE(%s, COALESCE(r.work_dir, '')) = 1")
        params.append(work_dir)

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT s.content, s.response, s.status, s.created_at, s.responded_at "
            "  FROM ai_claude_session s "
            "  JOIN ai_claude_session_registry r ON r.session_uuid = s.session_uuid "
            f" WHERE {' AND '.join(where)} "
            " ORDER BY s.id",
            params)

        return [dict(row) for row in (await db.fetchall() or [])]


def _marker_strip(text: str) -> str:
    """Убрать служебную метку агентного сообщения из начала задания."""
    stripped = text.strip()
    if stripped.startswith(TASK_LOG_SHELL_MARKER):
        stripped = stripped[len(TASK_LOG_SHELL_MARKER):]

    return stripped.strip()


def _text_cut(text: str, limit: int) -> str:
    """
    Текст в одну строку; за потолком обрезаем и помечаем многоточием.

    `limit` = 0 — не резать вовсе (так идут ответы оболочки).

    В одну строку сворачиваем всегда, даже когда не режем. Формат ленты — событие
    на строку, и перенос внутри события её разорвал бы: `_blocks_merge`
    раскладывает строки по времени обычной сортировкой, а продолжение без метки
    времени уехало бы от своего события в другое место блока.
    """
    one_line = ' '.join(str(text or '').replace('\\n', ' ').split())
    if not limit or len(one_line) <= limit:
        return one_line

    return one_line[:limit].rstrip() + '…'


def _seconds_between(start, end) -> int:
    """Сколько секунд между отметками. Любой из них нет — ноль."""
    if not start or not end:
        return 0

    return max(0, int((end - start).total_seconds()))
