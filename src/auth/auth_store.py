"""Где у нас лежат люди: роль — **ссылкой** `user.role_id` на таблицу `role`.

Скелет панели (`py_modules/panel_/`) умолчанием ждёт роль строкой в `user.role`.
У нас не так, и это не недочёт схемы: роли здесь заводятся на ходу, через
панель, — значит у них есть своя таблица и свой номер.

Ровно для этого у скелета и есть договор хранения: раскладка таблиц — вопрос
логики проекта, а интерфейс один.

## ⚠⚠ Имя роли наружу, номер внутрь

Договор требует отдавать `role` **именем**: правами ведает каталог
(`auth_access.py`), а он знает роли по именам. Поэтому чтение переводит номер в
имя `JOIN`-ом, а запись — имя обратно в номер.

Это и есть та половина, которую подменяемым SQL выразить нельзя: запрос чтения
написать можно, перевод имени в номер при заведении — нет.

## ⚠⚠ Пользователь №1 — всегда администратор

Правило старое и живое: первая учётка установки полноправна независимо от того,
что стоит у неё в `role_id`. Держится оно **здесь**, в одном месте, потому что
иначе разошлось бы между входом по сессии и входом по токену.
"""

from mysql_.mysql_ import mysql_get_db_async
from panel_.panel_store import PanelUserStoreColumn

from src.auth.auth_role import AuthRole

# Номер учётки, которая полноправна всегда. ⚠ Не настройка: это первая учётка
# установки, заведённая раньше любых ролей, и терять к ней доступ нельзя.
AUTH_STORE_ROOT_USER_ID = 1

# Чем выбираем человека вместе с именем роли. ⚠ `LEFT JOIN`: роли у учётки может
# не быть вовсе, и это законно — `NULL` значит «без роли», а не «нет учётки».
#
# ⚠ Сверх договора отдаются столбцы установки: `email`, `role_id` (его шлёт
# страница в выпадающем списке) и `language` из личных настроек. Договор просит
# минимум, лишнее ему не мешает — а странице без этого нечего показывать.
AUTH_STORE_SELECT = (
    'SELECT u.id, u.username, u.email, u.role_id, u.created_at,'
    '       COALESCE(r.name, %s) AS role,'
    "       s.value AS language"
    '  FROM `user` u'
    '  LEFT JOIN `role` r ON r.id = u.role_id'
    "  LEFT JOIN `setting` s ON s.user_id = u.id AND s.node_id IS NULL"
    "                       AND s.`key` = 'language'")

# ⚠⚠ Гостевые учётки в списке людей не показываются. Их заводит сам вход
# (`dynamic = 1`) при входе без пароля, и копится их столько же, сколько было
# заходов: страница управления людьми утонула бы в них за неделю.
AUTH_STORE_REAL_ONLY = 'u.dynamic = 0'

# Поля проекта, которые роутер передаёт сюда доводом `extra`. ⚠ Список закрытый:
# он и есть разрешение дописывать столбец, см. `panel_store.py`.
AUTH_STORE_EXTRA = ('email', 'node_ids')


