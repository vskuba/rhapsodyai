# Auth — аутентификация и права доступа

⚠⚠ **Проверку пары логин-пароль делает общий скелет**
(`panel_auth_user_check`, страница `.claude/docs-common/panel.md`, §10), а не
запрос в роутере. Он сравнивает хеш **всегда**, даже когда логина в базе нет:
здесь стоял мгновенный отказ на неизвестном имени, и логины можно было
перебирать по времени ответа, не пробуя ни одного пароля.

⚠ Правило «пользователь №1 — админ» живёт в хранилище (`auth_store.py`), а не
в роутере: вторая копия разошлась бы с первой на первой же правке.

> Session-based authentication with role-based access control (RBAC) and optional
> field-level policies. Сессия хранится в cookie, права проверяются зависимостью
> `AuthChecker`, публичные пути перечислены в middleware `main_uvicorn.py`.

## File Structure

```
src/
├── auth/
│   ├── auth.py              # AuthChecker dependency, auth_get_current_user()
│   ├── auth_session.py      # AuthSession Pydantic model
│   ├── auth_role.py         # AuthRole enum + AUTH_ROLE_PERMISSIONS mapping
│   ├── auth_permission.py   # AuthPermission enum
│   └── auth_field_policy.py # Field-level read/write policy per role
└── uvicorn/routers/auth/
    └── auth.py              # /auth/login, /auth/logout, /auth/me endpoints
data/uvicorn/template/login.html  # Standalone login page
```

## Session Middleware (`main_uvicorn.py`)

```python
Middleware(
    SessionMiddleware,
    secret_key=config_get('SESSION_SECRET_KEY'),
    session_cookie="uvicorn_session",
    max_age=SESSION_MAX_AGE,   # два часа простоя
    same_site="lax",
    https_only=False
),
Middleware(BaseHTTPMiddleware, dispatch=session_slide_middleware),  # двигает окно
Middleware(BaseHTTPMiddleware, dispatch=auth_middleware),
```

⚠ Порядок в списке = порядок вложения: первый снаружи. Продление стоит **после**
`SessionMiddleware`, то есть внутри него, — иначе правило бы сессию, которой ещё нет.

`auth_middleware` protects `/admin/*` routes, redirects unauthenticated users to `/login`.

### Срок сессии — четыре часа **простоя**, окно скользящее

Было час и от входа; подняли и сделали скользящим 2026-09-29, до четырёх часов —
2026-09-30. Час кончался посреди
работы, и выглядело это не как «сессия истекла», а как поломка сервера: страница админки
остаётся открытой (её маршрут проверяет вход только при переходе), а все запросы к API
отвечают 401 — панели молча пустеют. Живьём это дважды приняли за отказ базы.

Окно двигает `session_slide_middleware` (`main_uvicorn.py`), логика —
`src/auth/auth_session_slide.py`. Работающего человека сессия не выбрасывает вовсе:
отсчёт идёт от последнего запроса.

⚠ **Как это устроено.** Starlette переустанавливает куку, только если сессия
**изменилась** (`Session.modified`). Значит достаточно что-нибудь в неё записать — и на
ответе уедет свежий `Set-Cookie` с новым `Max-Age` и новой подписью, от которой и
считается срок.

⚠ **Версия Starlette тут важна.** В 1.6.0 (она в контейнере) условие
`if session.modified and session`; в старых (0.52.1) — просто `if scope["session"]`, то
есть кука уходит на каждом ответе и так. Приём с записью верен для обеих — но проверять
поведение надо **в контейнере**: локальный `.venv` держит другую версию и показывает
другое.

⚠ **Метка огрублена до `AUTH_SESSION_SLIDE_STEP` (минута), и это не мелочь.**
Присваивание помечает сессию изменённой всегда, даже тем же значением, — а `Set-Cookie`
на каждый ответ это лишние сотни байт с каждой картинкой и каждым файлом статики. Окно
при этом «дребезжит» на величину шага, что при сроке в два часа роли не играет.

⚠ **Анониму кука не заводится.** Признак входа — `user_id` в сессии, а не факт непустого
словаря: иначе сессию получал бы каждый, кто просто открыл страницу входа.

