"""
Вопрос агента человеку и ответ на него — развилки, которые роль не вправе решать сама.

Зачем. Подзадача #1028 упёрлась в вопрос «переименовывать ли инструменты в
`src/tool/**` и пересинхронизировать ли их реестр в БД»: цена ошибки там выше
обычного ренейма — по этим именам workflow зовёт инструменты. Спросить разработчику
было некуда, и он делал единственное, что умеет, — не доделывал и отчитывался
«цель не закрыта». Три круга подряд, после чего `blocked`. Человек при этом видел
только вердикт QA и ни одного вопроса: развилка жила в рассуждениях агента и
наружу не выходила.

Отсюда два конца одной механики.

**Вопрос** роль задаёт полем `question` в своём отчёте — вместе с готовыми
вариантами ответа. Круг за это не жжём: работа встала не потому, что агент не
справился, а потому что дальше без решения нельзя. Подзадача уходит в `blocked` —
это ровно его смысл, «нужен человек», — и на странице задач у неё появляется
кнопка с вопросом.

**Решение** человек принимает выбором варианта. Оно ложится в `metadata.decisions`
и с этого момента идёт во все последующие промпты роли: решение принимается один
раз, а кругов после него может быть сколько угодно, и на каждом агент обязан о нём
помнить. Держать его в `pipeline_error` не вышло бы — тот перетирается следующим
вердиктом QA.

Решение можно добавить и без вопроса: человек видит затык раньше, чем агент
догадается спросить, и тогда `task_question_decision_add` кладёт то же самое в тот
же список. Для агента разницы нет — он читает список, а не историю его появления.

Вопрос — не сообщение и не переписка. Он одноразовый: ответили — вопрос из мешка
исчез, остался след в решениях. Диалог ролью и человеком тут не ведётся: если
после ответа осталась неясность, роль задаёт новый вопрос следующим кругом.
"""
from datetime_.datetime_ import datetime_utc_now
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_metadata import task_metadata_parse, task_metadata_update

# Ключи в мешке `project_task.metadata`.
TASK_QUESTION_KEY = 'question'
TASK_QUESTION_KEY_DECISIONS = 'decisions'
# Пачка вопросов разведки: список со своими черновиками ответов.
#
# Отдельный ключ, а не список в `question`. Одиночный вопрос роли — другая механика:
# спросил, получил ответ, пошёл дальше. Здесь развилок сразу несколько, отвечают на
# них не подряд, и до последнего ответа ни одна не считается решённой: человек
# переключается между вопросами и правит уже данные ответы, потому что ответ на
# третий вопрос нередко меняет ответ на первый.
#
# Поэтому черновик, а не решение. В `decisions` пачка уезжает целиком и разом — когда
# отвечены все: половина развилок, поданная роли как решённая, хуже, чем ни одной, —
# она примет её за полный ответ и спланирует по нему.
TASK_QUESTION_KEY_QUEUE = 'questions'

# Сколько вариантов ответа берём у агента. Больше — не выбор, а анкета: человек
# идёт в кнопку, чтобы решить за десять секунд, и десять вариантов эту задачу
# превращают в чтение. Лишние отбрасываем молча — вопрос от этого не портится.
TASK_QUESTION_OPTIONS_MAX = 6

# Потолки на текст. Вопрос и варианты пишет живой Claude Code, и без границы он
# способен прислать в поле «вариант ответа» абзац рассуждений — попап от этого
# растянется на экран.
TASK_QUESTION_TEXT_MAX = 2000
TASK_QUESTION_OPTION_MAX = 300
TASK_QUESTION_ANSWER_MAX = 2000

# Сколько решений отдаём в промпт. Решения не устаревают и не отменяются, поэтому
# по-хорошему нужны все; потолок — страховка от подзадачи, которую человек правил
# два десятка раз, чтобы список не вытеснил из промпта саму работу. Обрезаем
# старые: свежие решения точнее описывают текущую развилку.
TASK_QUESTION_DECISIONS_MAX = 20

