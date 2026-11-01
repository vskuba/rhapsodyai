from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth.auth import AuthChecker, auth_claude_secret_need
from src.auth.auth_permission import AuthPermission
from src.project.team.team_dsh import TeamDshError, team_dsh_state, team_dsh_switch
from src.project.team.team_dsh_card import team_dsh_card_add, team_dsh_card_drop
from src.project.team.team_dsh_host import team_dsh_host_restart
from src.project.team.team_dsh_project import (team_dsh_project_attach,
                                               team_dsh_project_detach)
from src.project.team.team_member import (team_member_activate,
                                          team_member_command_llm_normalize,
                                          team_member_deactivate,
                                          team_member_get, team_member_get_by_role,
                                          team_member_list, team_member_ping)
from src.project.team.team_project import (team_project_blocks_get,
                                           team_project_id_by_work_dir,
                                           team_project_session_work_dir_sync)
from src.project.team.team_session import team_session_restart
from src.project.team.team_session_cleanup import cleanup_inactive_sessions
from src.project.team.team_task_type import team_task_type_list
from src.project.team.team_llm_catalog import team_llm_catalog_models
from src.project.team.team_llm_ping import team_llm_ping_all, team_llm_ping_map
from src.project.team.team_llm_pool import (team_llm_pool_conflicts, team_llm_pool_set)
from src.project.team.team_setting_autocompact import team_setting_autocompact_apply
from src.project.task.task_setting_parallel import (
    TASK_SETTING_PARALLEL_OPTIONS,
    task_setting_parallel_set)
from src.project.task.task_setting_step import (task_setting_step_all,
                                                task_setting_step_key_is,
                                                task_setting_step_set)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_PING_STALE,
    task_setting_timeout_all,
    task_setting_timeout_get,
    task_setting_timeout_ladder_problem,
    task_setting_timeout_set)

router = APIRouter(prefix='/api/team', tags=['team'])


class TeamPingRequest(BaseModel):
    """Пинг от запущенной оболочки claude-shell.

    Идентификация — либо member_id (кнопки на /admin/team), либо role: оболочка
    знает свою роль из флага запуска (--manager/--developer/--qa), а числовой ID
    строки в project_team ей неизвестен.
    """

    member_id: int | None = None
    role: str | None = None
    pid: int | None = None
    session_uuid: str | None = None
    work_dir: str | None = None

    def session_get(self) -> dict:
        """Данные запущенной оболочки для записи в project_team."""
        return {'pid': self.pid, 'session_uuid': self.session_uuid,
                'work_dir': self.work_dir}


class TeamSessionRequest(BaseModel):
    """Действие над конкретной оболочкой claude-shell с карточки команды."""

    session_uuid: str


class TeamTimeoutRequest(BaseModel):
    """Правка одного таймаута с карточки команды."""

    key: str
    value: int


class TeamParallelRequest(BaseModel):
    """Правка предела «Parallel LLM» в шапке блока проекта.

    `project_id = 0` — блок «Без проекта» (оболочки вне проектов).
    """

    project_id: int
    value: int


class TeamDshRequest(BaseModel):
    """Кнопка «включить/выключить» на карточке роли DeepSeek Harness.

    Роль, а не id карточки: карточку заводит и архивирует сам пульт, а её id — его
    внутреннее дело. Страница знает роль и то, чего от неё хотят.

    `project` — корень каталога проекта, чья это роль. Пультов столько же, сколько
    проектов, и роли у них одноимённые: без проекта «включить developer» не адресовано
    никому. Адрес пульта страница не присылает намеренно — сервер находит его сам,
    иначе браузер выбирал бы, к кому в сети сходить.
    """

    project: str
    role: str
    enabled: bool


class TeamDshCardRequest(BaseModel):
    """Кнопка «+» рядом с выключателем и крестик на добавочной карточке роли.

    `card_id` пуст при добавлении — номер новой карточки выбирает пульт: между показом
    блока и нажатием кнопки карточки могли завестись и уйти в архив. При удалении он
    обязателен и называет карточку целиком: перезавод поколения меняет id, а страница
    показывает состояние прошлой сверки.
    """

    project: str
    role: str
    card_id: str = ''


