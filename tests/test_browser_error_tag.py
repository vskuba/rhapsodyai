"""
Разметчик ошибок браузера — `src/uvicorn/routers/browser/browser_error_tag.py`.

Тег отвечает на вопрос «что случилось», которого не было в журнале: `source` говорит
только, кто прислал, и под одним словом `dating` лежат вперемешку таймауты, отказы входа
и упавшие сценарии. Разметка идёт по тексту сообщения, автоматически.

Проверяется здесь три вещи, и каждая ломает фильтр по-своему: формат хранения
(обрамляющие запятые, без них `,net,` находится внутри `,network,`), устойчивый порядок
тегов (иначе одинаковые ошибки лежат в журнале двумя разными строками) и двуязычность —
половина журнала на русском от ролей, половина на английском от библиотек.

Ходить в базу и поднимать клиента незачем: обе функции чистые.
"""
import pytest

pytestmark = pytest.mark.browser


class TestTagsFormat:
    """Формат строки: обрамляющие запятые и пустота, когда ничего не узнали."""

    def test_browser_error_tag_wraps_with_commas(self):
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags

        assert browser_error_tags('соединение оборвал сокет') == ',network,'

    def test_browser_error_tag_unknown_text_gives_empty(self):
        """Не опознали — тегов нет, запись видна в «все»."""
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags

        assert browser_error_tags('всё хорошо, просто заметка') == ''
        assert browser_error_tags('') == ''
        assert browser_error_tags(None) == ''

    def test_browser_error_tag_exact_match_needs_commas(self):
        """
        Ради этого запятые и нужны: `,net,` не должен находиться в `,network,`.

        Проверяем на самом формате, а не на SQL: правило `LIKE '%,net,%'` живёт в
        `browser_error_list`, а его точность целиком держится на этих запятых.
        """
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags

        stored = browser_error_tags('econnrefused')

        assert ',net,' not in stored
        assert ',network,' in stored


class TestTagsOrder:
    """Порядок тегов задан списком правил, а не тем, что нашлось раньше."""

    def test_browser_error_tag_order_is_stable(self):
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags

        # Текст называет таймаут раньше входа, а порядок обязан остаться правиловым.
        assert browser_error_tags('таймаут ожидания, нужен вход') == ',auth,timeout,'

    def test_browser_error_tag_same_error_same_string(self):
        """Иначе в журнале рядом лежат `,auth,network,` и `,network,auth,`."""
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags

        assert (browser_error_tags('нужен вход, соединение оборвал сокет')
                == browser_error_tags('соединение оборвал сокет, нужен вход'))


class TestTagsBilingual:
    """Русские сообщения ролей и английские исключения библиотек — один список."""

    @pytest.mark.parametrize('message, tag', [
        ('таймаут ожидания',              'timeout'),
        ('TimeoutError: timed out',       'timeout'),
        ('нужен вход',                    'auth'),
        ('401 Unauthorized',              'auth'),
        ('элемент не найден по xpath',    'selector'),
        ('502 Bad Gateway',               'server'),
        ('Target closed',                 'crash'),
    ])
    def test_browser_error_tag_recognises(self, message, tag):
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags

        assert tag in browser_error_tags(message)

    def test_browser_error_tag_source_counts_too(self):
        """`source` идёт в разбор наравне с текстом: иногда род сбоя виден только там."""
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags

        assert browser_error_tags('окно закрылось', 'proxy') == ',crash,'


class TestTagsList:
    """Обратный разбор: строка колонки -> список для ответа API."""

    def test_browser_error_tag_list_splits(self):
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags_list

        assert browser_error_tags_list(',auth,network,') == ['auth', 'network']

    def test_browser_error_tag_list_empty_forms(self):
        """У записи из журнала колонка бывает пустой строкой, а из драйвера — None."""
        from src.uvicorn.routers.browser.browser_error_tag import browser_error_tags_list

        assert browser_error_tags_list('') == []
        assert browser_error_tags_list(None) == []
        assert browser_error_tags_list(',,') == []

    def test_browser_error_tag_round_trip(self):
        from src.uvicorn.routers.browser.browser_error_tag import (browser_error_tags,
                                                                   browser_error_tags_list)

        assert browser_error_tags_list(browser_error_tags('нужен вход: таймаут')) == \
               ['auth', 'timeout']
