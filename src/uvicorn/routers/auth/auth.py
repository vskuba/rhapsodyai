import ipaddress
import time
import uuid

import bcrypt
from fastapi import APIRouter, Request, HTTPException
from event_.event_ import event_emit
from logging_.logging_ import logger_exception
from mysql_.mysql_ import mysql_get_db_async
from dashboard.src.panel.panel_auth import panel_auth_user_check
from dashboard.src.panel.panel_auth_throttle import (panel_auth_throttle_fail,
                                                     panel_auth_throttle_ip,
                                                     panel_auth_throttle_reset,
                                                     panel_auth_throttle_wait)
from setting_.setting_ import setting_get, setting_set
from i18n_.i18n_ import i18n_languages_parse
from src.tool.setting.setting_ import setting_value_get

router = APIRouter()

# Потолок анонимных гостей с ОДНОГО адреса за окно. Публичный `/auth/guest`
# заводит учётку без доказательств, и без потолка один клиент плодил их без
# счёта — рост таблицы `user` и нагрузка на базу.
#
# ⚠ Числа щедрые: живой игрок получает гостя один раз (сессия идемпотентна,
# cookie держит того же), новый нужен лишь тем, кто чистит cookie или ходит из
# приватного окна. 20 за час с одного адреса — заведомо выше честного и заведомо
# ниже флуда. Адрес нужен настоящий: прод поднят с `--proxy-headers`.
#
# ⚠⚠ Потолок **поадресный**, а не общий на окно: общий заперел бы вход 21-му
# живому игроку из-за двадцати других — то есть сам стал бы отказом в
# обслуживании. Ключ — адрес, и популярность игры в него не упирается.
AUTH_GUEST_MAX_PER_IP = 20
AUTH_GUEST_WINDOW_SECONDS = 3600

# ⚠⚠ Хеш-заглушка гостя: НЕ bcrypt, а короткий маркер. Войти по паролю гостём
# нельзя вовсе — `panel_auth_user_check` зовёт `bcrypt.checkpw`, та на не-bcrypt
# строке бросает `ValueError`, перехваченный в `ok = False`. Прежде тут считался
# настоящий bcrypt от случайного uuid — и это была вторая ось флуда: каждый
# анонимный запрос жёг ~100 мс CPU на хеш, который никому не нужен (гость входит
# сессией, не паролем).
#
# ⚠ `AUTH_DUMMY_HASH` сюда не годится: это bcrypt от `-`, и `checkpw('-', …)`
# вернул бы True — вход по паролю `-` открылся бы всем гостям разом.
AUTH_GUEST_PASSWORD_MARKER = 'guest-no-login'

# Счётчик гостевых входов по адресу: `{ip: [метки времени]}`. Живёт в памяти
# процесса — `/auth/guest` обслуживает только активный слот (один в любой
# момент), и один процесс видит все запросы. Переживаемость при рестарте анти-
# флуду не нужна: флуд — всплеск, его ловит живой процесс, а рестарт обнуляет
# окно и флудеру же во вред.
_auth_guest_hits: dict = {}


