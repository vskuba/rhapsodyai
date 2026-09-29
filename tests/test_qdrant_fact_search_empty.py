"""Поиск фактов с пустым запросом отвечает пусто, а не роняет прогон.

## ⚠⚠ Что здесь стережётся

Незаполненная переменная workflow приезжает в инструмент как `None` — и это **по
контракту**: движок берёт `variables.get(имя, None)`, а кастование по аннотациям
`None` намеренно пропускает как есть (`.claude/docs/tools.md`, §8). Значит
различать «не передано» и «передано пустым» обязан сам инструмент.

`qdrant_fact_search` этого не делал, и `None` доезжал до токенизатора внутри
`qdrant_search`. Тот отвечал `TextEncodeInput must be Union[TextInputSequence,
…]` — сообщением, по которому не найти ни шага, ни переменной, — а весь прогон
обрывался «Внутренней ошибкой сервера».

## ⚠ Цена измерена, и это не теория

99 попаданий в журнале ошибок установки начиная с 26.09.2026; на проде так падал
подпоток `girl_fact_invent` каждый раз, когда родитель не передавал ему
`prompt_user`. В `tests_llm/dating_talk` от этого краснели семь маршрутных
тестов — причём сообщение уводило в сторону Qdrant, хотя Qdrant был ни при чём.

⚠ Ответ именно **пустой**, а не отказ: искать факты по пустому запросу нечем, и
«ничего не нашлось» — честный итог, с которым workflow идёт дальше. Так и было,
пока в сценариях до шага доезжала пустая строка вместо `None`.
"""

import pytest

from src.tool.qdrant import qdrant as tool

pytestmark = pytest.mark.ai


class TestAnEmptyQueryIsAnEmptyAnswer:
    """⚠⚠ Главное: до Qdrant дело не доходит вовсе."""

    @pytest.mark.parametrize('query', [None, '', '   ', '\n\t'])
    async def test_nothing_to_search_means_nothing_found(self, query, monkeypatch):
        """Пустой запрос любого вида — пустая строка в ответе."""
        monkeypatch.setattr(tool, 'qdrant_search', _must_not_be_called)

        got = await tool.qdrant_fact_search(
            query_text=query, collection_name='dating_girl',
            metadata_filter='{"document_id":"whoever"}')

        assert got == '', 'пустой запрос должен давать пустой ответ'

    async def test_a_real_query_still_reaches_qdrant(self, monkeypatch):
        """⚠ Обратная сторона: непустой запрос обязан дойти до поиска.

        Без этой проверки сторож выше зеленел бы и у инструмента, который не
        ищет никогда.
        """
        seen = {}

        async def _remember(**kwargs):
            seen.update(kwargs)
            return []

        monkeypatch.setattr(tool, 'qdrant_search', _remember)
        monkeypatch.setattr(tool, 'ai_fact_collection_metadata_get', _no_metadata)

        got = await tool.qdrant_fact_search(
            query_text='where does she work', collection_name='dating_girl',
            metadata_filter='{"document_id":"whoever"}')

        assert seen.get('query_text') == 'where does she work', \
            'запрос не доехал до поиска'
        assert got == '', 'ничего не найдено — ответ пустой'


async def _must_not_be_called(**kwargs):
    """Поиск, которого не должно случиться: пустой запрос до Qdrant не идёт."""
    raise AssertionError(f'qdrant_search позван с пустым запросом: {kwargs!r}')


async def _no_metadata(collection_name):
    """Схема коллекции здесь не важна — важен сам факт вызова поиска."""
    return {}
