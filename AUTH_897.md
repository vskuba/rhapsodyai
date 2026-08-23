# task/897 — auth-примитивы в py_modules

Вынесены проект-агностичные auth-примитивы в общий слой: `py_modules/auth_/auth_primitive.py`.
Ролевые модели проектов не трогались — кто админ и кому что можно, решает каждый проект сам.

## Что в модуле

| Имя | Что делает |
|-----|------------|
| `AUTH_TOKEN_HEADERS` | `('authorization', 'x-api-key')` — заголовки, которыми принимается токен |
| `AUTH_TOKEN_PREFIX` | `'bearer '` — префикс, необязателен |
| `AUTH_DUMMY_HASH` | bcrypt-хеш-заглушка для несуществующего логина (равное время сравнения) |
| `auth_password_hash(password)` | bcrypt-хеш пароля для записи в базу |
| `auth_token_new()` | новый токен, `secrets.token_urlsafe(32)` |
| `auth_token_of(request)` | токен из заголовков; нет ни одного — пустая строка |
| `auth_token_user(token, db, query)` | владелец токена; `db` и `query` — аргументы, без импорта конкретной таблицы |

Донор — DatingAi/src/auth/auth.py (строки 35-40: константы; 111-176: функции). `auth_token_user`
переведён на `db.execute`/`db.fetchone` как аргумент: примитив сам соединение не открывает и
не знает схемы — в какую таблицу смотреть и что выбрать, решает вызывающий.

## Как закрыты цели

1. **bcrypt-хеш и сравнение.** `auth_password_hash('secret-пароль-123')` → хеш,
   `bcrypt.checkpw(pw, hash)` = True, неверный пароль = False. `AUTH_DUMMY_HASH` — валидный
   bcrypt-хеш (сравнение не роняет исключение). Проверено smoke (см. ниже).
2. **Токен из Authorization и X-API-KEY.** `auth_token_of` вернул токен из
   `Authorization: Bearer <t>`, голый `<t>` в `Authorization`, `X-API-KEY: <t>`; пустой запрос —
   пустая строка. Проверено smoke.
3. **`auth_token_user` принимает db аргументом.** `db` и `query` приходят извне, вызывается
   `db.execute(query, (token,))` + `db.fetchone()`; пустая строка — `None`. В исходнике модуля
   нет `user_access_token`/`role`/проектных импортов. Проверено smoke + grep исходника.

## Чем проверял

- `.venv/bin/python3 -m py_compile py_modules/auth_/auth_primitive.py` — синтаксис ок.
- Smoke (scratchpad, импорт из `feature_task_897/py_modules`): 4/4 проверки — bcrypt-хеш и
  сравнение, токен из двух заголовков + пустой запрос, `auth_token_user` с FakeDB + grep
  исходника на отсутствие привязки к таблице.
- `grep -rn "from auth_" src/` — 0 совпадений: новых импортов в RhapsodyAi/src не появилось,
  старые имена не сломаны.

## Что не коммитилось и почему

Код лежит в `py_modules/auth_/auth_primitive.py` — в **master py_modules**
(`/home/vasyl/PycharmProjects/py_modules`) и в сабмодуле worktree
(`feature_task_897/py_modules`). По правилу задачи в py_modules **не коммитить** и **пин gitlink
не двигать**: `git status` в py_modules = только `?? auth_/` (untracked), `HEAD` = `fee4a23`,
пин не сдвинут. Этот MR — в RhapsodyAi, и несущий артефакт диффа — данный отчёт, а не код:
кодом он не двигает пин и не попадает в историю py_modules. Коммит py_modules делает человек,
когда решит принять работу в общий слой.