@router.post("/auth/guest")
async def auth_guest_login(request: Request):
    """
    Анонимная guest-сессия для публичных PWA (например /play/detective) - без
    формы логина. Идемпотентно: если в сессии уже есть валидный user_id,
    просто возвращает его, не плодя новых guest-пользователей при перезагрузке
    страницы. role_id намеренно NULL (гость не подпадает ни под одну реальную
    роль).
    dynamic=1 (аналог agent.dynamic) - гость не должен попадать ни в обычный
    экспорт ноды, ни в прод-миграцию (mysql_migration_prod_create фильтрует
    dynamic=0 для любой таблицы, где есть эта колонка).

    ## ⚠⚠ Прав у гостя нет ни одного — и игре их не нужно

    Точка публична и заводит учётку без доказательств: кто открыл страницу, тот
    и гость. Поэтому роль `guest` стоит в `AUTH_ROLE_PERMISSIONS` с **пустым**
    набором (`auth_role.py`), а не достаётся ей из набора по умолчанию, как
    было до 2026-11-01. Тогда гость читал `/api/users`, `/api/setting`,
    `/api/team` с `work_dir` и `pid`, все 36 страниц `/admin/*` — и, пока в
    наборе лежали два права на запись, мог слить ветку задачи и запустить
    конвейер за наши деньги.

    Игра от этого не пострадала, и вот почему: всем пяти точкам, которыми она
    пользуется (`/auth/guest`, `/chat/ask`, `/chat/messages`, `/chat/voice`,
    `/detective/case_agents`), прав не нужно вовсе. У `/chat/ask` и
    `/detective/case_agents` стоит `AuthChecker([])` — **пустой** список: он
    спрашивает «вошёл ли», а не «что умеет». Остальные три проверок не имеют.

    ⚠ Вход гостю нужен ровно за одним: чтобы у разговора был `user_id`. Под ним
    пишется `agent_session` — история дела, без неё игра не помнит ничего.

    ⚠⚠ Новой публичной PWA, которой понадобится что-то сверх этого, права надо
    выдавать **именованной ролью**, а не возвращать их гостю: гость — это
    «любой человек из интернета», и у него не должно быть ничего.

    ## ⚠⚠ Против флуда: потолок по адресу и хеш-маркер вместо bcrypt

    Точка публична и заводит учётку без доказательств — пентест 2026-11-02
    показал флуд: один клиент плодил гостей без счёта. Две оси закрыты.

    Рост таблицы — поадресный потолок (`_auth_guest_rate_ok`,
    `AUTH_GUEST_MAX_PER_IP` за окно). Честного игрока он не трогает: сессия
    идемпотентна, у него один гость навсегда; потолок бьёт только по тому, кто
    заводит десятки с одного адреса.

    CPU — пароль гостя теперь не bcrypt, а короткий маркер
    (`AUTH_GUEST_PASSWORD_MARKER`). Прежде на каждый анонимный запрос считался
    настоящий bcrypt от случайного uuid (~100 мс), который никому не нужен:
    гость входит сессией, не паролем. Войти под гостя по паролю невозможно —
    `checkpw` на не-bcrypt строке бросает `ValueError` и даёт отказ.
    """
    existing_user_id = request.session.get("user_id")
    if existing_user_id:
        async with mysql_get_db_async() as db:
            await db.execute("SELECT id, username FROM `user` WHERE id = %s", (existing_user_id,))
            existing_user = await db.fetchone()
        if existing_user:
            return {"user": {"id": existing_user['id'], "username": existing_user['username']}}

    # ⚠⚠ Потолок анонимов с адреса — против флуда. Идемпотентность выше закрывает
    # честного игрока (у него cookie), сюда доходит только запрос БЕЗ сессии:
    # первый вход, чистка cookie — или перебор без счёта.
    #
    # ⚠⚠ Лимитируем только ПУБЛИЧНЫЕ адреса. На проде внешний клиент идёт через
    # Caddy, и `--proxy-headers` подставляет его реальный (публичный) адрес —
    # флуд приходит отсюда. А приватные и петля (`192.168.*`, `172.16/12`,
    # `10.*`, `127.*`) значат «из своей сети»: docker-мост, соседний контейнер,
    # сама машина. Сюита ходит с адреса docker-gateway (один на все тесты) и без
    # этого исключения упёрлась бы в потолок на двадцать первом госте — то есть
    # лимит бил бы по тестам, не по флуду. Прод исключение не ослабляет: оттуда
    # публичные адреса, и их он считает.
    ip = panel_auth_throttle_ip(request)
    if ip and _auth_ip_is_public(ip) and not _auth_guest_rate_ok(ip):
        logger_exception(
            f'[auth] гостевой флуд: больше {AUTH_GUEST_MAX_PER_IP} входов за '
            f'{AUTH_GUEST_WINDOW_SECONDS}s с адреса {ip}')
        raise HTTPException(status_code=429,
                            detail='Слишком много гостевых входов, попробуйте позже')

    guest_username = f"guest_{uuid.uuid4().hex[:12]}"

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO `user` (username, email, password_hash, role_id, dynamic) VALUES (%s, %s, %s, NULL, 1)",
            (guest_username, f"{guest_username}@guest.local", AUTH_GUEST_PASSWORD_MARKER)
        )
        new_user_id = db.lastrowid
        await db.connection.commit()

    request.session["user_id"] = new_user_id
    request.session["username"] = guest_username
    request.session["role"] = "guest"

    return {"user": {"id": new_user_id, "username": guest_username}}


