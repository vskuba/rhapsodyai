"""
Подключение проекта к пульту ролей: кнопка в шапке блока вместо команды на машине.

Зачем. Пульт (`ds-shell --service`) обслуживает проект, только если тот есть в его
списке. Раньше список набирался руками — установкой ещё одного systemd-экземпляра на
свой порт и правкой `DSH_CONTROL_URL`, — и новый проект оставался без ролей до тех пор,
пока кто-нибудь не сходил на машину. Теперь список живёт у надзирателя пульта на диске, а
меняют его две ручки (`/projects/add`, `/projects/drop`), и нажимает их страница.

Каталог проекта берётся из карточки проекта в базе (`work_dir`), а не из поля ввода:
страница показывает блоки всех проектов, и у каждого свой корень уже известен. Человек
нажимает кнопку — больше от него ничего не нужно.

Какому пульту отдать проект, решаем не спрашивая: подключение пробуем по очереди у всех,
кто ответил, и берём первого, кто согласился. Согласиться может лишь тот, у кого этот
каталог существует, — проверку делает сам пульт (`dsh_projects_check`), а каталог проекта
лежит на одной машине. Так выбор остаётся за файловой системой, а не за браузером: адрес
пульта в запросе означал бы, что сервер ходит в сеть по указке страницы.
"""
from logging_.logging_ import logger_info
from src.project.team.team_dsh import team_dsh_panels, team_dsh_path_norm
from src.project.team.team_dsh_panel import (TeamDshError, team_dsh_panel_projects,
                                             team_dsh_panel_request)


async def team_dsh_project_attach(project: str) -> dict:
    """
    Подключить проект к пульту: сервис поднимет ему оболочки и запомнит список на диске.

    Returns: `{'project', 'label', 'panel', 'attached': True, 'changed': bool}`, где
    `changed` ложно, если проект уже был подключён, — повтор нажатия ничего не ломает.

    Raises: `TeamDshError` — 422, если ни один ответивший пульт проект не принял (обычно
    такого каталога нет ни на одной машине); 502, если все пульты молчат.
    """
    project = _asked(project)

    panels = await team_dsh_panels()
    url, label = _owner(panels, project)
    if url:
        return {'project': project, 'label': label, 'panel': url,
                'attached': True, 'changed': False}

    refused, silent = [], []
    for url, _state, problem in panels:
        if problem:
            silent.append(problem)
            continue
        try:
            result = await team_dsh_panel_request(url, 'POST', '/projects/add',
                                                  {'project': project})
        except TeamDshError as error:
            # Отказ одного пульта — не конец: у соседнего этот каталог может быть.
            logger_info(f'[team] пульт {url} не принял проект {project}: {error}')
            refused.append(f'{url}: {error}')
            continue

        return {'project': str(result.get('project') or project),
                'label': str(result.get('label') or ''),
                'panel': url,
                'attached': True,
                'changed': bool(result.get('added'))}

    raise _nobody(project, refused, silent)


async def team_dsh_project_detach(project: str, force: bool = False) -> dict:
    """
    Отключить проект от пульта: погасить его роли, забыть в списке.

    Returns: `{'project', 'panel', 'attached': False, 'changed': bool, 'roles': [...]}` —
    `roles` те, что пришлось погасить при отключении.

    Отключение обрывает переписку: карточки уходят в архив, и включённая заново роль
    начнёт следующее поколение с чистой сессией. Поэтому пульт при живых ролях откажет,
    назвав их, — а `force` здесь ответ на уже заданный человеку вопрос, а не «молчи».

    Raises: `TeamDshError` — 422, если пульт отказал (домашний проект не отключают, роли
    живы без `force`); 502, если пульт не ответил.
    """
    project = _asked(project)

    panels = await team_dsh_panels()
    url, _label = _owner(panels, project)
    if not url:
        # Не подключён ни у кого — значит уже отключён; но если кто-то молчит, он мог
        # быть как раз владельцем, и молчаливое «готово» соврало бы.
        silent = [problem for _url, _state, problem in panels if problem]
        if silent:
            raise TeamDshError(f'пульт проекта {project} не отвечает: ' + '; '.join(silent))
        return {'project': project, 'panel': '', 'attached': False,
                'changed': False, 'roles': []}

    result = await team_dsh_panel_request(url, 'POST', '/projects/drop',
                                          {'project': project, 'force': bool(force)})

    return {'project': str(result.get('project') or project),
            'panel': url,
            'attached': False,
            'changed': bool(result.get('dropped')),
            'roles': [str(item) for item in (result.get('roles') or [])]}


def _asked(project: str) -> str:
    """Корень проекта в сравнимом виде. Пустой — 422: подключать нечего."""
    project = team_dsh_path_norm(project)
    if not project:
        raise TeamDshError('project обязателен: подключают проект по корню каталога', 422)

    return project


def _owner(panels: list, project: str) -> tuple:
    """Пульт, у которого этот проект уже в списке: `(адрес, имя)`. Нет такого — пустые."""
    for url, state, problem in panels:
        if problem:
            continue
        for item in team_dsh_panel_projects(state):
            if team_dsh_path_norm(item['project']) == project:
                return url, item['label']

    return '', ''


def _nobody(project: str, refused: list, silent: list) -> TeamDshError:
    """Ошибка «никто не взялся»: чей отказ, а чьё молчание — разные коды и разные слова."""
    if refused:
        return TeamDshError(f'ни один пульт не принял проект {project} — обычно это значит,'
                            f' что такого каталога нет ни на одной машине: '
                            + '; '.join(refused), 422)
    if silent:
        return TeamDshError('пульты не отвечают: ' + '; '.join(silent))

    return TeamDshError('пультов нет вовсе: задайте DSH_CONTROL_URL и поднимите '
                        'ds-shell --service на машине с проектом', 422)
