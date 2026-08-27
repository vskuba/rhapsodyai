"""
Вопросы по подзадаче и ответы человека — API страницы задач.

Вопрос здесь один как понятие, хотя авторов у него два. Роль спрашивает о том,
чего не вправе решать сама (`metadata.question`); конвейер — о том, чего не смог
сделать: подзадача встала, попытки жгутся, и дальше нужно решение об охвате
(`task_question_auto`). Для человека это одно и то же действие — открыть строку,
которая не движется, и ответить, — поэтому и endpoint один.

Ответ на вопрос роли только записывается. Ответ на вопрос конвейера ещё и
исполняется: варианты там — действия над целями (`task_goal_scope`), и выбор
«раздробить» без самого дробления был бы обещанием, а не ответом.

Механика вопроса — `src/project/task/task_question.py`, действия над охватом —
`src/project/task/task_goal_scope.py`.
"""
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from datetime_.datetime_ import datetime_offset_apply, datetime_utc_now
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_get
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.task.task_goal_replan import TASK_GOAL_REPLAN_STATE, task_goal_replan_send
from src.project.task.task_goal_scope import task_goal_scope_drop, task_goal_scope_split
from src.project.task.task_log import task_log_dir
from src.project.task.task_log_decision import task_log_decision_write
from src.project.task.task_metadata import task_metadata_row_apply
from src.project.task.task_plan import task_plan_goals_normalize
from src.project.task.task_role import task_role_project_work_dir
from src.project.task.task_question import (TASK_QUESTION_ACTION_DROP,
                                            TASK_QUESTION_ACTION_PLAN,
                                            TASK_QUESTION_ACTION_RETRY,
                                            TASK_QUESTION_ACTION_SPLIT, task_question_answer,
                                            task_question_auto, task_question_decisions,
                                            task_question_get, task_question_plan_append)
from src.project.task.task_report import task_report_write
from src.project.task.task_setting_timeout import (TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
                                                   task_setting_timeout_get)
from src.project.task.task_state import task_state_subtask_set, task_state_task_requeue

router = APIRouter()

# Куда возвращается подзадача после ответа. `planned` — начало круга Developer → QA:
# ответ меняет условия работы, и правильный следующий шаг — заново взяться за
# подзадачу, а не отдать на проверку то, что сделано до развилки.
TASK_QUESTION_STATE_BACK = 'planned'

# Сколько последних попыток показываем: по ним человек видит, обрывались прогоны
# или доходили до отчёта. Глубже смотреть незачем — лимит кругов всё равно меньше.
TASK_QUESTION_ATTEMPTS_MAX = 10


class TaskQuestionAnswer(BaseModel):
    """Ответ человека: выбранные варианты, отмеченные цели и свободный текст."""
    answers: list[str] = []
    note: str = ''
    goal_indexes: list[int] = []


