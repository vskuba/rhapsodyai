"""
Колонка «Открытые страницы» обновляется сама, не дожидаясь перезагрузки.

Зачем. Пул смотрят именно тогда, когда страницы открываются и гаснут прямо
сейчас — своим сценарием, тестом, соседом по установке. Раньше колонка жила на
общем круге страницы в десять секунд: открыл страницу — и гадаешь, она ещё не
появилась или не открылась вовсе. Теперь у пула свой круг, три секунды.

Проверяем **чужими руками**: страницу заводим и гасим мимо админки, прямо в
контейнере. Нажми мы кнопку на самой странице — та перерисовала бы колонку
сразу, своим обработчиком, и круг остался бы непроверенным.

Окно ожидания намеренно уже десяти секунд: уложились — значит обновил свой круг
пула, а не общий круг страницы.

Требуется живой сервер на BASE_URL и контейнер-браузер (маркеры `integration`,
`slow`).
"""

import os
import time
from contextlib import suppress

import httpx
import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

from tests.test_team_task_pages import _login

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
BROWSER_URL = os.getenv('BROWSER_TEST_URL', 'http://127.0.0.1:8014')

pytestmark = [pytest.mark.browser, pytest.mark.integration, pytest.mark.slow]

# Имя страницы, которую заводит сам тест. Своё, чтобы уборка не задела чужую.
PROBE_NAME = '__pytest пул автообновление'

# Круг колонки — 3 с, общий круг страницы — 10 с. Ждём между ними: уложились —
# обновил пул, не уложились — тест честно красный, даже если через полминуты
# карточка и появится.
PROBE_WAIT_SEC = 7.0

# Сколько секунд обещает страница (`POOL_REFRESH_MS`). Здесь оно только для
# текста ошибки: сверять число в тесте с числом в шаблоне значило бы держать
# копию, которая разойдётся молча.
POOL_REFRESH_EXPECTED_SEC = 3


@pytest.fixture
def page():
    """Страница админки под QA-учёткой; свои сессии убираем за собой."""
    before = _session_ids()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1600, 'height': 1000})
            page = context.new_page()
            _login(page)
            page.goto(f'{BASE_URL}/admin/browser')
            page.wait_for_selector('#poolCards', timeout=15000)
            # Первый ответ приходит уже после отрисовки: даём колонке заполниться,
            # иначе «до» посчитается по пустому месту.
            page.wait_for_timeout(2500)
            try:
                yield page
            finally:
                browser.close()
    finally:
        _sessions_drop(_session_ids() - before)


