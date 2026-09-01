"""
Один пульт ролей DeepSeek Harness: адреса, запрос, разбор ответа.

Пульт — это постоянно живущий `ds-shell --service` на машине разработчика. Проектов он
обслуживает столько, сколько ему подключили: список приходит полем `projects`, а
подключают и отключают их кнопкой на этой же странице (`team_dsh_project.py`). Этот файл
знает про один пульт; кто опрашивает их разом и сводит ответы — `team_dsh.py`.

Почему вообще посредник, а не поход в сам Harness. Его хост слушает петлю ноутбука и
шире не поднимается: аутентификации у него нет вовсе, а инструменты исполняют код. Из
контейнера uvicorn петля недостижима, CORS-заголовков хост не шлёт — браузеру он тоже
не отвечает. Пульт стоит на той же машине, с хостом говорит по петле, а наружу отдаёт
три ручки под общим секретом.
"""
import httpx

from config.config import config_get

# Адреса пультов — список через запятую или пробел, по одному на машину: проекты
# пульту подключают кнопкой в шапке блока, а не отдельным адресом. Умолчание —
# мост docker: контейнер ходит к ноутбуку через `host.docker.internal`, петля хоста ему
# недостижима. На установках без оболочки (прод) адрес просто не отзовётся, и страница
# покажет причину вместо кнопок.
TEAM_DSH_PANEL_URL_KEY = 'DSH_CONTROL_URL'
TEAM_DSH_PANEL_URL_DEFAULT = 'http://host.docker.internal:8791'

# Секрет — общий с team API реестра, тот же заголовок и тот же ключ. Своего пульт не
# заводит: обе стороны и так обязаны знать общий, а второй только добавил бы способов
# разойтись. Читаем в момент запроса, а не в константу: секретам не место в модуле.
TEAM_DSH_PANEL_SECRET_KEY = 'TELEGRAM_TOKEN_RHAPSODY'
TEAM_DSH_PANEL_SECRET_HEADER = 'X-Claude-Secret'

# Адрес самого Harness, когда пульт не ответил. Ссылку наверху страницы держим живой
# даже так: она ведёт на хост, который переживает и оболочку, и сервис, — и человеку
# она нужна ровно тогда, когда что-то не работает. Хост один на все проекты и все роли.
TEAM_DSH_PANEL_HARNESS_URL = 'http://127.0.0.1:8790/'

# Включение роли заводит карточку и тут же сверяет её с оболочками сервиса, поэтому
# потолок щедрый. Дозвон отдельным сроком и коротким: пульта либо нет, либо он рядом.
TEAM_DSH_PANEL_TIMEOUT = 25.0
TEAM_DSH_PANEL_CONNECT_TIMEOUT = 3.0


