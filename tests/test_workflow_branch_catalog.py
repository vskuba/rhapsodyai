"""
Словарь меток: что видит шаг-развилка «Тема разговора».

⚠ Без словаря перечень тем пришлось бы держать текстом в промпте — то, от чего
слой и уходит. Развилка стоит ДО шагов веток, и положить его ей некому: поэтому
он приезжает служебной переменной прогона, как `user_language`.

⚠⚠ Тесты здесь **синхронные и со своим циклом событий**, а не `async def`. Пул
соединений лежит в модульной переменной и привязан к циклу, в котором создан
(`mysql_.mysql_`, докстринг `mysql_pool_get`); pytest-asyncio заводит на каждый
тест новый цикл, и второй же поход в базу встречает пул закрытым — «Event loop
is closed». Та же идиома, тем же поводом, стоит в `conftest.py` у чисток.
"""

import asyncio

import pytest

from src.ai.ai_workflow_branch import ai_workflow_branch_catalog, ai_workflow_branch_topics

pytestmark = pytest.mark.ai

# ⚠ Нода, которой нет: реестр ветками живых нод тест не трогает.
TEST_NODE_ID = 999343


def _run(make_coro):
    """Прогнать корутину в своём цикле и закрыть за собой пул."""
    from mysql_.mysql_ import mysql_pool_close

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(make_coro())
        loop.run_until_complete(mysql_pool_close())
        return result
    finally:
        loop.close()


async def _registry_drop() -> None:
    """Темы уносит каскад внешнего ключа — хватает удаления веток."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM `agent_workflow_branch` WHERE `node_id` = %s", (TEST_NODE_ID,)
        )


async def _registry_make(rows) -> None:
    """rows: [(имя ветки, включена, [(имя темы, метки, включена), …]), …]"""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        for branch_name, branch_on, topics in rows:
            await db.execute(
                """INSERT INTO `agent_workflow_branch` (`node_id`, `name`, `title`, `is_enabled`)
                   VALUES (%s, %s, %s, %s)""",
                (TEST_NODE_ID, branch_name, branch_name, branch_on)
            )
            branch_id = db.lastrowid
            for topic_name, tags, topic_on in topics:
                await db.execute(
                    """INSERT INTO `agent_workflow_branch_topic`
                              (`branch_id`, `name`, `title`, `tags`, `is_enabled`)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (branch_id, topic_name, topic_name, tags, topic_on)
                )


class TestCatalog:
    def test_unknown_node_gives_empty_catalog(self):
        async def _check():
            return await ai_workflow_branch_catalog(999_344)

        assert _run(_check) == ''

    def test_catalog_gathers_tags_of_all_branches(self):
        async def _check():
            await _registry_drop()
            await _registry_make([
                ('test_catalog_deal', 1, [('test_photo_mail', 'обмен письмами, пришли письмо', 1)]),
                ('test_catalog_dodge', 1, [('test_money', 'перевод денег, обмен письмами', 1)]),
            ])
            try:
                return await ai_workflow_branch_catalog(TEST_NODE_ID)
            finally:
                await _registry_drop()

        catalog = _run(_check)
        tags = [tag.strip() for tag in catalog.split(',')]

        assert 'обмен письмами' in tags
        assert 'перевод денег' in tags
        # ⚠ Метка «обмен письмами» стоит у обеих тем — в словаре обязана быть раз
        assert len(tags) == len(set(tags))
        # ⚠ Группировки по темам быть не должно: увидев её, модель выберет тему
        # сама, и выбор перестанет быть детерминированным
        assert 'test_photo_mail' not in catalog
        assert 'test_catalog_deal' not in catalog

    def test_disabled_branch_drops_out(self):
        async def _check():
            await _registry_drop()
            await _registry_make([
                ('test_catalog_off', 0, [('test_hidden', 'метка выключенной ветки', 1)]),
            ])
            try:
                return (await ai_workflow_branch_catalog(TEST_NODE_ID),
                        await ai_workflow_branch_topics(TEST_NODE_ID))
            finally:
                await _registry_drop()

        catalog, topics = _run(_check)
        assert 'метка выключенной ветки' not in catalog
        assert topics == []

    def test_disabled_topic_drops_out(self):
        async def _check():
            await _registry_drop()
            await _registry_make([
                ('test_catalog_mixed', 1, [
                    ('test_on', 'метка живой темы', 1),
                    ('test_off', 'метка выключенной темы', 0),
                ]),
            ])
            try:
                return await ai_workflow_branch_catalog(TEST_NODE_ID)
            finally:
                await _registry_drop()

        catalog = _run(_check)
        assert 'метка живой темы' in catalog
        assert 'метка выключенной темы' not in catalog