⚠ **Секрет сессии переживает выкладку**, пока `SESSION_SECRET_KEY` лежит в `.env` прода:
куки после деплоя остаются годными. Пропадёт переменная — все сессии оборвутся разом, и
это будет выглядеть тем же «сервер сломался».

Проверить срок в живой установке: `Max-Age` в ответе на вход.

```bash
curl -s -i -X POST http://localhost:8011/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"…","password":"…"}' | grep -i '^set-cookie'
```

## AuthSession Model

```python
class AuthSession(BaseModel):
    user_id: int
    username: str
    role: str   # "admin" | "user"
```

## auth_get_current_user()

Два способа авторизации: сессия админки и токен доступа (`user_access_token`).

```python
async def auth_get_current_user(request: Request) -> AuthSession:
    # 1. Сессия админки
    if request.session.get("user_id"):
        return AuthSession(...)
    # 2. Токен доступа — общий разбор заголовков
    token = auth_token_of(request)
    if token:
        return await auth_token_user(token)
    raise HTTPException(status_code=401, detail="Not authenticated")
```

Токен принимается тремя видами заголовка, разбор — в `auth_token_of()`:

| Заголовок | Пример |
|-----------|--------|
| `Authorization: Bearer <token>` | общепринятый, им пользуются готовые клиенты |
| `Authorization: <token>` | без слова `Bearer` — отказывать из-за него придирка |
| `X-API-KEY: <token>` | остаётся: на нём написаны существующие интеграции |

**Проверка одна на все точки.** Точки зовут `AuthChecker`, он — `auth_get_current_user`,
поэтому новый способ авторизации появляется сразу везде, а не там, куда его не
забыли добавить.

**Ловушка — `auth_middleware` в `main_uvicorn.py`.** Он отсекает неавторизованные
запросы **до** роутера, и его условие обязано знать те же заголовки. Пока он знал
только `X-API-KEY`, запрос с `Authorization` получал 401, не доходя до проверки
прав, — и выглядело это как «токен неверный». Поэтому middleware зовёт тот же
`auth_token_of()`, а не повторяет разбор своей копией.

### ⚠⚠ Застава проверяет ключ, а не наличие заголовка

До 2026-11-01 застава пускала дальше по одному факту, что заголовок **есть**, —
проверку оставляли роутеру. Для 303 точек с `AuthChecker` это работало, но точка
**без** него исполнялась для кого угодно: `Authorization: Bearer deadbeef`
отдавал 200 там, где без заголовка был 401. Проба аудита — `POST /chat/messages`:
с выдуманным токеном он отдавал чужую переписку по `session_uuid`.

Цена ошибки была не в одной точке, а в правиле: забыть `AuthChecker` на новой
ручке значило открыть её наружу, и ни тест, ни чтение кода об этом не говорили.

Теперь застава решает сама:

| Что пришло | Что делает застава |
|------------|--------------------|
| токен (`Authorization` / `X-API-KEY`) | `auth_token_valid()` — есть ли такой в базе; нет → 401 |
| `X-Claude-Secret` | `auth_claude_secret_ok()` — сверка с `TELEGRAM_TOKEN_RHAPSODY`; не сошлось → 401 |
| ничего | 401 (API) либо редирект на `/login` (страницы) |

⚠ Застава прав **не выдаёт**: кто пришёл и что ему можно, по-прежнему решает
роутер своим `AuthChecker`. Здесь отвечают на один вопрос — «ключ настоящий ли».

⚠ Сравнение секрета живёт в одном месте (`auth_claude_secret_ok`): его зовут и
застава, и `_require_claude_secret` точек Mini App, и зависимость
`auth_claude_secret_need` на heartbeat команды. Две копии условия разошлись бы.

Сторожит `tests/test_user_access_token.py::TestFakeTokenDoesNotPassGate` —
намеренно на точке **без** `AuthChecker`: на точке с ним тест зеленел бы и при
дырявой заставе.

## AuthChecker Dependency

```python
class AuthChecker:
    def __init__(self, required_permissions: list[AuthPermission]):
        self.required_permissions = required_permissions

    async def __call__(self, request: Request) -> AuthSession:
        current_user = await auth_get_current_user(request)
        user_permissions = auth_role_permissions(current_user.role)   # admin -> все права
        for perm in self.required_permissions:
            if perm not in user_permissions:
                raise HTTPException(status_code=403, detail="Недостаточно прав")
        return current_user
```