class TeamDshError(RuntimeError):
    """Пульт не сделал того, о чём просили. `status` — код для ответа наружу."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def team_dsh_panel_urls() -> list:
    """
    Адреса пультов из `DSH_CONTROL_URL` — по одному на машину, без повторов.

    Разделители — запятая и пробелы разом: список живёт в одной строке `.env`, и
    требовать ровно один вид разделителя значило бы ловить опечатки вместо работы.

    Читаем при каждом вызове, а не в константу модуля: значение приходит из настроек,
    а модуль импортируется один раз за жизнь процесса. Толку от этого, впрочем, немного:
    `config_get` — это `os.getenv`, а `.env` читается один раз, при импорте `config`, так
    что правка файла доходит до страницы только с перезапуском процесса.

    Через `or`, а не вторым аргументом `config_get`: пустой ключ в `.env` вернул бы
    пустую строку, до умолчания не дойдя.
    """
    raw = config_get(TEAM_DSH_PANEL_URL_KEY) or TEAM_DSH_PANEL_URL_DEFAULT

    urls = []
    for item in raw.replace(',', ' ').split():
        url = item.strip().rstrip('/')
        if url and url not in urls:
            urls.append(url)

    return urls


async def team_dsh_panel_request(url: str, method: str, path: str, payload: dict = None,
                                 timeout: float = 0) -> dict:
    """
    Один запрос к пульту. Любая неудача — `TeamDshError`, наружу httpx не течёт.

    `timeout` — потолок ожидания ответа, ноль означает общий (`TEAM_DSH_PANEL_TIMEOUT`).
    Отдельным сроком живёт лишь перезапуск хоста: он гасит процесс, ждёт освобождения
    порта и поднимает заново, и общий потолок оборвал бы его на середине — страница
    прочла бы это как «пульт не ответил», хотя хост в этот миг как раз поднимался.
    Дозвон сроком не меняется никогда: пульта либо нет, либо он рядом.

    Raises: `TeamDshError`; `status` уже пригоден для ответа наружу (422 — кривой
    запрос от нас, 502 — не дозвонились или пульту плохо).
    """
    secret = config_get(TEAM_DSH_PANEL_SECRET_KEY)
    if not secret:
        raise TeamDshError(
            f'не задан {TEAM_DSH_PANEL_SECRET_KEY}: пульт ролей без секрета не пустит')

    address = f"{url.rstrip('/')}{path}"
    timeout = httpx.Timeout(float(timeout) or TEAM_DSH_PANEL_TIMEOUT,
                            connect=TEAM_DSH_PANEL_CONNECT_TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, address, json=payload,
                                            headers={TEAM_DSH_PANEL_SECRET_HEADER: secret})
    except httpx.HTTPError as e:
        raise TeamDshError(f'пульт ролей недоступен ({address}): {e}')

    if not response.is_success:
        # 400 пульта — это «нет такой роли», то есть кривой запрос от нас, а не его
        # поломка; наружу он должен уйти как 422, иначе страница обвинит ноутбук.
        raise TeamDshError(f'пульт ролей ответил {response.status_code}: {_detail(response)}',
                           422 if response.status_code == 400 else 502)

    try:
        return response.json() or {}
    except ValueError as e:
        raise TeamDshError(f'ответ пульта ролей не разобран: {e}')


def team_dsh_panel_projects(state) -> list:
    """
    Проекты одного пульта: `[{'project', 'label', 'home', 'roles', 'attached'}]`.

    Домашний проект пульта (`home`) — тот, в чьём каталоге подняли сервис: из его `.env`
    взят секрет, и отключить его нельзя. Остальные подключены кнопкой и равноправны.

    Ответ пульта для нас входные данные — это чужой процесс чужого репозитория. Записи
    без каталога пропускаем: адресовать кнопки было бы нечем, а ронять из-за одной
    записи весь список значило бы потерять и здоровые проекты.
    """
    if not isinstance(state, dict):
        return []

    items = state.get('projects')
    if not isinstance(items, list):
        items = []

    found = []
    for item in items:
        if not isinstance(item, dict):
            continue
        project = str(item.get('project') or '').strip()
        if not project:
            continue
        found.append({'project': project,
                      'label': str(item.get('label') or ''),
                      'home': bool(item.get('home')),
                      'roles': item.get('roles'),
                      'attached': item.get('attached')})

    return found


def team_dsh_panel_roles(roles) -> dict:
    """
    Список ролей пульта в словарь `роль → состояние`. Кривые записи пропускаем.

    Пульт — чужой процесс чужого репозитория, и его ответ для нас входные данные.
    Урони весь список одна запись без имени — блок потерял бы кнопки всех ролей разом.
    """
    result = {}
    for item in roles or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('role') or '').strip()
        if not name:
            continue
        result[name] = {'title': str(item.get('title') or name),
                        'enabled': bool(item.get('enabled')),
                        'cards': [str(card) for card in (item.get('cards') or [])]}

    return result


def team_dsh_panel_sessions(attached) -> dict:
    """
    Соответствие `attached` пульта в вид страницы: `сессия реестра → карточка Harness`.

    Returns: `{session_uuid: {'card_id', 'role', 'index'}}`.

    Ключ — именно `session_uuid`, а не номер: у карточки страницы номер выдаёт реестр
    при регистрации, у карточки Harness — её место в проекте, и назначаются они
    независимо. Совпадение номеров было бы совпадением, а не правилом; общий у двух
    сторон только идентификатор сессии, который оболочка получила от реестра.

    По этому соответствию страница и узнаёт, какую карточку убирает крестик и какая из
    них базовая (номер 1) — то есть где стоять выключателю роли.
    """
    result = {}
    for card_id, item in (attached or {}).items():
        if not isinstance(item, dict):
            continue
        session = str(item.get('session_uuid') or '').strip()
        if not session:
            continue
        result[session] = {'card_id': str(card_id),
                           'role': str(item.get('role') or '').strip(),
                           'index': team_dsh_panel_index(item.get('index'))}

    return result


def team_dsh_panel_index(value) -> int:
    """Номер карточки числом. Пульт — чужой процесс, и его `index` для нас входные данные."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _detail(response) -> str:
    """Причина отказа словами: сначала `detail` пульта, потом сырое тело."""
    try:
        detail = (response.json() or {}).get('detail')
    except ValueError:
        detail = ''

    return str(detail or response.text[:300] or 'без объяснений')