# Сколько вопросов принимаем за раз. Разведка формулирует до пяти, и столько же
# берём: пачка длиннее означает, что агент не разведал, а переложил работу на
# человека — на такое отвечать не станут, и задача встанет насовсем.
TASK_QUESTION_QUEUE_MAX = 5

# Состояния, в которых конвейер спрашивает сам. Общее у них одно: строка стоит и
# сама не сдвинется. `failed_qa` сюда входит намеренно, хотя попытки ещё есть, —
# круг с тем же охватом даст тот же вердикт, и дождаться `blocked`, чтобы только
# потом спросить, значит потратить две попытки на подтверждение известного.
TASK_QUESTION_STUCK_STATES = ('blocked', 'failed_qa', 'failed')

# Заголовок раздела с решениями в плане подзадачи. Ищется в тексте, поэтому
# менять его нельзя без разового прохода по существующим планам: не найдя старый
# заголовок, код заведёт второй раздел рядом.
TASK_QUESTION_PLAN_SECTION = '## Решения по развилкам'

# Ключи действий в автовопросе. Ответ на него не просто записывается — он что-то
# делает с подзадачей, и по ключу вызывающий понимает, что именно.
TASK_QUESTION_ACTION_SPLIT = 'goals_split'
TASK_QUESTION_ACTION_DROP = 'goals_drop'
TASK_QUESTION_ACTION_RETRY = 'goals_keep'

# Вернуть строку менеджеру на разбиение. Не действие над целями, в отличие от
# соседей, а признание, что охват задали неподъёмный: строка уходит в состояние
# `new`, откуда её забирает планирование, и менеджер раскладывает её на подзадачи
# следующего уровня. Отдельной ветки для этого не нужно — рекурсия дробления уже
# устроена так же (`task_state._subtask_state`).
TASK_QUESTION_ACTION_PLAN = 'goals_replan'

# Сколько прогонов подряд считаем оборванными, чтобы говорить «объём не влезает».
# Один таймаут — случайность (зависла оболочка, упёрлись в контекст), два подряд
# — уже свойство подзадачи.
TASK_QUESTION_TIMEOUT_HINT = 2

# Короче этого прогон не считается попыткой: столько не длится даже самый быстрый круг
# агента — он читает проект, думает и пишет, это минуты. Уложившийся в минуту прогон
# кончился поломкой: не собрался промпт, оболочка не ответила, круг упал на первом шаге.
#
# Минута с запасом: живьём такие срывы укладывались в 7–26 секунд.
TASK_QUESTION_INSTANT_RUN_MS = 60000


def task_question_parse(report: dict | None) -> dict:
    """
    Достать вопрос из отчёта роли. Нет вопроса — `{}`.

    Терпимо к форме: `question` приходит и строкой («просто спросил»), и объектом
    с вариантами. Строку разворачиваем в объект без вариантов — человек ответит
    свободным текстом. Так промпту не нужно попадать в структуру с первого раза,
    а мы не теряем вопрос из-за того, что агент поленился завести массив.

    Вопрос без текста не вопрос: пустую строку и объект без `text` отбрасываем,
    иначе подзадача встала бы в `blocked` с пустым попапом.
    """
    raw = (report or {}).get(TASK_QUESTION_KEY)
    if isinstance(raw, str):
        raw = {'text': raw}
    if not isinstance(raw, dict):
        return {}

    text = str(raw.get('text') or raw.get('question') or '').strip()
    if not text:
        return {}

    return {
        'text':    text[:TASK_QUESTION_TEXT_MAX],
        'options': _options_parse(raw.get('options')),
        # Несколько вариантов сразу имеют смысл не всегда: «переименовать или
        # оставить» — выбор одного, «что из этого делать» — набор. Решает
        # спрашивающий, умолчание — один вариант, как более частый случай.
        'multi':   bool(raw.get('multi')),
        'asked_at': _now(),
    }