@router.get('/task/{task_id}/question')
async def project_task_question_get(task_id: int,
                                    user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Вопрос по подзадаче, её цели и уже принятые решения.

    Вопрос роли имеет приоритет над вопросом конвейера: роль спросила о конкретной
    развилке, и подменять её вопрос общим «что делаем с целями» значит потерять
    то, ради чего прогон вообще остановился.

    Цели отдаём всегда, а не только с автовопросом: человек, отвечающий на вопрос
    роли, тоже смотрит, чем подзадачу примут.
    """
    subtask = await _subtask_row(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='task not found')

    attempts = await _attempts(task_id)
    question = task_question_get(subtask)
    # Автовопрос — только по подзадаче: его варианты дробят и сокращают цели, а у
    # задачи целиком цели ведёт план менеджера, и охват там меняют не так.
    if not question and subtask.get('parent_id'):
        question = task_question_auto(subtask, attempts,
                                      await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX))

    return {
        'question':  question,
        'decisions': task_question_decisions(subtask),
        'goals':     task_plan_goals_normalize(subtask.get('goals')),
        'attempts':  attempts,
        'state':     subtask.get('pipeline_state') or '',
        'error':     subtask.get('pipeline_error') or '',
        'title':     subtask.get('title') or '',
    }


@router.post('/task/{task_id}/question/answer')
async def project_task_question_answer(task_id: int, body: TaskQuestionAnswer,
                                       user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Ответить на вопрос и вернуть подзадачу в работу.

    Действие над целями исполняется до записи решения: дробление и сокращение
    могут отказать (отмечены все цели, не отмечено ни одной), и записывать решение
    о том, чего не произошло, нельзя — роль прочла бы его следующим кругом как
    свершившееся.

    Счётчик попыток обнуляем. Вопрос застаёт подзадачу на любом круге, и после
    ответа у неё должен быть полный запас: круги до вопроса потрачены на работу,
    которая упиралась в нерешённое, — считать их за неудачи нечестно, и без
    обнуления подзадача, спросившая на третьем круге, вернулась бы в `blocked`
    первым же прогоном.

    Замечание QA (`pipeline_error`) затираем — в отличие от «Перезапустить». Там
    оно единственное, что говорит следующему кругу, чего не хватило; здесь на его
    месте стоит либо текст вопроса, либо вердикт, который ответом уже учтён.
    """
    subtask = await _subtask_row(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='task not found')

    # Вопрос берём тот же, что показывали: у автовопроса в мешке ничего не лежит, и
    # без него в решение попал бы голый ключ `goals_split` вместо подписи варианта.
    question = task_question_get(subtask)
    if not question and not subtask.get('parent_id'):
        # Автовопрос — про охват подзадачи: его варианты дробят и сокращают цели,
        # а у корневой задачи цели ведёт план, и трогать их отсюда нельзя.
        raise HTTPException(status_code=409,
                            detail='По задаче целиком вопрос задаёт только менеджер при планировании')
    if not question:
        question = task_question_auto(
            subtask, await _attempts(task_id),
            await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX))

    scope = await _scope_apply(subtask, body)
    if scope and not scope.get('ok'):
        raise HTTPException(status_code=400, detail=scope.get('error') or 'Действие над целями не выполнено')

    decision = await task_question_answer(task_id, subtask, body.answers,
                                          _note_with_scope(body.note, scope), user.username,
                                          question=question)
    if not decision:
        raise HTTPException(status_code=400, detail='Ответ пустой: выберите вариант или напишите решение')

    # Ответ должен быть виден человеку, а не только роли. В мешке он уже есть и в
    # промпт уйдёт сам; здесь раскладываем его по двум местам, куда человек
    # смотрит: план подзадачи и журнал строки.
    await _answer_show(task_id, subtask, decision, question)

    state = await _answer_after(subtask, task_id, user.username, decision, question,
                                TASK_GOAL_REPLAN_STATE if scope.get('subtask_id') and TASK_QUESTION_ACTION_PLAN in {str(a) for a in body.answers} else '')

    return {'ok': True, 'decision': decision, 'state': state, 'scope': scope}


async def _answer_show(task_id: int, subtask: dict, decision: dict, question: dict) -> None:
    """
    Показать решение человеку: в плане подзадачи и в журнале строки.

    Два места, потому что смотрят в них по-разному. План отвечает на вопрос
    «почему работа устроена так» — там решение живёт постоянно, рядом с
    описанием. Журнал отвечает на «что происходило и когда» — там оно встаёт по
    времени, между кругом, который упёрся в развилку, и кругом, который пошёл
    дальше.

    Ни то, ни другое не обязательно для работы: роль получает решение из мешка
    через промпт. Поэтому сбой любой из записей ответ не отменяет — теряется
    видимость, а не решение.

    По задаче целиком план не трогаем: там он JSON плана всей работы, а вопрос
    менеджера приходит вместе с ним, а не после, — дописывать в него нечего.
    """
    if subtask.get('parent_id'):
        with suppress(Exception):
            await task_question_plan_append(task_id, subtask, decision, question)

    with suppress(Exception):
        offset = await setting_get('timezone', '+0')
        task_log_decision_write(
            task_log_dir(await task_role_project_work_dir(subtask.get('project_id')), task_id),
            decision, question,
            datetime_offset_apply(datetime_utc_now(), offset),
            str(question.get('role') or ''))