**Usage:**
```python
@router.get("/protected")
async def endpoint(user: AuthSession = Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    ...
```

## Login/Logout/Me Endpoints

```python
@router.post("/auth/login")
async def login(request: Request, data: dict):
    # Queries user by username, verifies bcrypt hash, sets session
    if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["user_id"] = user['id']
    request.session["username"] = user['username']
    request.session["role"] = user['role']

@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()

@router.get("/auth/me")
async def me(request: Request):
    # Returns current user from DB, validates session is still valid
```

## Заслон от подбора пароля

Введён 24.10.2026. Повод — замер, а не опасение: двенадцать неверных паролей
подряд давали двенадцать `401`, ни одного `429`, время ответа не росло.
Единственным тормозом был `bcrypt` (~250 мс), а он обходится параллелизмом:
двадцать потоков — ~80 попыток в секунду, семь миллионов в сутки. Против
словаря из десяти тысяч паролей это две минуты.

Теперь каждая неудача удваивает паузу до следующей попытки:

| неудач подряд | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11+ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ждать | 1 с | 2 с | 4 с | 8 с | 16 с | 32 с | 1 м | 2 м | 4 м | 8 м | **15 м** |

Замерено на живой установке: 2, 2, 5, 8, 16, 33 с (удвоение плюс округление
`Retry-After` вверх). Потолок даёт **~107 попыток в сутки** на логин.

Код — **в скелете** (`dashboard/src/panel/panel_auth_throttle.py`), потому что
панель общая на три проекта. Схема: эталон `dashboard/src/panel/schema/
auth_attempt.sql`, у нас накатана миграцией `20261024165211_auth_attempt.sql`.

### Две двери, один счёт

Вход в этот проект ведут **двое**: `/api/auth/login` скелета и свой
`/auth/login` (`src/uvicorn/routers/auth/auth.py`). Обе зовут один заслон.

⚠⚠ Заведи вторая дверь свой счёт — перебор просто шёл бы через неё, и заслон
на первой оказался бы украшением.

⚠ Заслон спрашивается **до** `panel_auth_user_check`: `bcrypt` — самая дорогая
часть входа, и запрещённая попытка не должна до него доходить.

### Два счёта: по логину и по адресу

| | по логину | по адресу |
|---|---|---|
| ловит | подбор пароля к аккаунту | перебор логинов с одной точки |
| свободных неудач | **0** | 5 |
| потолок | 15 мин | 5 мин |

Держит строгий из двух. Смена адреса запрет по логину не снимает — это
стережёт отдельный тест.

⚠ Запас по адресу нужен из-за NAT: за одним IP бывает офис.

⚠⚠ Удачный вход сбрасывает **оба** счёта. Владелец рабочей учётки может тем
самым обнулить себе счёт адреса — принято сознательно: счёт чужого логина так
не сбросить, а он и есть главный заслон.

### ⚠⚠⚠ `--proxy-headers` — без него заслон запрёт всех

За обратным прокси в `request.client.host` приходит адрес **Caddy**, один и тот
же у всех. Читая его, счёт по адресу стал бы общим на установку, и первый же
перебор закрыл бы вход всем сразу.

Поэтому запуск в `docker/uvicorn/dockerfile`:

