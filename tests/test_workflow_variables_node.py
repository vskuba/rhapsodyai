"""Страница показывает публичные переменные ноды — все и только их.

## ⚠⚠ Зачем

Колонка «переменные» на вкладке «Шаги» показывала **ноль** переменных ноды у
`dating_favorite_mail_write`, хотя в его прогонах лежат все три.

Причина — два разных вопроса об одном:

| | как ищет | что получает |
|---|---|---|
| движок, `ai_workflow_variables_node_get` | `WHERE v.node_id = %s` | все переменные ноды |
| страница, `/workflow/{id}/variables` | `JOIN node_variable_workflow` | только явно связанные |

Связка наполняется редактором переменной и на работу движка не влияет **никак**:
6 строк на 3 переменные, только `dating_bot` и `dating_girl_create`. Человек видел
пустую колонку и не знал, что вправе сослаться на `%girl_prompt_system%`.

## ⚠ Почему не «страница = движок»

Движок отдаёт **и `proxy`** — служебные псевдонимы, подставляющие другую переменную
(`girl_title` = `%prompt_user%`). Настроить такую нельзя: её значение часть проводки
узла. В списке «что я вправе вписать и настроить» ей не место, и потому страница
показывает **подмножество**: публичные.

⚠⚠ Пока выдачу ограничивала связка, отбор по типу выходил сам собой — `proxy` в неё
просто не попал. Убрав связку, тип пришлось назвать явно, иначе `girl_title` встал бы
в список наравне с остальными. Здесь стережётся обе половины: публичные видны все,
`proxy` не виден ни один.
"""

import pytest

from src.ai.ai_workflow import ai_workflow_variables_node_get
from mysql_.mysql_ import mysql_get_db_async

pytestmark = pytest.mark.core


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой.

    ⚠ Тот же приём, что у `test_browser_site_variable.py`. Без него второй
    ходящий в базу тест падает «Future attached to a different loop»: пул остаётся
    от первого цикла, а отдавать в него соединение приходится уже из нового.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


async def _survey(limit: int = 12) -> list:
    """Что покажет страница и что лежит на ноде — по workflow с переменными ноды.

    Returns:
        list: записи `(workflow_id, есть_ли_связка, что_покажет_страница,
        публичные_ноды, все_ноды)`.

    ⚠ **Одним запросом и одной сессией.** Пул соединений привязан к циклу, в
    котором заведён, и вторая сессия внутри теста приезжала с «Future attached to
    a different loop». Заодно вопрос задаётся один раз: два запроса об одном
    разошлись бы — ровно так разошлись страница с движком.
    """
    sql = """
        SELECT w.id,
               EXISTS(SELECT 1 FROM node_variable_workflow vw
                       WHERE vw.workflow_id = w.id) AS linked,
               GROUP_CONCAT(CASE WHEN v.`type` = 'public'
                                 THEN v.name END ORDER BY v.name) AS public_vars,
               GROUP_CONCAT(v.name ORDER BY v.name) AS all_vars
          FROM agent_workflow w
          JOIN node_variable v ON v.node_id = w.node_id
         GROUP BY w.id, linked
         ORDER BY w.id
         LIMIT %s
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (limit,))
        rows = await db.fetchall()

    def names(raw) -> set:
        return set(str(raw or '').split(',')) - {''}

    return [(int(row['id']), bool(row['linked']),
             names(row['public_vars']), names(row['all_vars']))
            for row in rows]


class TestThePageShowsThePublicOnes:
    """⚠⚠ Главное: видны все публичные и ни одной `proxy`."""

    async def test_every_public_variable_is_shown(self):
        """Ни одна публичная не теряется — из-за чего всё и затевалось.

        ⚠ Проверяется на всех workflow с нодой, а не на одном: связка наполнена
        выборочно, и ошибка пряталась именно у тех, кого в ней нет.

        ⚠⚠ Здесь же стережётся **сам разобранный случай**: среди проверенных
        обязан быть workflow **без** связки, у которого список непуст. Это
        `dating_favorite_mail_write`. Верни ручка зависимость от связки — он
        снова покажет ноль, и тест это назовёт.
        """
        rows = await _survey()

        assert rows, 'не нашлось ни одного workflow с переменными ноды'

        unlinked_seen = False
        for workflow_id, linked, page, _all in rows:
            node_public = {one['name'] for one in
                           await _node_vars(workflow_id)
                           if one.get('type') == 'public'}

            assert page == node_public, (
                f'workflow {workflow_id}: страница покажет {sorted(page)}, '
                f'а публичных на ноде {sorted(node_public)}')

            if not linked and page:
                unlinked_seen = True

        assert unlinked_seen, (
            'ни один проверенный workflow не обошёлся без связки — '
            'разобранный случай перестал проверяться')

    async def test_proxy_stays_hidden(self):
        """⚠⚠ Служебные псевдонимы в список не попадают.

        Их значение — часть проводки узла (`girl_title` = `%prompt_user%`), и
        настроить такую переменную из редактора workflow нельзя. Пропадёт отбор
        по типу — `girl_title` встанет рядом с настоящими настройками.
        """
        rows = await _survey()
        checked = 0

        for workflow_id, _linked, page, all_vars in rows:
            proxy = {one['name'] for one in await _node_vars(workflow_id)
                     if one.get('type') == 'proxy'}
            if not proxy:
                continue

            assert not (page & proxy), (
                f'workflow {workflow_id}: в списке служебные {sorted(page & proxy)}')
            assert proxy <= all_vars, 'обзор потерял proxy — проверка ничего не значит'
            checked += 1

        assert checked, 'ни одной proxy-переменной не нашлось — правило не проверено'


class TestTheQueryStaysTheOne:
    """⚠ Сторож приёма: ручка не вернулась к связке и не забыла тип."""

    def test_the_handler_asks_the_node(self):
        import ast
        import inspect
        import textwrap

        from src.uvicorn.routers.workflow import workflow

        # ⚠ Разбором, а не поиском по тексту: и связка, и тип названы рядом в
        # пояснениях, зачем так сделано, — поиск подстрокой ловил бы их.
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(workflow.workflow_variables)))
        sql = ' '.join(node.value for node in ast.walk(tree)
                       if isinstance(node, ast.Constant)
                       and isinstance(node.value, str))

        assert 'node_variable_workflow' not in sql, \
            'выдача переменных ноды снова зависит от связки'
        assert 'w.node_id = v.node_id' in sql, \
            'переменные ноды берутся не по ноде workflow'
        assert "= 'public'" in sql, \
            'пропал отбор по типу — служебные proxy попадут в список'


async def _node_vars(workflow_id: int) -> list:
    """Переменные ноды глазами движка — тем самым вызовом, что и в бою."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT node_id FROM agent_workflow WHERE id = %s', (workflow_id,))
        row = await db.fetchone()

    node_id = int((row or {}).get('node_id') or 0)

    return await ai_workflow_variables_node_get(node_id) if node_id else []