class AuthStore(PanelUserStoreColumn):
    """Хранилище людей этой установки. Токены — как у умолчания, роли — свои."""

    async def list(self) -> list:
        async with mysql_get_db_async() as db:
            await db.execute(
                f'{AUTH_STORE_SELECT} WHERE {AUTH_STORE_REAL_ONLY} ORDER BY u.id',
                ('',))
            rows = await db.fetchall() or []

            await db.execute('SELECT user_id, node_id FROM user_node')
            nodes: dict = {}
            for one in await db.fetchall() or []:
                nodes.setdefault(int(one['user_id']), []).append(one['node_id'])

            for row in rows:
                row['role'] = _role_of(row)
                row['node_ids'] = nodes.get(int(row['id']), [])
                await db.execute(
                    'SELECT id, note, RIGHT(token, %s) AS tail, created_at'
                    '  FROM user_access_token WHERE user_id = %s ORDER BY id',
                    (self.TOKEN_TAIL, int(row['id'])))
                row['tokens'] = await db.fetchall() or []

        return rows

    async def get(self, user_id: int) -> dict | None:
        async with mysql_get_db_async() as db:
            await db.execute(f'{AUTH_STORE_SELECT} WHERE u.id = %s', ('', int(user_id)))
            row = await db.fetchone()

        if row:
            row['role'] = _role_of(row)
            async with mysql_get_db_async() as db:
                await db.execute('SELECT node_id FROM user_node WHERE user_id = %s',
                                 (int(user_id),))
                row['node_ids'] = [one['node_id'] for one in await db.fetchall() or []]

        return row

    async def by_name(self, username: str) -> dict | None:
        async with mysql_get_db_async() as db:
            await db.execute(
                f'{AUTH_STORE_SELECT.replace("u.created_at,", "u.created_at, u.password_hash,")}'
                ' WHERE u.username = %s', ('', str(username).strip()))
            row = await db.fetchone()

        if row:
            row['role'] = _role_of(row)

        return row

    async def by_token(self, token: str) -> dict | None:
        async with mysql_get_db_async() as db:
            await db.execute(
                f'{AUTH_STORE_SELECT} JOIN user_access_token t ON t.user_id = u.id'
                ' WHERE t.token = %s', ('', str(token)))
            row = await db.fetchone()

        if row:
            row['role'] = _role_of(row)

        return row

    async def create(self, username: str, password_hash: str, role: str,
                     extra: dict | None = None) -> int:
        """⚠ Имя роли переводится в номер. Нет такой роли — учётка без роли:
        отказывать здесь нельзя, проверку роли делает домен скелета раньше."""
        extra = extra or {}
        role_id = await _role_id(role)

        # ⚠ Учётка и её узлы пишутся **одним соединением**: порознь отказ по
        # внешнему ключу на узле оставлял бы человека заведённым наполовину —
        # в списке он есть, а вызывающий получил 500 и считает, что не завёл.
        async with mysql_get_db_async() as db:
            await db.execute(
                'INSERT INTO `user` (username, email, password_hash, role_id)'
                ' VALUES (%s, %s, %s, %s)',
                (username, str(extra.get('email') or ''), password_hash, role_id))
            user_id = int(db.lastrowid)

            for one in extra.get('node_ids') or []:
                await db.execute(
                    'INSERT INTO user_node (user_id, node_id) VALUES (%s, %s)',
                    (user_id, int(one)))

        return user_id

    async def update(self, user_id: int, password_hash: str = '',
                     role: str = '', extra: dict | None = None) -> None:
        extra = extra or {}
        fields, args = [], []
        if password_hash:
            fields.append('password_hash = %s')
            args.append(password_hash)
        if role:
            fields.append('role_id = %s')
            args.append(await _role_id(role))
        if extra.get('email') is not None:
            fields.append('email = %s')
            args.append(str(extra['email']))

        if fields:
            async with mysql_get_db_async() as db:
                await db.execute(
                    f'UPDATE `user` SET {", ".join(fields)} WHERE id = %s',
                    tuple(args) + (int(user_id),))

        # ⚠ Список узлов правится, только когда его прислали: отсутствие ключа
        # значит «не трогать», а пустой список — законное «снять все».
        if 'node_ids' in extra:
            await _nodes_set(user_id, extra['node_ids'])

    async def roles_used(self) -> list:
        async with mysql_get_db_async() as db:
            await db.execute(f'{AUTH_STORE_SELECT} WHERE {AUTH_STORE_REAL_ONLY}', ('',))
            rows = await db.fetchall() or []

        return [_role_of(one) for one in rows]


# ── Приватное ────────────────────────────────────────────────────────────────

def _role_of(row) -> str:
    """Имя роли строки с учётом правила про пользователя №1."""
    if not row:
        return ''

    if int(row.get('id') or 0) == AUTH_STORE_ROOT_USER_ID:
        return str(AuthRole.ROLE_ADMIN.value)

    return str(row.get('role') or '')


async def _nodes_set(user_id: int, node_ids) -> None:
    """Переписать связи человека с узлами. `None` — не трогать."""
    if node_ids is None:
        return

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM user_node WHERE user_id = %s', (int(user_id),))
        for one in node_ids or []:
            await db.execute(
                'INSERT INTO user_node (user_id, node_id) VALUES (%s, %s)',
                (int(user_id), int(one)))


async def _role_id(role: str):
    """Номер роли по имени. Нет такой — `None`, то есть учётка без роли."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id FROM `role` WHERE name = %s', (str(role or ''),))
        row = await db.fetchone()

    return int(row['id']) if row else None