class TestPoolAutoRefresh:
    """Колонка идёт за контейнером сама."""

    def test_pool_polls_every_few_seconds(self, page: Page):
        """
        Круг опроса действительно частый — считаем запросы, а не ждём удачи.

        Проверка «карточка появилась за 7 секунд» вероятностна: общий круг
        страницы (10 с) может попасть в то же окно и показать её вместо пула.
        Так и вышло при снятом круге — тест позеленел на чужой работе.

        Здесь измеряется то, что просили: частота. За окно ожидания запросов к
        `/api/browser/session` должно пройти хотя бы столько, сколько даёт круг
        в три секунды, — общий десятисекундный столько не наберёт при всём
        желании.
        """
        seen = []
        page.on('request', lambda r: seen.append(r.url)
                if '/api/browser/session' in r.url and r.method == 'GET' else None)

        page.wait_for_timeout(int(PROBE_WAIT_SEC * 1000))

        # За 7 секунд круг в 3 с даёт два запроса, круг в 10 с — ноль или один.
        assert len(seen) >= 2, (
            f'за {PROBE_WAIT_SEC}с колонка сходила за списком {len(seen)} раз(а) — '
            f'это не похоже на круг в {POOL_REFRESH_EXPECTED_SEC}с')

    def test_new_page_appears_without_reload(self, page: Page):
        """
        Открытая мимо админки страница показывается в колонке сама.

        Тот самый случай: человек смотрит на пул, а страницы заводит сценарий.

        Окно шире круга пула, но уже общего круга страницы — и всё же этот тест
        слабее соседнего: общий круг может попасть в то же окно. Держим его
        ради сквозной проверки (запрос → отрисовка), а частоту стережёт
        `test_pool_polls_every_few_seconds`.
        """
        before = _cards(page)

        session_id = _probe_open()
        assert session_id, 'контейнер не завёл страницу — проверять нечего'

        assert _wait_cards(page, lambda n: n > before), (
            f'за {PROBE_WAIT_SEC}с колонка не показала новую страницу '
            f'(было {before}, стало {_cards(page)})')

    def test_closed_page_disappears_without_reload(self, page: Page):
        """
        Погашенная страница уходит из колонки сама.

        Обратная сторона: пул смотрят, чтобы поймать забытые страницы, и
        «призрак» закрытой врал бы ровно тому, кто пришёл разбираться.
        """
        before = _cards(page)
        session_id = _probe_open()
        assert session_id
        assert _wait_cards(page, lambda n: n > before), 'страница не появилась'

        _sessions_drop({session_id})

        assert _wait_cards(page, lambda n: n <= before), (
            f'за {PROBE_WAIT_SEC}с колонка не убрала погашенную страницу '
            f'(осталось {_cards(page)}, ожидалось {before})')

    def test_counter_follows_the_list(self, page: Page):
        """
        Счётчик в заголовке считает то же, что видно в колонке.

        Он отвечает на вопрос «сколько мест осталось», и разойдись он со
        списком — соврал бы ровно там, где по нему принимают решение.
        """
        _probe_open()
        assert _wait_cards(page, lambda n: n > 0), 'страница не появилась'

        shown = page.locator('#poolCount').text_content() or ''
        count = _cards(page)

        assert shown.strip().startswith(str(count)), (
            f'счётчик «{shown}» не сходится с числом карточек ({count})')


def _cards(page: Page) -> int:
    return page.locator('#poolCards .pool-card').count()


def _wait_cards(page: Page, ok) -> bool:
    """Ждать, пока число карточек удовлетворит условию. Опрос — глазами страницы."""
    deadline = time.monotonic() + PROBE_WAIT_SEC
    while time.monotonic() < deadline:
        if ok(_cards(page)):
            return True
        page.wait_for_timeout(400)

    return ok(_cards(page))


def _probe_open() -> str:
    """
    Завести страницу прямо в контейнере, мимо админки.

    Адрес — `example.com`: он открывается и не тянет за собой ничего лишнего.
    Открылся он или нет, для теста неважно — колонка показывает и неудавшиеся
    переходы, — но живой адрес не оставляет двусмысленности.

    Ошибку **не глушим**: не завелась страница — проверять нечего, и тест обязан
    сказать почему. Проглоченное исключение дало бы пустой номер и жалобу на
    колонку, которая ни при чём.

    Номер лежит в `session`, а не в корне ответа (`{"session": {...}}`).
    """
    response = httpx.post(f'{BROWSER_URL}/browser/session', timeout=30.0,
                          headers=_browser_headers(),
                          json={'name': PROBE_NAME, 'url': 'https://example.com',
                                'site_id': 1})
    response.raise_for_status()

    return str((response.json().get('session') or {}).get('session_id') or '')


def _session_ids() -> set:
    with suppress(Exception):
        response = httpx.get(f'{BROWSER_URL}/browser/session', timeout=10.0,
                             headers=_browser_headers())
        response.raise_for_status()
        return {str(row['session_id']) for row in response.json().get('sessions') or []}

    return set()


def _sessions_drop(session_ids: set) -> None:
    for session_id in session_ids:
        with suppress(Exception):
            httpx.delete(f'{BROWSER_URL}/browser/session/{session_id}', timeout=10.0,
                         headers=_browser_headers())


def _browser_headers() -> dict:
    token = os.getenv('BROWSER_API_TOKEN', '')

    return {'X-Browser-Token': token} if token else {}


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
