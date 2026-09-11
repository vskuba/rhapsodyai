"""
Перехват сети: шаги `net_watch` и `net_dump`.

Зачем они есть. Сценарий умеет нажать кнопку, но не умеет ответить «а куда она
постит» — а именно это и нужно, когда прогон хотят **заменить** HTTP-запросом:
страница чата, отправка сообщения, добавление в избранное сводятся к одному
запросу, если этот запрос знать. Прогон стоит десятков секунд живого браузера и
вкладки в общем пуле; запрос — миллисекунд.

Живой случай, ради которого это и появилось: DatingAi отправлял реплику в чат
LadaDate сценарием — 60 секунд на сообщение. У сайта в документации API чата нет,
страница одностраничная (`/chat#{ID}`), и найти адрес отправки было нечем:
`extract` ждёт элемент **видимым**, а `<script>` и `input[type=hidden]` невидимы
всегда. Первый же прогон с перехватом дал всю поверхность: `/chat-select`,
`/chat-users`, `/chat-sync` и `/chat-send`.

Проверяется схема (что примет и что отвергнет) и разбор записи запроса — то, что
живёт без Playwright. Сам перехват проверяется живым прогоном: он про слушателя
Chromium, и подменять его значило бы проверять заглушку.
"""

import pytest

pytestmark = pytest.mark.browser


class TestSchema:
    """Что схема шага принимает, а что отвергает — до всякого прогона."""

    def test_watch_needs_nothing(self):
        """`net_watch` без полей законен: пусто — писать всё."""
        from browser_.browser_scenario import BrowserScenarioStep

        step = BrowserScenarioStep(action='net_watch')

        assert step.action == 'net_watch'
        assert step.value == ''

    def test_watch_takes_a_filter(self):
        from browser_.browser_scenario import BrowserScenarioStep

        step = BrowserScenarioStep(action='net_watch', value='ladadate.com')

        assert step.value == 'ladadate.com'

    def test_dump_needs_a_name(self):
        """⚠ Без имени записанному некуда лечь: `extract` кладёт по имени шага, и
        безымянный `net_dump` молча выбрасывал бы весь съём."""
        from pydantic import ValidationError

        from browser_.browser_scenario import BrowserScenarioStep

        with pytest.raises(ValidationError):
            BrowserScenarioStep(action='net_dump')

    def test_dump_with_a_name(self):
        from browser_.browser_scenario import BrowserScenarioStep

        step = BrowserScenarioStep(action='net_dump', name='запросы', value='/chat')

        assert step.name == 'запросы'

    def test_fields_are_refused(self):
        """Поля бывают только у `extract_rows`: у соседних они молча ничего не
        делали бы, а автор сценария думал бы, что сбор настроен."""
        from pydantic import ValidationError

        from browser_.browser_scenario import BrowserScenarioStep

        with pytest.raises(ValidationError):
            BrowserScenarioStep(action='net_dump', name='x',
                                fields=[{'name': 'a', 'selector': 'b'}])


class TestRow:
    """Что попадает в запись о запросе."""

    def test_row_keeps_what_is_needed_to_repeat_the_request(self):
        from browser_.browser_scenario_net import _row as _net_row

        got = _net_row(_Request(
            method='POST', url='https://site.com/chat-send',
            post_data='id=181685&body=Hello',
            headers={'content-type': 'application/x-www-form-urlencoded',
                     'x-requested-with': 'XMLHttpRequest'}))

        assert got['method'] == 'POST'
        assert got['url'] == 'https://site.com/chat-send'
        assert got['body'] == 'id=181685&body=Hello'
        assert got['headers']['content-type'].startswith('application/x-www-form')

    def test_secret_headers_are_not_recorded(self):
        """⚠ **Про безопасность, а не про объём.** В заголовках живут `cookie` и
        `authorization` — сама сессия; уедь она в `extract`, чужая сессия
        оказалась бы в нашей базе и в ответе API открытым текстом.

        Для повторения запроса они и не нужны: свою сессию вызывающий подставит
        сам.
        """
        from browser_.browser_scenario_net import _row as _net_row

        got = _net_row(_Request(
            headers={'cookie': 'session=secret-value',
                     'authorization': 'Bearer secret-token',
                     'content-type': 'application/json'}))

        assert 'cookie' not in got['headers']
        assert 'authorization' not in got['headers']
        assert got['headers'] == {'content-type': 'application/json'}

    def test_missing_body_is_empty_not_an_error(self):
        """⚠ У GET тела нет вовсе, и у загрузки файла его не спросить. Пустая
        строка честнее исключения посреди слушателя: оно уронило бы не шаг, а
        весь прогон."""
        from browser_.browser_scenario_net import _row as _net_row

        got = _net_row(_Request(method='GET', post_data=None, raises=True))

        assert got['body'] == ''
        assert got['method'] == 'GET'

    def test_long_body_is_cut(self):
        """Тело бывает мегабайтом (загрузка файла), и в журнал такому не место."""
        from browser_.browser_scenario import BROWSER_SCENARIO_NET_BODY_LIMIT
        from browser_.browser_scenario_net import _row as _net_row

        got = _net_row(_Request(post_data='x' * 99999))

        assert len(got['body']) == BROWSER_SCENARIO_NET_BODY_LIMIT


class _Request:
    """Запрос Playwright настолько, насколько его читает `_net_row`.

    Своей заглушкой, а не `unittest.mock`: у настоящего запроса `post_data` и
    `headers` — **свойства**, и они умеют бросать. Именно это и проверяется, а мок
    с `Mock()` бросал бы не там, где надо.
    """

    def __init__(self, method='POST', url='https://site.com/x', post_data='',
                 headers=None, kind='xhr', raises=False):
        self.method = method
        self.url = url
        self.resource_type = kind
        self._post_data = post_data
        self._headers = headers or {}
        self._raises = raises

    @property
    def post_data(self):
        if self._raises:
            raise RuntimeError('тела нет')

        return self._post_data

    @property
    def headers(self):
        return self._headers