class TeamDshProjectRequest(BaseModel):
    """Кнопка «подключить/отключить проект» в шапке блока.

    `project` — корень каталога, и берёт его страница из самого блока (`work_dir`), а не
    из поля ввода: путь у блока уже есть, а набранный руками означал бы, что каталог на
    машине разработчика выбирает браузер.

    `force` — ответ на уже заданный человеку вопрос: отключение гасит работающие роли и
    отправляет их карточки в архив, обрывая переписку. Без него пульт откажет, назвав
    роли, — и страница спросит.
    """

    project: str
    attached: bool
    force: bool = False


class TeamStatusResponse(BaseModel):
    id: int
    name: str
    role: str
    command: str
    work_dir: str
    status: str
    last_ping_at: datetime | None
    pid: int | None
    session_uuid: str | None


@router.get('', response_model=list[TeamStatusResponse])
async def project_team_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Получить список всех членов команды.

    Отдаёт work_dir, pid и session_uuid, поэтому требует авторизации — в отличие
    от POST-ов /ping, /activate, /deactivate, которые дёргает внешняя оболочка.
    """
    # Команду отдаём в том же виде, что и карточка блока: с приведённым флагом
    # модели и подставленным порогом автосжатия. В колонке лежит заготовка, и
    # сырой она врала бы дважды — старым флагом и старым числом. Расхождение
    # ловится только глазами; на нём и попался `test_copy_button_carries_command`,
    # где кнопка показывала подставленное значение, а этот список — заготовку.
    members = await team_member_list()
    for member in members:
        command = team_member_command_llm_normalize(member.get('command'))
        member['command'] = await team_setting_autocompact_apply(command) if command else command

    return members


@router.post('/ping', dependencies=[Depends(auth_claude_secret_need)])
async def project_team_ping(request: TeamPingRequest):
    """Обновить пинг члена команды — оболочка шлёт его, пока жива.

    ⚠⚠ Закрыто общим секретом оболочки (`X-Claude-Secret`), а не сессией: у
    запущенной claude-shell куки нет и быть не может. Раньше точка была
    публичной совсем — из белого списка `auth_middleware` она проходила заставу,
    а своей проверки не имела, и `status`/`pid`/`session_uuid` любого члена
    команды менялись одним curl-ом без всякого ключа.
    """
    member = await _member_resolve(request)
    await team_member_ping(member['id'], request.session_get())
    await team_project_session_work_dir_sync(request.session_uuid or '', request.work_dir or '')

    return {'success': True, 'member_id': member['id']}


@router.get('/projects')
async def project_team_projects_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Команда в разрезе проектов: блок на проект, внутри карточки ролей.

    Активность карточки считается на сервере — в реестре last_seen_at пишется в
    часовом поясе настройки, и браузер не знает, какой это пояс.
    """
    blocks = await team_project_blocks_get()
    stale_seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_PING_STALE)
    return {'result': {'blocks': blocks, 'stale_seconds': stale_seconds,
                       'parallel_options': list(TASK_SETTING_PARALLEL_OPTIONS)}}