async def _answer_after(subtask: dict, task_id: int, username: str, decision: dict,
                        question: dict, scope_state: str = '') -> str:
    """
    Что делать со строкой после ответа. Возвращает её состояние.

    У подзадачи ответ возвращает круг: она уходит в `planned` с обнулённым
    счётчиком. Счётчик обнуляем потому, что круги до вопроса упирались в
    нерешённое — считать их неудачами нечестно, и подзадача, спросившая на третьем
    круге, иначе вернулась бы в `blocked` первым же прогоном.

    У задачи целиком всё зависит от того, кто спросил, и различает их пометка
    `dialog` в самом вопросе:

    * **Менеджер вместе с планом** — возвращать нечего. Задача уже стоит там, где
      её ждёт человек, на утверждении; решение записано и уйдёт в промпт, если
      план отправят на пересмотр. Тронуть состояние здесь значило бы вырвать
      задачу из-под утверждения ответом на вопрос.
    * **Оболочка встала на диалоге Claude Code** (`task_shell_dialog`) — задача
      лежит в `failed`, и без возврата она осталась бы там навсегда: круга не
      было, а ответ снял то, из-за чего он не состоялся. Возвращаем туда, откуда
      её сняли, — `back_state` запомнил сам придержавший (`_dialog_hold`):
      планирование ждёт задачу в `new`, пересмотр плана — в `reviewing`.
    """
    title = str(subtask.get('title') or '').strip()

    if not subtask.get('parent_id'):
        back = str((question or {}).get('back_state') or '') if (question or {}).get('dialog') else ''
        if back:
            await task_state_task_requeue(task_id, back, '')
        await task_report_write(
            task_id,
            f"Решение принято ({username}) — {decision['answer']}"
            + (f'. Задача возвращена в работу ({back})' if back else ''),
            ok=True)
        return back or str(subtask.get('pipeline_state') or '')

    # Возврат менеджеру уже поставил строке своё состояние (`new`), и общий
    # `planned` его перебил бы — строка ушла бы не на планирование, а в круг с тем
    # же неподъёмным охватом, ради ухода от которого её и вернули.
    if str(scope_state or '') == TASK_GOAL_REPLAN_STATE:
        await task_report_write(
            int(subtask['parent_id']),
            f"Подзадача #{task_id}: решение принято ({username}) — {decision['answer']}. "
            f"Возвращена менеджеру на разбиение", ok=True)
        return TASK_GOAL_REPLAN_STATE

    await task_state_subtask_set(task_id, TASK_QUESTION_STATE_BACK, last_error='', attempt_count=0)
    label = f'Подзадача #{task_id}' + (f' «{title}»' if title else '')
    await task_report_write(int(subtask['parent_id']),
                            f"{label}: решение принято ({username}) — {decision['answer']}. "
                            f"Возвращена в работу, попытки обнулены", ok=True)

    return TASK_QUESTION_STATE_BACK


async def _scope_apply(subtask: dict, body: TaskQuestionAnswer) -> dict:
    """
    Исполнить действие над целями, если оно выбрано. Нечего делать — `{}`.

    Ключи действий приходят только из автовопроса; ответ на вопрос роли их не
    содержит, и проверять тип вопроса отдельно не нужно — достаточно посмотреть,
    что выбрано.
    """
    picked = {str(a) for a in (body.answers or [])}

    if TASK_QUESTION_ACTION_SPLIT in picked:
        return await task_goal_scope_split(subtask, body.goal_indexes)
    if TASK_QUESTION_ACTION_DROP in picked:
        return await task_goal_scope_drop(subtask, body.goal_indexes)
    # Возврат менеджеру — не действие над целями, а признание, что охват задали
    # неподъёмный: строка уходит в `new`, откуда её забирает планирование, и
    # менеджер раскладывает её на подзадачи следующего уровня.
    if TASK_QUESTION_ACTION_PLAN in picked:
        return await task_goal_replan_send(subtask)

    # `goals_keep` — осознанный отказ менять охват, а не отсутствие ответа: он
    # запишется решением, но делать по нему нечего.
    return {}


def _note_with_scope(note: str, scope: dict) -> str:
    """
    Дописать к ответу, что именно случилось с целями.

    Читать решение будет роль следующим кругом, и «раздробить» без перечня
    уехавшего для неё пустой звук: она увидит короткий список целей и примется
    искать, где остальные.
    """
    text = str(note or '').strip()
    if not scope or not scope.get('ok'):
        return text

    if scope.get('moved_text'):
        done = (f"вынесено в подзадачу #{scope['subtask_id']}: "
                + '; '.join(scope['moved_text']))
    elif scope.get('dropped_text'):
        done = 'убраны цели: ' + '; '.join(scope['dropped_text'])
    else:
        return text

    return f'{text} ({done})' if text else done


async def _attempts(task_id: int) -> list:
    """Последние попытки подзадачи, старые первыми — по ним собирается автовопрос."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT attempt_no, role, status, error, duration_ms, created_at "
            "  FROM project_task_attempt WHERE task_id = %s ORDER BY id DESC LIMIT %s",
            (task_id, TASK_QUESTION_ATTEMPTS_MAX))
        rows = await db.fetchall()

    return list(reversed(rows))


async def _subtask_row(task_id: int) -> dict | None:
    """Строка подзадачи с разобранным `metadata`. Нет строки — None."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()

    return task_metadata_row_apply(row) if row else None