@router.post("/auth/login")
async def auth_login(request: Request, data: dict):
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    # ⚠⚠ Проверку пары делает общий скелет, а не свой запрос рядом. Дело не в
    # экономии строк: он сравнивает хеш **всегда**, даже когда логина в базе
    # нет. Здесь стоял мгновенный отказ на неизвестном имени — то есть логины
    # можно было перебирать по времени ответа, не пробуя ни одного пароля.
    #
    # ⚠ Правило «пользователь №1 — админ» тоже уехало: оно живёт в хранилище
    # (`auth_store.py`), и вторая копия разошлась бы с первой на первой правке.
    #
    # ⚠⚠ Заслон от подбора — **общий со скелетом** (`panel_auth_throttle.py`).
    # Дверей входа две: эта и `/api/auth/login` панели, а счёт попыток у них
    # обязан быть один. Заведи здесь свой — перебор просто шёл бы через вторую
    # дверь, и заслон на первой оказался бы украшением.
    #
    # ⚠ Спрашивается ДО сверки пары: `bcrypt` дорог, и запрещённая попытка не
    # должна до него доходить.
    ip = panel_auth_throttle_ip(request)
    wait = await panel_auth_throttle_wait(username, ip)

    if wait:
        raise HTTPException(status_code=429,
                            detail=f'Too many attempts, retry in {wait}s',
                            headers={'Retry-After': str(wait)})

    checked = await panel_auth_user_check(username, password)
    if not checked:
        await panel_auth_throttle_fail(username, ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await panel_auth_throttle_reset(username, ip)

    user_id = checked.user_id
    role = checked.role

    async with mysql_get_db_async() as db:
        await db.execute("SELECT email FROM `user` WHERE id = %s", (user_id,))
        row = await db.fetchone()

    user = {'id': user_id, 'username': checked.username,
            'email': (row or {}).get('email') or ''}

    request.session["user_id"] = user_id
    request.session["username"] = user['username']
    request.session["role"] = role

    event_emit('user.login', {'user_id': user_id, 'username': user['username'], 'role': role})

    return {
        "message": "Успешный вход! Сессия создана.",
        "user": {
            "id": user_id,
            "username": user['username'],
            "email": user['email'],
            "role": role
        }
    }


@router.post("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return {"message": "Сессия успешно завершена."}


@router.get("/auth/me")
async def auth_me(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT u.id, u.username, u.email, r.name as role FROM `user` u LEFT JOIN role r ON r.id = u.role_id WHERE u.id = %s",
            (user_id,)
        )
        user = await db.fetchone()

    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="User not found")

    return {"user": user}


@router.get("/auth/me/languages")
async def auth_me_languages(request: Request):
    """Языки, доступные текущему пользователю по его нодам, и его текущий выбор."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    languages = await _user_languages_get(user_id)
    current = str(await setting_get('language', '', user_id=user_id) or '').strip().lower()
    if current not in languages:
        current = None

    return {"result": {"languages": languages, "current": current}}


@router.put("/auth/me/password")
async def auth_update_me_password(request: Request, data: dict):
    """Смена пароля текущим пользователем: требует действующий пароль."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    password_current = str(data.get("password_current") or '')
    password_new = str(data.get("password_new") or '')

    if len(password_new) < 8:
        raise HTTPException(status_code=400, detail="Новый пароль должен быть не короче 8 символов")

    async with mysql_get_db_async() as db:
        await db.execute("SELECT password_hash FROM `user` WHERE id = %s", (user_id,))
        row = await db.fetchone()

        if not row or not bcrypt.checkpw(password_current.encode(), row['password_hash'].encode()):
            raise HTTPException(status_code=401, detail="Текущий пароль неверен")

        password_hash = bcrypt.hashpw(password_new.encode(), bcrypt.gensalt()).decode()
        await db.execute(
            "UPDATE `user` SET password_hash = %s WHERE id = %s",
            (password_hash, user_id)
        )
        await db.connection.commit()

    return {"message": "Пароль успешно изменен."}


@router.put("/auth/me")
async def auth_update_me(request: Request, data: dict):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    email = data.get("email")

    if email is None:
        raise HTTPException(status_code=400, detail="Email is required")

    # Язык общения: пользовательская настройка (setting c user_id),
    # принимается только язык из доступных пользователю нод
    language = str(data.get("language") or '').strip().lower()
    if language:
        if language not in await _user_languages_get(user_id):
            raise HTTPException(status_code=400, detail=f"Язык '{language}' недоступен для ваших нод")
        await setting_set('language', language, user_id=user_id)

    async with mysql_get_db_async() as db:
        # Обновляем email в user
        await db.execute(
            "UPDATE `user` SET email = %s WHERE id = %s",
            (email, user_id)
        )

        await db.execute(
            "SELECT u.id, u.username, u.email, r.name as role FROM `user` u LEFT JOIN role r ON r.id = u.role_id WHERE u.id = %s",
            (user_id,)
        )
        updated_user = await db.fetchone()

    return {"message": "Профиль успешно обновлен.", "user": updated_user}


def _auth_ip_is_public(ip: str) -> bool:
    """Публичный ли адрес — только такие лимитируем. См. ⚠⚠ в хендлере.

    Приватные (`10.*`, `172.16/12`, `192.168.*`), петля и прочее не-глобальное —
    «из своей сети»: docker-мост, сама машина, сюита. Нераспознанный адрес
    считаем НЕ публичным (`False`): лучше не лимитировать сомнительное, чем
    запереть своих по ошибке разбора.
    """
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _auth_guest_rate_ok(ip: str) -> bool:
    """Можно ли завести ещё одного гостя с этого адреса. `False` — упёрлись.

    Скользящее окно в памяти процесса: храним метки времени гостевых входов
    адреса, отбрасываем те, что старше окна, и считаем оставшиеся. Дошло до
    потолка — отказ; иначе метим эту попытку и пускаем.

    ⚠ Чистим протухшее при каждом вызове и у **всех** адресов, не только у
    текущего: иначе словарь рос бы ключами разовых посетителей до конца жизни
    процесса. Разовый флудер с тысяч адресов словарь всё же раздует — но против
    такого (ботнет) поадресный лимит бессилен в принципе, это другой разговор.

    ⚠ Решение и запись — в одном вызове под `/auth/guest`, который обслуживает
    один процесс (активный слот): гонки здесь нет, блокировка не нужна.
    """
    now = time.monotonic()
    floor = now - AUTH_GUEST_WINDOW_SECONDS

    for addr in list(_auth_guest_hits.keys()):
        kept = [t for t in _auth_guest_hits[addr] if t >= floor]
        if kept:
            _auth_guest_hits[addr] = kept
        else:
            del _auth_guest_hits[addr]

    if len(_auth_guest_hits.get(ip, ())) >= AUTH_GUEST_MAX_PER_IP:
        return False

    _auth_guest_hits.setdefault(ip, []).append(now)

    return True


async def _user_languages_get(user_id: int) -> list[str]:
    """Языки, доступные пользователю: объединение языков всех его нод
    (настройка 'languages', нодовая перекрывает общую). Без нод — глобальная настройка."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", (user_id,))
        node_ids = [r['node_id'] for r in await db.fetchall()]

    languages = []
    for node_id in (node_ids or [0]):
        raw = (await setting_value_get('languages', node_id, 'ru'))['value']
        for lang in i18n_languages_parse(raw):
            if lang not in languages:
                languages.append(lang)
    return languages