@router.post('/parallel')
async def project_team_parallel_set(parallel_request: TeamParallelRequest,
                                    user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Записать предел «Parallel LLM» проекта — селект в шапке блока.

    `project_id = 0` — блок «Без проекта». Значение вне списка вариантов — 422.
    Отдельного GET нет: текущие пределы приходят вместе с блоками (`/projects`).
    """
    try:
        value = await task_setting_parallel_set(parallel_request.project_id, parallel_request.value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    return {'result': {'project_id': parallel_request.project_id, 'value': value}}


@router.post('/llm/pool')
async def project_team_llm_pool_set(data: dict,
                                    user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Записать пул моделей проекта — мультиселект в шапке блока.

    Пул задаёт, чем работают роли этого проекта и сколько их работает разом: предел
    параллельности выводится из его размера, отдельной настройки под это больше нет.

    Модель, занятая пулом другого проекта, отклоняется с 409: модели общие на машину,
    и две роли разных проектов, взявшие одну, поделили бы один прокси. Отказ, а не
    молчаливое исключение из списка: человек выбрал её осознанно и должен узнать,
    почему она не сохранилась.
    """
    project_id = int(data.get('project_id') or 0)
    names = data.get('names')
    if not isinstance(names, list):
        raise HTTPException(status_code=422, detail='names должен быть списком имён моделей')

    taken = await team_llm_pool_conflicts(project_id, names)
    if taken:
        where = ', '.join(f'{name} — у проекта #{pid}' for name, pid in taken.items())
        raise HTTPException(status_code=409, detail=f'модели уже заняты: {where}')

    saved = await team_llm_pool_set(project_id, names)

    return {'result': {'project_id': project_id, 'names': saved, 'parallel': len(saved) or 1}}


@router.get('/types')
async def project_team_task_types_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Получить все типы задач."""
    types = await team_task_type_list()
    return types


@router.get('/llm')
async def project_team_llm_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Модели для селекта в шапке блока — из каталога самой оболочки.

    Не из справочника `llm`: там модели, которые умеет вызывать этот проект, и он
    шире каталога оболочки. Селект, обещающий больше, чем `claude-shell` умеет
    поднять, приводит к отказу уже в терминале — а там его никто не ждёт.

    `problem` непустой, когда каталог не прочитан. Страницу это не роняет: селект
    остаётся с умолчанием, но человек видит причину, а не молча укороченный список.

    Вместе со списком отдаём последний пинг каждой модели (`pings`): по нему страница
    показывает, какие из них отвечают, а какие выведены из выдачи, — иначе неотвечающая
    модель выглядит в списке ровно как рабочая.
    """
    catalog = await team_llm_catalog_models()
    catalog['pings'] = await team_llm_ping_map(catalog.get('models') or [])

    return {'result': catalog}


@router.post('/llm/ping')
async def project_team_llm_ping(data: dict = None,
                                user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Пропинговать модели пула: названные в `names` либо все, что стоят в пулах.

    Права на изменение, а не на просмотр: пинг ходит к провайдеру и переписывает
    состояние, по которому конвейер решает, кому отдавать круги. Кнопка «Ping» на
    странице команды зовёт ровно эту ручку — ту же, что опрашивает по расписанию
    (`_run_llm_ping` в конвейере, раз в пять минут), чтобы результат руками и по
    таймеру считался одинаково.
    """
    names = (data or {}).get('names')
    if names is not None and not isinstance(names, list):
        raise HTTPException(status_code=422, detail='names должен быть списком имён моделей')

    return {'result': await team_llm_ping_all(names)}


@router.get('/dsh')
async def project_team_dsh_state(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Роли DeepSeek Harness: какие включены, где он сам и жив ли его хост.

    Отдельной ручкой, а не вместе с блоками (`/projects`): пульты живут на ноутбуке
    разработчика, и их молчание не должно задерживать обновление карточек. По той же
    причине неудача приходит полем `problem`, а не кодом ошибки, — страница показывает
    её словами и продолжает работать.

    `projects` — ответы всех пультов, разложенные по корню каталога проекта: по нему
    страница находит блок, чьи это роли. Один пульт обслуживает несколько проектов, а
    роли у них одноимённые, так что без этого ключа кнопки встали бы на чужие карточки.

    `panels` — сами пульты. Блок, чьего проекта в `projects` нет, показывает кнопку
    «подключить», и по списку пультов страница отличает «проект не подключён» от «пульта
    на этой установке нет вовсе».
    """
    return {'result': await team_dsh_state()}


@router.post('/dsh/switch')
async def project_team_dsh_switch(dsh_request: TeamDshRequest,
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Включить или выключить роль Harness — кнопка на её карточке.

    Включение заводит в Harness новую сессию, выключение отправляет её в архив.
    Карточка сессии и есть состояние роли, поэтому отдельного флага мы не пишем: то,
    что видно в браузере на хосте Harness, и есть правда.

    Роль адресуется парой «проект + имя»: пультов столько же, сколько проектов, и
    нужный сервер находится по корню каталога уже здесь, на стороне сервера.

    Права на изменение, а не на просмотр: действие поднимает и гасит агента.
    Повтор безвреден — обе ручки пульта идемпотентны, `changed` скажет, было ли что
    менять.
    """
    try:
        result = await team_dsh_switch(dsh_request.project, dsh_request.role,
                                       dsh_request.enabled)
    except TeamDshError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    return {'result': result}


@router.post('/dsh/card/add')
async def project_team_dsh_card_add(card_request: TeamDshCardRequest,
                                    user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Добавить роли ещё одну карточку Harness — кнопка «+» рядом с выключателем.

    Роль от этого берёт больше кругов сразу: карточек у неё столько, сколько оболочек
    поднимет сервис. Номер новой выбирает пульт — первый свободный, а не следующий по
    счёту, чтобы дыра от убранной карточки заполнялась, а не росла.

    Права на изменение: действие поднимает ещё одного агента.
    """
    try:
        result = await team_dsh_card_add(card_request.project, card_request.role)
    except TeamDshError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    return {'result': result}


@router.post('/dsh/card/drop')
async def project_team_dsh_card_drop(card_request: TeamDshCardRequest,
                                     user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Убрать добавочную карточку роли — крестик в её углу. Сессия уходит в архив.

    Базовую карточку так не убрать: это выключение роли, и на него есть `/dsh/switch`.
    Пульт откажет с 422, даже если крестик каким-то образом нажали на ней.

    Права на изменение: действие гасит агента.
    """
    try:
        result = await team_dsh_card_drop(card_request.project, card_request.role,
                                          card_request.card_id)
    except TeamDshError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    return {'result': result}


@router.post('/dsh/restart')
async def project_team_dsh_restart(user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Перезапустить хост Harness — кнопка наверху страницы, рядом с его адресом.

    Единственная ручка dsh без тела: хост один на все проекты и все роли, адресовать
    нечего. Просьба уходит всем ответившим пультам разом — пульт это машина, а хост у
    машины свой.

    Нужен перезапуск в четырёх случаях: хост умер или завис — и тогда чинить его больше
    некому, потому что сервис, пока тот молчит, лишь пропускает сверку карточек, и
    включённые роли не поднимутся никогда; обновился сам `dsh`; сменилась накладка
    `--patch` (окно контекста, права, набор инструментов) — её настройки достаются тому,
    кто поднял хост первым; заклинило сессии или поток событий.

    Стоит он только идущих сейчас кругов: карточки, их номера и переписка лежат на диске,
    а оболочки переподключаются к потоку событий сами. Спрашивает человека страница.

    Права на изменение: действие обрывает работу всех агентов машины разом.
    """
    try:
        result = await team_dsh_host_restart()
    except TeamDshError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    return {'result': result}


@router.post('/dsh/project')
async def project_team_dsh_project(project_request: TeamDshProjectRequest,
                                   user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Подключить проект к пульту ролей или отключить — кнопка в шапке блока.

    До этой ручки новый проект получал роли только руками: ещё один systemd-экземпляр на
    свой порт, правка `DSH_CONTROL_URL`, перезапуск. Теперь список обслуживаемых проектов
    хранит сам пульт, и меняет его нажатие кнопки.

    Какому пульту отдать проект, решает не страница: подключение пробуют у всех, кто
    ответил, и берёт его тот, у кого этот каталог существует. Адрес пульта в запросе
    означал бы, что браузер выбирает, к кому серверу сходить в сети.

    Права на изменение: подключение поднимает проекту оболочки, отключение гасит его
    роли — их карточки уходят в архив, и переписка обрывается.
    """
    try:
        if project_request.attached:
            result = await team_dsh_project_attach(project_request.project)
        else:
            result = await team_dsh_project_detach(project_request.project,
                                                   project_request.force)
    except TeamDshError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    return {'result': result}


@router.get('/timeout')
async def project_team_timeout_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Все таймауты конвейера с текущими значениями — блок на карточке команды.

    Кроме настроек отдаются сроки шагов агентских workflow (`task_setting_step`):
    прогон обрывается по ним раньше, чем по потолку роли, и карточка, где их нет,
    обещает час там, где на деле десять минут.

    `problem` — непустая строка, если лестница таймаутов нарушена (прогон агента
    обязан срываться раньше job'а, а job — раньше возврата блокировки). Считается
    по настройкам: шаги в лестницу не входят, их срок меньше потолка роли по самому
    смыслу. Это предупреждение, а не запрет: поднять все три значения разом одним
    запросом нельзя, и промежуточное состояние законно.
    """
    items = await task_setting_timeout_all()
    problem = task_setting_timeout_ladder_problem({item['key']: item['value'] for item in items})

    return {'result': {'items': items + await task_setting_step_all(), 'problem': problem}}


@router.post('/timeout')
async def project_team_timeout_set(timeout_request: TeamTimeoutRequest,
                                   user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Записать одно значение таймаута. Неизвестный ключ или выход за границы — 422.

    Ключ `step_timeout_<id>` — срок шага workflow: он лежит не в таблице настроек,
    а в определении самого шага, и пишется туда же. Развилка по ключу, а не
    отдельный endpoint: для страницы это одна и та же строка в одном блоке.
    """
    try:
        item = (await task_setting_step_set(timeout_request.key, timeout_request.value)
                if task_setting_step_key_is(timeout_request.key)
                else await task_setting_timeout_set(timeout_request.key, timeout_request.value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    items = await task_setting_timeout_all()
    problem = task_setting_timeout_ladder_problem({row['key']: row['value'] for row in items})

    return {'result': {'item': item, 'problem': problem}}


@router.post('/session/restart')
async def project_team_session_restart(session_request: TeamSessionRequest,
                                       user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Перезапустить watch-процесс оболочки — кнопка на активной карточке команды.

    Авторизацию требуем, в отличие от /ping и /activate: те дёргает сама оболочка,
    а это действие приходит из браузера и меняет состояние чужого процесса.
    """
    status = await team_session_restart(session_request.session_uuid)
    if status is None:
        raise HTTPException(status_code=404, detail='Session not found')

    return {'result': status}


@router.post('/cleanup-sessions')
async def project_team_cleanup_sessions(user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Ручной запуск очистки orphaned сессий: inactive старше 7 дней.

    Удаляет связанные записи в agent_session и ai_claude_session.
    """
    result = await cleanup_inactive_sessions()
    return {'result': result}


@router.post('/activate', dependencies=[Depends(auth_claude_secret_need)])
async def project_team_activate(member_request: TeamPingRequest):
    """Активировать члена команды (взять на работу). Секрет — как у `/ping`."""
    member = await _member_resolve(member_request)
    await team_member_activate(member['id'], member_request.session_get())
    return {'success': True, 'member_id': member['id'], 'status': 'active'}


@router.post('/deactivate', dependencies=[Depends(auth_claude_secret_need)])
async def project_team_deactivate(member_request: TeamPingRequest):
    """Деактивировать члена команды (отпустить). Секрет — как у `/ping`."""
    member = await _member_resolve(member_request)
    await team_member_deactivate(member['id'])
    return {'success': True, 'member_id': member['id'], 'status': 'inactive'}


async def _member_resolve(request: TeamPingRequest):
    """Найти члена команды по member_id или по роли; 404, если не нашли.

    Карточки заведены на проект, а роль в пинге одна на все проекты, поэтому
    проект берём из каталога запуска оболочки: `/home/.../RhapsodyAi` — это
    карточка проекта RhapsodyAi, а не первая строка с ролью `manager`.
    """
    if request.member_id is not None:
        member = await team_member_get(request.member_id)
    elif request.role:
        project_id = await team_project_id_by_work_dir(request.work_dir or '')
        member = await team_member_get_by_role(request.role, project_id)
    else:
        raise HTTPException(status_code=422, detail='member_id or role is required')

    if not member:
        raise HTTPException(status_code=404, detail='Team member not found')

    return member