```
--proxy-headers --forwarded-allow-ips 127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

⚠⚠ Список частных сетей, а не своя подсеть: `os-net` объявлена просто
`driver: bridge`, и подсеть ей выдаёт docker — **разную на установках**
(замерено: локально `192.168.160.0/20`, на проде `172.18.0.0/16`). Жёсткая
строка работала бы у разработчика и молча ломала бы прод, причём в сторону
«запереть всех».

⚠ `*` ставить нельзя: порт 8011 проброшен на хост, `iptables` его не
закрывает, а `X-Forwarded-For` подделывается строкой в запросе — то есть
заслон обходился бы, а под запрет ставился бы кто угодно. Частные диапазоны
публичным адресам не верят.

⚠ Остаточный риск: кто-то **внутри** частной сети, достучавшись до 8011 мимо
Caddy, адрес подделает. Закрыть 8011 снаружи файрволом — отдельная работа,
здесь не сделана.

### Выключатели и видимость

| Настройка | Умолчание | Зачем |
|---|---|---|
| `auth_throttle_enabled` | `1` | запер себя — лечение не должно требовать выкладки |
| `auth_throttle_ip_enabled` | `1` | `0` там, где запуск без `--proxy-headers` |

⚠ Умолчание — **включено**, и даже при отсутствии строк в `setting`: заслон,
который молчит, пока его не включили, защищает ровно до первой установки, где
об этом забыли. Ответ о настройке живёт в памяти процесса полминуты — иначе
каждая попытка добавляла бы запрос к базе, то есть заслон усиливал бы
нагрузку, от которой защищает.

⚠⚠ Срабатывание пишется `logger_exception` — **один раз на окно**, а не на
каждую попытку. До этого неудачные входы шли `logger_info` и не попадали в
«Журнал → Ошибки» вовсе: миллион попыток не оставлял следа нигде, а в Telegram
уходил только **удачный** вход.

### Что заслон НЕ закрывает

- `/auth/guest` — анонимная сессия для `/play/*`, пароля там нет;
- подбор токенов доступа — он и не нужен: `secrets.token_urlsafe(32)`, 256 бит;
- распределённую атаку с тысячи адресов по тысяче разных логинов: счёт логина
  при этом растёт у каждого, но медленно. От этого спасает длина пароля, а не
  заслон.

## Roles & Permissions

Роли динамические (таблица `role`); в коде захардкожен только `admin` (`AuthRole.ROLE_ADMIN`).

`auth_role.py`:
- `AUTH_PERMISSIONS_DEFAULT` — **пустой** набор: что достаётся роли, которой нет в списке
- `AUTH_PERMISSIONS_VIEW` — view-набор, выдаётся роли **поимённо**
- `AUTH_ROLE_PERMISSIONS` — права по имени роли
- `auth_role_permissions(role)` → набор прав роли (`admin` → все права)
- `auth_role_is_full(role)` → роль с полным набором прав

### ⚠⚠⚠ Незнакомая роль не получает ничего

`AUTH_PERMISSIONS_DEFAULT` достаётся роли, которой **нет** в
`AUTH_ROLE_PERMISSIONS`, — то есть любой строке, пришедшей в куке. До
2026-11-01 там лежал view-набор, и обошлось это дважды.

Сперва в набор попали два права на **запись** (`PLANNING_UPDATE`,
`WORKFLOW_VARIABLE_UPDATE`), и анонимный гость получил **71 пишущую точку**:
`POST /task/{id}/worktree/merge`, `POST /task/{id}/pipeline/start` (конвейер за
наши деньги), `DELETE /design/block/{id}`, `POST /api/team/dsh/restart`. Проба
аудита: `POST /api/team/parallel` отвечал гостю 422 «не хватает `project_id`» —
право прошло, споткнулось только тело.

Потом выяснилось, что и чтения ему хватало: `/api/users` с почтой всех людей,
`/api/setting`, `/api/team` с `work_dir` и `pid`, перечень бэкапов и 36 страниц
`/admin/*`. Открытых гостю GET-точек было **120 из 192**; стало **6** — свои
данные (`/auth/me`, `/user`) и публичные страницы.

⚠ Цена названа честно: **роль, заведённая в панели и не упомянутая в коде, не
может ничего**. Это не недосмотр, а смысл правки — права выдаются решением, а
не достаются молча. Новой роли нужен view-набор: строка
`'имя': set(AUTH_PERMISSIONS_VIEW)` в `AUTH_ROLE_PERMISSIONS`.

Сторожат пара классов в `tests/test_permissions.py`: `TestPermissions`
(неназванной роли нельзя ничего) и `TestNamedRoleCanRead` (названной — можно).
Поодиночке каждый зеленел бы на сломанном коде, вместе — нет.

### Гость: одно право, и оно нужно игре

`POST /auth/guest` публичен и заводит учётку без доказательств — это нужно
публичным PWA (`/play/detective`). Роль `guest` стоит в `AUTH_ROLE_PERMISSIONS`
с единственным правом `chat:ask`.

Игре хватает ровно его: `apps/detective/js/app.js` ходит по пяти адресам, и
четыре из них — `/chat/ask`, `/chat/messages`, `/chat/voice`,
`/detective/case_agents` — закрыты именно этим правом. Пятый — сам
`/auth/guest`.

⚠⚠ Раньше у этих четырёх стоял `AuthChecker([])` — «вошёл, и ладно». Тем же
пустым списком были закрыты ещё семь точек, и гость получал их заодно:
`/translate` (поход в модель за наши деньги), `/companion` и `/companion/list`
(справочник собеседников, чтение и запись), `/agent/list`, три
`/chat/message/*` (запись в память агента). Теперь у каждой своё право:

| Точка | Право |
|-------|-------|
| `/chat/ask`, `/chat/messages`, `/chat/voice`, `/detective/case_agents` | `chat:ask` |
| три `/chat/message/*`, `POST /companion` | `session_companion:write` |
| `GET /companion/list` | `session:view` |
| `POST /translate` | `translate:create` |
| `POST /agent/list` | `agent:view` |

⚠ Новой публичной PWA права выдавать **именованной ролью**, а не гостю: гость —
это «любой человек из интернета».

### `panel:view` — дверь в саму панель

Страницы `/admin/*` и корень `/` закрыты правом `panel:view`
(`dashboard_require_auth`). Что человек увидит внутри, решают права по темам на
точках API; здесь только дверь.

⚠⚠ Право отдельное, потому что «вошёл» и «работает здесь» — разные вещи.
Первая версия правки спрашивала «есть ли хоть какое-нибудь право» — и гость
прошёл обратно: `chat:ask` у него есть, и он ему правда нужен.

⚠ Служебным учёткам соседей (`blog_service`, `dating_service`) право не выдано:
они ходят по токену из кода и браузером в панель не заходят.

**`qa`** (`vova.tkachenko`, логин/пароль в `.env.local`: `QA_USERNAME` / `QA_PASSWORD`) — учётка автотестов
и ручных проверок, права полные: сюита создаёт и удаляет пользователей, роли, агентов, workflow.
Отделена от `admin`, чтобы её сессии и действия были видны в логах отдельно от владельца.

**`blog_service`** — учётка **соседнего проекта BlogAi** («Блокнот»). Черновики, их теги и
страница живут там; сюда он ходит ровно за одним — расшифровать голос через `/api/stt/*`.
Право единственное: `stt:create`. Ходит по токену (`user_access_token`), не по логину:
звонит автоматика, и сессия ей не нужна. Подробности точек — `stt.md`.

**`dating_service`** (логин/пароль в `.env.local`: `DATING_USERNAME` / `DATING_PASSWORD`) — учётка
**соседнего проекта DatingAi**. Анкеты и переписка живут там, а сюда он ходит за браузером, за
агентом анкеты и за счётчиком токенов. Права узкие намеренно — `browser:view`, `browser:create`,
`agent:view`, `agent:create`, `llm:view`: этой учёткой правит автоматика, и лишнее право здесь не
удобство, а возможность снести чужое по ошибке в коде.

⚠️ **`llm:view` — пятое право, и оно только читает.** Добавлено под вкладку «Статистика» у соседа:
сколько запросов к LLM ушло и сколько токенов потрачено, считает только эта установка
(`llm_request`), и второй копии быть не должно — токены знает тот, кто зовёт модель. Оговорка
«лишнее право — возможность снести чужое» относится к правам, которые **пишут**: `llm:view`
открывает `GET /llm/list`, `/llm/status` и `/llm/usage/stats`, а очистка журнала живёт за отдельным
`llm:delete`, которого здесь нет.

Объём набора сторожит тест (`test_browser_site_variable.py`, `TestPermissions`): прав ровно пять.
Без него набор рос бы незаметно — каждое следующее «ну ещё одно» выглядит безобидным, а вместе они
дают учётке автоматики то, чего никто не решал.

⚠️ Знакомства и браузер прикрывались `planning:*` — по образцу соседнего модуля. Пока все учётки были
полноправными, разница не была видна; вылезла она на служебной: чтобы дать ей работать с анкетами,
приходилось выдавать `planning:create`, а он открывает ещё и закладки сайтов, сценарии браузера и его
сессии (проверено — учётка знакомств заводила сессию Chromium). Теперь у каждого модуля свои права:

| Модуль | Права | Где |
|--------|-------|-----|
| контейнер-браузер | `browser:view`, `browser:create` | `routers/browser/` — закладки, сценарии, сессии, запись, журнал ошибок |
| планирование и design | `planning:*` | `routers/project/`, в том числе `design/design_browser.py` |

`design_browser.py` водит браузер, но это ручки модуля design — они и остались на `planning:*`.
Право определяется тем, **чем управляет ручка**, а не тем, что она использует под капотом.

`browser:view` входит в `AUTH_PERMISSIONS_DEFAULT` — там же, где `planning:view`,
чтобы у существующих ролей (`manager_dating` и прочих) доступ не изменился.

Знакомства уехали в отдельный проект, и `dating:*` вместе с ними: ручек `/api/dating/*` здесь
больше нет. Теперь DatingAi водит браузер **по HTTP**, поэтому его учётке нужны именно
`browser:view` и `browser:create` — то, чего внутри одного процесса не требовалось.

⚠️ Не проверять роль по имени (`if user.role == 'admin'`) — такие проверки отсекают `qa` и любую
другую полноправную роль. Использовать `auth_role_is_full(role)`; так сделано в `agent.py`,
`session.py`, `fact.py`, `workflow_variable.py`, `auth_field_policy.py`, `event_handlers.py`
(последний ещё и глушит Telegram-уведомление о логине — иначе каждый тест слал бы пуш владельцу).

Adding a permission:
1. Add to `AuthPermission` enum in `auth_permission.py`
2. Add to the role's set in `AUTH_ROLE_PERMISSIONS` in `auth_role.py`
3. Use `Depends(AuthChecker([AuthPermission.NEW_PERM]))` in the router

## Field-Level Access Policy (`src/auth/auth_field_policy.py`)

Sits on top of endpoint-level RBAC. Controls which DB columns a role can read/write.

```python
ALL_FIELDS = '*'

AUTH_FIELD_POLICY = {
    'agent_workflow_variable': {
        'fields': {'name', 'description', 'default', 'workflow_id', 'node_id', 'pattern'},
        'write': {
            '*': {'default'},  # any non-admin role writes only `default`
        },
        'read': {
            '*': ALL_FIELDS,
        },
    },
}
```

Key: `'*'` is the fallback for any restricted role; a specific role name overrides it. Полноправные роли (`auth_role_is_full` — `admin`, `qa`) в политике не описываются — всегда `ALL_FIELDS`.

**Functions:**
- `auth_field_policy_fields_allowed(entity, action, role)` → `ALL_FIELDS` or `set` of allowed fields
- `auth_field_policy_fields_filter_for_update(entity, action, role, data)` → `(fields, data)` filtered to allowed columns

**Usage in PUT router:**
```python
fields, data = auth_field_policy_fields_filter_for_update('agent_workflow_variable', 'write', user.role, data)
if fields:
    set_clause = ', '.join(f"`{f}`=%s" for f in fields)
    await db.execute(f"UPDATE agent_workflow_variable SET {set_clause} WHERE id=%s", ...)
```

**Usage in GET/list router:**
```python
allowed = auth_field_policy_fields_allowed('agent_workflow_variable', 'read', user.role)
if allowed != ALL_FIELDS:
    results = [{k: v for k, v in row.items() if k in allowed} for row in results]
```

Adding field policy for a new entity:
1. Add entity key to `AUTH_FIELD_POLICY` with `fields`, `write`, `read`
2. Replace static UPDATE with `auth_field_policy_fields_filter_for_update()` + dynamic SET clause
3. Filter list/get response with `auth_field_policy_fields_allowed(entity, 'read', user.role)`

**Note:** `workflow_variable` uses separate permissions `WORKFLOW_VARIABLE_VIEW` / `WORKFLOW_VARIABLE_UPDATE` so regular users can save `default` without needing `WORKFLOW_UPDATE`.