async def task_question_set(subtask_id: int, question: dict, role: str = '') -> None:
    """
    Положить вопрос в мешок подзадачи. Пустой вопрос ничего не делает.

    Вопрос приводим к канону тем же разбором, что и на входе от роли
    (`task_question_parse`): варианты становятся объектами `{key, label}`, текст
    обрезается по пределу.

    Раньше клали как дали. Пути, идущие через конвейер, приносят уже разобранный
    вопрос, и работало это годами — но всякий, кто позовёт функцию со списком строк в
    `options`, положит в мешок строки, а `_answer_labels` при ответе зовёт у них
    `.get()` и падает с `'str' object has no attribute 'get'`. Ошибка вылезает не при
    записи, а при ответе человека, и по тексту не сводится к причине.
    """
    if not subtask_id or not question:
        return

    parsed = task_question_parse({TASK_QUESTION_KEY: question})
    if not parsed:
        return

    # Пометки, которых нет в общей форме, переносим как есть: `auto`, `dialog`,
    # `back_state` — по ним `_answer_after` решает, куда вернуть строку.
    extra = {k: v for k, v in question.items() if k not in parsed}

    await task_metadata_update(int(subtask_id),
                               {TASK_QUESTION_KEY: {**extra, **parsed, 'role': str(role or '')}})


async def task_question_set_many(subtask_id: int, questions: list, role: str = '') -> int:
    """
    Положить пачку вопросов разведки. Returns: сколько принято.

    Ответов у них пока нет — они появятся черновиками, по мере того как человек будет
    отвечать. Пустые и бестекстовые отбрасываем тем же разбором, что и одиночный
    вопрос: пустой попап хуже отсутствующего.

    Одиночный вопрос роли этим не затрагивается: у него свой ключ и свой путь.
    """
    clean = []
    for item in (questions or [])[:TASK_QUESTION_QUEUE_MAX]:
        parsed = task_question_parse({TASK_QUESTION_KEY: item})
        if parsed:
            clean.append({**parsed, 'role': str(role or ''), 'answer': None})

    if not subtask_id or not clean:
        return 0

    await task_metadata_update(int(subtask_id), {TASK_QUESTION_KEY_QUEUE: clean})

    return len(clean)


def task_question_batch(subtask: dict | None) -> list:
    """Пачка вопросов с черновиками ответов. Нет пачки — пустой список."""
    meta = task_metadata_parse((subtask or {}).get('metadata'))
    batch = meta.get(TASK_QUESTION_KEY_QUEUE)

    return [q for q in batch if isinstance(q, dict) and q.get('text')] if isinstance(batch, list) else []


def task_question_batch_left(subtask: dict | None) -> int:
    """Сколько вопросов пачки ещё без ответа. Ноль — либо пачки нет, либо всё отвечено."""
    return sum(1 for q in task_question_batch(subtask) if not (q.get('answer') or {}).get('text'))


