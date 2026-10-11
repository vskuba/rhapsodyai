"""Факты: записанное **находится** поиском, и находится своё.

⚠⚠ Фича движка и двух инструментов разом: `fact_collection_add` пишет,
`qdrant_fact_sync` переносит в векторное хранилище, `qdrant_fact_search`
находит. Звенья ломаются порознь и молча — факт остаётся в базе с
`qdrant_synced = 0`, поиск честно отдаёт пусто, и выглядит это как «модель не
вспомнила».

Раньше это проверялось на `dating_talk` с его тремя коллекциями и подпотоками
выдумывания — тесты падали от правки промпта разбора, хотя запись и поиск
работали.

⚠ Коллекция своя (`testing_facts`), ключ документа — на прогон: сюита не
трогает боевые факты и не находит собственные прошлые.
"""
import pytest

from tests_llm.testing_facts.conftest import (AGENT, STEP_ADD, STEP_FIND,
                                              STEP_SYNC, fact_key)

pytestmark = pytest.mark.llm

FACT = 'She watches storms from the lighthouse'


class TestTheFactIsStoredAndFound:
    """Полный круг: записали — синхронизировали — нашли."""

    async def test_all_three_steps_run(self, ask):
        got = await _run(ask, 'round', FACT, 'weather', 'storms')

        for step in (STEP_ADD, STEP_SYNC, STEP_FIND):
            assert got.ran(step), f'шаг «{step}» не отработал.{got}'

    async def test_what_was_written_comes_back(self, ask):
        """⚠⚠ Главное: текст факта вправду доезжает из хранилища.

        «Шаг поиска отработал» ничего не значит — он отрабатывает и с пустым
        ответом. Проверяется содержимое.
        """
        got = await _run(ask, 'back', FACT, 'weather', 'storms')

        said = got.output_of(STEP_FIND)

        assert FACT in said, f'записанный факт не нашёлся: {said!r}.{got}'


class TestTheSearchIsNarrow:
    """Поиск отдаёт своё, а не всё подряд."""

    async def test_a_foreign_key_finds_nothing(self, ask):
        """⚠⚠ Фильтр по документу держит: чужой ключ не достаёт наш факт.

        Пропади фильтр — агент «вспомнил» бы про одного человека то, что
        рассказал другой. Ровно ради этого документы и разделены.
        """
        await _run(ask, 'mine', FACT, 'weather', 'storms')

        got = await _run(ask, 'other', 'Unrelated note', 'other', 'storms')

        said = got.output_of(STEP_FIND)

        assert FACT not in said, \
            f'чужой документ отдал наш факт: {said!r}.{got}'

    async def test_a_far_query_still_returns_the_only_fact(self, ask):
        """⚠⚠ Порога близости у поиска НЕТ — и это надо знать, а не чинить тестом.

        `qdrant_fact_search` отдаёт `limit` ближайших, каким бы далёким ни был
        запрос: в документе один факт, и на «accounting invoices tax» вернётся
        он же. Ожидать пустоту тут неверно — тест проверял бы порог, которого в
        инструменте нет.

        Отбор идёт **фильтром по документу** (проверка выше), а не
        расстоянием. Появится порог — этот тест и скажет о смене контракта.
        """
        got = await _run(ask, 'far', FACT, 'weather', 'accounting invoices tax')

        said = got.output_of(STEP_FIND)

        assert FACT in said, \
            f'поиск без порога обязан вернуть единственный факт: {said!r}.{got}'


async def _run(ask, name: str, document: str, tags: str, query: str):
    """Один заход: записать факт под своим ключом и поискать его."""
    return await ask(AGENT, f'probe {name}', variables={
        'fact_key': fact_key(name), 'fact_doc': document,
        'fact_tags': tags, 'fact_query': query})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