async def task_question_batch_answer(subtask_id: int, subtask: dict, index: int,
                                     answers: list | None, note: str = '',
                                     by: str = '') -> dict:
    """
    Ответ на один вопрос пачки — черновиком. Отвечены все — пачка уходит в решения.

    Args:
        index: какой вопрос пачки. Порядок свободный: человек отвечает как ему удобно
            и возвращается к уже отвеченным, потому что ответ на третий вопрос нередко
            меняет ответ на первый.

    Returns:
        `{'left': сколько без ответа, 'done': отвечены ли все, 'decisions': [...]}`.
        `decisions` непусты только в момент, когда пачка закрылась.

    Черновик перезаписывается молча: правка ответа — обычное дело, пока пачка открыта,
    и хранить историю черновиков незачем — в решения уедет последний.

    В решения пачка уезжает разом и только целиком. До этого ответы — черновики, и
    роль их не видит: половина развилок, поданная как решённая, хуже, чем ни одной, —
    агент принял бы её за полный ответ и спланировал по нему.

    Задачу это не держит: вопрос менеджера её и не останавливал (план пишется по
    допущению, ответ приходит к пересмотру), а держать её ради ответов значило бы
    остановить работу, которая идёт.
    """
    batch = task_question_batch(subtask)
    if not batch or not 0 <= int(index) < len(batch):
        return {}

    question = batch[int(index)]
    labels = _answer_labels(question, answers)
    free = str(note or '').strip()[:TASK_QUESTION_ANSWER_MAX]
    text = '; '.join([*labels, free] if free else labels)
    if not text:
        return {}

    # В черновике держим и разобранный текст, и то, чем человек его набрал: вернувшись
    # к отвеченному вопросу, он должен увидеть свой выбор отмеченным, а не пустую форму.
    # Без ключей и заметки попап показал бы «ответ есть», но чем именно — неизвестно, и
    # правка превратилась бы в ответ заново.
    batch[int(index)] = {**question, 'answer': {
        'text': text,
        'keys': [str(a) for a in (answers or [])],
        'note': free,
        'at': _now(),
        'by': str(by or ''),
    }}
    left = sum(1 for q in batch if not (q.get('answer') or {}).get('text'))

    if left:
        await task_metadata_update(int(subtask_id), {TASK_QUESTION_KEY_QUEUE: batch})
        return {'left': left, 'done': False, 'decisions': []}

    # Пачка закрылась — черновики становятся решениями разом и в порядке вопросов.
    fresh = [{'at': q['answer']['at'], 'question': str(q.get('text') or '').strip(),
              'answer': q['answer']['text'], 'by': q['answer'].get('by') or ''}
             for q in batch]
    decisions = [*task_question_decisions(subtask), *fresh][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(int(subtask_id), {
        TASK_QUESTION_KEY_QUEUE: None,
        TASK_QUESTION_KEY_DECISIONS: decisions,
    })

    return {'left': 0, 'done': True, 'decisions': fresh}


def task_question_get(subtask: dict | None) -> dict:
    """Вопрос из уже прочитанной строки подзадачи. Нет вопроса — `{}`."""
    meta = task_metadata_parse((subtask or {}).get('metadata'))
    question = meta.get(TASK_QUESTION_KEY)

    return question if isinstance(question, dict) and question.get('text') else {}


def task_question_decisions(subtask: dict | None) -> list:
    """Принятые по подзадаче решения, старые первыми. Нет решений — пустой список."""
    meta = task_metadata_parse((subtask or {}).get('metadata'))
    decisions = meta.get(TASK_QUESTION_KEY_DECISIONS)

    return [d for d in decisions if isinstance(d, dict)] if isinstance(decisions, list) else []


async def task_question_answer(subtask_id: int, subtask: dict, answers: list | None,
                               note: str = '', by: str = '', question: dict | None = None) -> dict:
    """
    Записать ответ человека: решение — в список, вопрос — из мешка вон.

    Выбранные варианты и свободный текст складываются в одну строку: агенту важно
    решение, а не то, кликом оно пришло или набором. Пустой ответ — отказ: вопрос
    остаётся на месте, иначе подзадача ушла бы в работу с той же развилкой и
    следующим кругом спросила бы снова.

    `question` передают снаружи, потому что вопрос конвейера в мешке не лежит — он
    собирается из фактов при чтении. Не передали — берём из мешка. Без этого у
    ответа на автовопрос терялись бы и сам вопрос, и подписи вариантов: в решение
    попал бы голый ключ `goals_split`, который роль следующим кругом не прочтёт.

    Returns: записанное решение, либо `{}` если отвечать было нечем.
    """
    question = question or task_question_get(subtask)
    labels   = _answer_labels(question, answers)
    free     = str(note or '').strip()[:TASK_QUESTION_ANSWER_MAX]
    text     = '; '.join([*labels, free] if free else labels)
    if not text:
        return {}

    decision = {
        'at':       _now(),
        'question': str(question.get('text') or '').strip(),
        'answer':   text,
        'by':       str(by or ''),
    }
    # Список пишем целиком, а не патчем по индексу: JSON_MERGE_PATCH заменяет
    # массив, и дописать в него можно только собранным заново. Гонки тут не
    # страшны — решения принимает человек со страницы, конвейер в этот ключ не
    # пишет.
    decisions = [*task_question_decisions(subtask), decision][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(int(subtask_id),
                               {TASK_QUESTION_KEY: None, TASK_QUESTION_KEY_DECISIONS: decisions})

    return decision


def task_question_auto(subtask: dict, attempts: list, max_attempts: int = 0) -> dict:
    """
    Вопрос от конвейера — когда роль не спросила, а подзадача всё равно встала.

    Второго вида сущности тут нет и быть не должно. Человеку всё равно, кто
    сформулировал развилку: он открывает подзадачу, которая не движется, и хочет
    видеть вопрос с вариантами. Разница только в авторе — роль спрашивает о том,
    чего не вправе решать, конвейер о том, чего не смог сделать.

    Вопрос собирается из фактов, а не из догадок: сколько кругов потрачено,
    сколько из них оборвалось по таймауту, что говорил последний вердикт. Вывод о
    причине даётся отдельной фразой и со словом «похоже» — по пяти прогонам он
    правдоподобен, но не доказан, и выдавать его за диагноз нечестно.

    Варианты — действия над охватом подзадачи, потому что именно охват здесь
    обычно и не сходится: цель, не влезающая в круг, будет не влезать в него и на
    четвёртый раз. Что делать с целями — такой же вопрос, как «переименовывать ли
    инструменты»: ответ на него меняет работу, а принять его вправе только человек.

    Returns: вопрос той же формы, что и у роли, плюс `auto: True`. Подзадача,
    которую и спрашивать не о чем (работа идёт, попытки не исчерпаны), — `{}`.
    """
    state = str(subtask.get('pipeline_state') or '')
    if state not in TASK_QUESTION_STUCK_STATES:
        return {}

    facts = _attempts_facts(attempts)
    goals = [g for g in _goals_list(subtask) if not g.get('done')]

    return {
        'text':    _stuck_text(subtask, facts, max_attempts),
        'options': _stuck_options(goals),
        'multi':   False,
        'auto':    True,
        'asked_at': _now(),
    }


async def task_question_plan_append(subtask_id: int, subtask: dict, decision: dict,
                                    question: dict) -> bool:
    """
    Дописать вопрос и ответ в план подзадачи. Returns: `True`, если дописали.

    Зачем в план, если решение и так уходит в промпт. Промпт видит только роль, а
    план видит человек — на странице, на следующий день, при разборе «почему
    сделано так». Живой вопрос был именно об этом: «я ответил, но нигде не вижу
    ни вопроса, ни ответа, и непонятно, дойдёт ли до роли». План — то место, где
    он и должен быть виден: это описание работы, а решение развилки — часть
    описания.

    Дописываем, а не переписываем: план пишет менеджер, и правка его текста
    здесь означала бы, что план у подзадачи уже не тот, что был утверждён.
    Решения идут отдельным разделом в конце, каждое своей строкой.

    Раздел заводим один и потом дополняем: развилок по одной подзадаче бывает
    несколько, и три одинаковых заголовка подряд читались бы как ошибка.

    План у подзадачи — обычный текст (у задачи целиком там JSON, и её плана это
    не касается: вопрос менеджера приходит вместе с планом, а не после него).
    """
    if not subtask_id or not decision:
        return False

    plan = str((subtask or {}).get('pipeline_plan') or '')
    text = _one_line(question.get('text'))
    answer = _one_line(decision.get('answer'))
    if not answer:
        return False

    entry = (f"- **Вопрос ({decision.get('at') or ''}):** {text}\n"
             f"  **Решение ({decision.get('by') or 'человек'}):** {answer}\n")
    plan = (plan.rstrip() + '\n' + entry if TASK_QUESTION_PLAN_SECTION in plan
            else plan.rstrip() + f'\n\n{TASK_QUESTION_PLAN_SECTION}\n' + entry)

    async with mysql_get_db_async() as db:
        await db.execute('UPDATE project_task SET pipeline_plan = %s WHERE id = %s',
                         (plan, int(subtask_id)))
        await db.connection.commit()

    return True


def task_question_decisions_text(subtask: dict | None) -> str:
    """
    Решения для промпта роли. Нет решений — пустая строка.

    Пустая строка ложна для `%if%` в промптах — блок про решения просто не
    раскроется, и промпт останется прежним. Это и есть способ не трогать
    подзадачи, по которым никто ничего не решал.

    Формулировка обязывающая, а не справочная: «принято решение» роль читает как
    контекст и спокойно делает по-своему, а развилка ровно в том, чтобы она так
    не поступала.
    """
    decisions = task_question_decisions(subtask)
    if not decisions:
        return ''

    lines = []
    for item in decisions:
        question = str(item.get('question') or '').strip()
        answer   = str(item.get('answer') or '').strip()
        if not answer:
            continue
        lines.append(f'- Вопрос: {question}\n  Решение: {answer}' if question else f'- {answer}')

    return '\n'.join(lines)


def _one_line(text) -> str:
    """Текст в одну строку: и план, и журнал читают построчно."""
    return ' '.join(str(text or '').replace('\\n', ' ').split())


def _attempts_facts(attempts: list) -> dict:
    """
    Что видно по журналу попыток: сколько кругов, сколько оборвалось, последний итог.

    Оборванный прогон отличаем по тексту ошибки, а не по статусу: в журнале
    попыток у него тот же `error`, что и у честной неудачи, — конвейер разделяет
    их флагом `env_ok`, которого здесь уже нет.

    **Мгновенные срывы за попытки не считаем.** Прогон короче минуты — это не работа
    агента, а поломка установки: не собрался промпт, оболочка не ответила, круг упал
    на первом шаге. Настоящий круг столько не длится, он идёт минутами.

    Считать их наравне с работой опасно тем, что вывод о причине делается по их числу.
    Живьём: подзадача #5219 набрала шесть срывов по 7–26 секунд, когда миграция сломала
    JSON промпта и движок слал агенту пустоту. Автовопрос увидел «8 прогонов, 6
    оборвалось, 19 минут» и объявил неподъёмным охват — то есть предложил дробить
    работу, к которой поломка не имела никакого отношения. Ответь человек «раздробить»
    — и подзадача была бы разрезана впустую.

    В счёт прогонов такие срывы всё же входят: они были, и человек вправе о них знать.
    Из них не строится только вывод о причине.
    """
    runs = [a for a in (attempts or []) if isinstance(a, dict)]
    broken = [a for a in runs if _run_broken(a) and not _run_instant(a)]
    real   = [a for a in runs if not _run_broken(a)]
    instant = [a for a in runs if _run_broken(a) and _run_instant(a)]

    return {
        'runs':     len(runs),
        'broken':   len(broken),
        'real':     len(real),
        'instant':  len(instant),
        'last':     str((real[-1] if real else runs[-1] if runs else {}).get('error') or '').strip(),
        'minutes':  sum(int(a.get('duration_ms') or 0) for a in runs) // 60000,
    }


def _run_instant(attempt: dict) -> bool:
    """
    Прогон кончился быстрее, чем агент успел бы что-то сделать.

    Порог сравниваем строго: прогон ровно в минуту — уже спорный случай, и относить
    его к поломке значило бы прятать пограничную работу от разбора.

    Без длительности вовсе (старая запись, сбой замера) считаем прогон настоящим:
    молча выкидывать из статистики то, о чём ничего не известно, — худший вид
    догадки.
    """
    duration = attempt.get('duration_ms')
    if duration in (None, ''):
        return False

    try:
        return int(duration) < TASK_QUESTION_INSTANT_RUN_MS
    except (TypeError, ValueError):
        return False


def _run_broken(attempt: dict) -> bool:
    """Прогон оборвался, а не завершился неудачей: агент не ответил."""
    error = str(attempt.get('error') or '')

    return 'не ответил' in error or 'прогон не состоялся' in error or 'timeout' in error.lower()


def _stuck_text(subtask: dict, facts: dict, max_attempts: int) -> str:
    """
    Текст автовопроса: факты, осторожный вывод, вопрос.

    Вывод отделён от фактов намеренно. Факты проверяемы — они прямо из журнала
    попыток; вывод о причине выведен из них и может быть неверен, поэтому идёт со
    словом «похоже» и отдельной строкой. Человек должен видеть, где кончается
    отчёт и начинается догадка.
    """
    used  = int(subtask.get('pipeline_attempt_count') or 0)
    limit = f' из {max_attempts}' if max_attempts else ''
    lines = [f'Подзадача встала: кругов потрачено {used}{limit}, прогонов {facts["runs"]}'
             + (f', из них оборвалось по таймауту {facts["broken"]}' if facts['broken'] else '')
             + (f', сорвалось мгновенно {facts["instant"]}' if facts.get('instant') else '')
             + (f', времени ушло {facts["minutes"]} мин' if facts['minutes'] else '') + '.']

    if facts['last']:
        lines.append(f'Последний итог: {facts["last"][:600]}')

    # Мгновенные срывы называем отдельной строкой: они в счёт прогонов входят, но
    # вывод о причине по ним не делается, и человек не должен гадать, почему цифры
    # не сходятся с выводом.
    if facts.get('instant'):
        lines.append(f'Из них {facts["instant"]} прогон(ов) оборвались за секунды — так '
                     f'выглядит не работа, а поломка установки: не собрался промпт, не '
                     f'ответила оболочка. В выводе о причине они не учитывались.')

    if facts['broken'] >= TASK_QUESTION_TIMEOUT_HINT:
        lines.append('Похоже, объём не влезает в круг: работа каждый раз начинается, '
                     'но не доводится до конца, и следующий круг с тем же охватом '
                     'кончится тем же.')
    elif facts['real'] >= TASK_QUESTION_TIMEOUT_HINT:
        lines.append('Похоже, дело не во времени: прогоны доходили до отчёта, но работа '
                     'не сходилась по существу.')

    lines.append('Что делаем?')

    return '\n\n'.join(lines)


def _stuck_options(goals: list) -> list:
    """
    Варианты автовопроса — что делать с охватом вставшей подзадачи.

    Дробление первым: у вставшей подзадачи чаще всего слишком большой охват, а
    дробление, в отличие от сокращения, работу не выбрасывает — она уезжает в
    соседнюю строку и будет сделана отдельным кругом.

    **Одна цель — дробить нечего.** Развилка тут ложная: раздробить единственную
    цель невозможно, а убрать её значит отменить подзадачу. Настоящая причина в
    другом: раз строка встала, а работы не вышло, значит охват ей задали
    неподъёмный — то есть ошибся не исполнитель, а планирование. Поэтому вместо
    двух пустых кнопок предлагаем то, что действительно поможет: вернуть строку
    менеджеру, чтобы он разложил её на подзадачи третьего уровня.

    Целей не осталось (все закрыты или их не заводили) — трогать нечего, и
    варианты про цели были бы кнопками в пустоту: остаётся перезапуск.
    """
    if not goals:
        return [{'key': TASK_QUESTION_ACTION_RETRY, 'label': 'Перезапустить как есть',
                 'hint': 'Охват не меняем, счётчик попыток обнуляется'}]

    if len(goals) == 1:
        return [
            {'key': TASK_QUESTION_ACTION_PLAN, 'label': 'Отправить на планирование: разложить на подзадачи',
             'hint': 'Менеджер разберёт эту строку заново и разложит её на несколько мелких. '
                     'Цель одна и неподъёмна — дробить её нечем, а повтор с тем же охватом '
                     'кончится тем же'},
            {'key': TASK_QUESTION_ACTION_RETRY, 'label': 'Перезапустить как есть',
             'hint': 'Охват не меняем, счётчик попыток обнуляется. Имеет смысл, если мешало '
                     'что-то разовое, а не объём'},
        ]

    return [
        {'key': TASK_QUESTION_ACTION_SPLIT, 'label': 'Раздробить: часть целей — в новую подзадачу',
         'hint': 'Отмеченные цели уедут в соседнюю подзадачу и будут сделаны своим кругом. '
                 'Работа не теряется, охват этой строки становится меньше'},
        {'key': TASK_QUESTION_ACTION_DROP, 'label': 'Сократить: убрать отмеченные цели',
         'hint': 'Цели исчезают из подзадачи вовсе. Берите, когда работа по ним не нужна, '
                 'а не когда она просто не влезает'},
        {'key': TASK_QUESTION_ACTION_RETRY, 'label': 'Перезапустить как есть',
         'hint': 'Охват не меняем, счётчик попыток обнуляется. Имеет смысл, если мешало '
                 'что-то разовое, а не объём'},
    ]


def _goals_list(subtask: dict) -> list:
    """Цели подзадачи списком `[{text, done}]`. Разбор общий с планом — `task_plan`."""
    from src.project.task.task_plan import task_plan_goals_normalize

    return task_plan_goals_normalize(subtask.get('goals'))


def _now() -> str:
    """Метка времени решения — в UTC, как всё хранимое.

    В пояс настройки `timezone` её переводит страница при показе: хранить местное
    время значило бы, что смена настройки задним числом переписывает историю
    решений. См. `.claude/docs-common/datetime_rules.md`.
    """
    return datetime_utc_now().strftime('%Y-%m-%d %H:%M:%S')


def _options_parse(raw) -> list:
    """
    Варианты ответа к виду `{key, label}`.

    Терпимо к форме по той же причине, что и сам вопрос: агент присылает то
    массив строк, то массив объектов, то объект «ключ -> подпись». Ключ нужен,
    чтобы ответ пришёл обратно опознаваемым; своего у варианта может не быть —
    тогда ключом становится номер.
    """
    if isinstance(raw, dict):
        raw = [{'key': k, 'label': v} for k, v in raw.items()]
    if not isinstance(raw, list):
        return []

    options = []
    for number, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {'label': item}
        if not isinstance(item, dict):
            continue
        label = str(item.get('label') or item.get('text') or item.get('title') or '').strip()
        if not label:
            continue
        options.append({
            'key':   str(item.get('key') or number),
            'label': label[:TASK_QUESTION_OPTION_MAX],
            'hint':  str(item.get('hint') or item.get('description') or '').strip()[:TASK_QUESTION_OPTION_MAX],
        })
        if len(options) >= TASK_QUESTION_OPTIONS_MAX:
            break

    return options


def _answer_labels(question: dict, answers: list | None) -> list:
    """
    Ключи выбранных вариантов -> их подписи.

    В решение пишем подпись, а не ключ: читать его будет агент следующим кругом,
    а к тому времени вопроса в мешке уже нет, и ключ `2` не значит ничего.
    Неизвестный ключ пропускаем — вопрос мог смениться, пока попап был открыт.
    """
    if not answers:
        return []

    by_key = {str(o.get('key')): str(o.get('label') or '') for o in question.get('options') or []}

    return [by_key[key] for key in (str(a) for a in answers) if by_key.get(key)]
