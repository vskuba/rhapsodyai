"""
Открытие сайта на `/admin/browser` переключает **выбранный** сайт, а не только адрес.

Дефект был такой. Кнопка «Открыть» на карточке подставляла её адрес в строку и уводила
на вкладку «Сессии», но текущий сайт не меняла — он оставался из прошлого захода, из
`localStorage`. Человек открывал LadaDate, а в шапке страницы стоял Goldenbride, и по
нему же отбиралось всё остальное: сессии, сценарии, журналы и переменные.

Последнее опаснее всего. Переменные сайта — это логины и пароли: на экране LadaDate
показывались бы чужие учётные данные, а сохранение легло бы в чужой сайт.

Проверка идёт живым браузером, потому что дефект живёт в связке трёх состояний
(`localStorage`, значение селекта, поле адреса), и ни одно из них не видно из API.

Требуется запущенный сервер на BASE_URL и заведённые сайты (маркер `integration`).
"""

import os
from contextlib import suppress

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

from tests_browser.test_team_task_pages import _login

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

# Контейнер-браузер напрямую: порт опубликован на петле для отладки, и уборка
# сессий ходит сюда, а не через админку, — она нужна и когда тест упал на входе.
BROWSER_URL = os.getenv('BROWSER_TEST_URL', 'http://127.0.0.1:8014')

pytestmark = [pytest.mark.browser, pytest.mark.integration, pytest.mark.slow]

# Ключ, под которым страница помнит выбранный сайт между заходами.
SITE_KEY = 'browser_site_id'


@pytest.fixture
def page():
    """
    Страница теста — и уборка сессий, которые она открыла в контейнере-браузере.

    Кнопка «Открыть» заводит настоящую сессию, а `browser.close()` гасит только
    playwright-браузер самого теста: сессия в контейнере переживает прогон. Пул
    у контейнера общий и небольшой (25 мест), поэтому три теста за прогон копили
    по три забытых страницы — за утро набежало девять из двадцати, и все мёртвые.

    Убираем по разнице «до и после»: чужие сессии — открытые человеком в админке —
    трогать нельзя, а свои иначе не отличить, идентификатор придумывает контейнер.

    Уборка стоит во внешнем `finally`, а не после блока: упади вход в админку
    (`_login`) или сам `browser.close()` — и хвост функции не выполнился бы. Замер
    сессий до входа по той же причине: он не должен зависеть от того, дошли ли мы
    до страницы.

    **Прерванный прогон это не покрывает.** Убей pytest (Ctrl+C, SIGKILL) — уборка
    не выполнится, и сессия останется: проверено, одна пережила SIGINT. У самого
    контейнера TTL нет — сессия живёт до явного DELETE или до его перезапуска.
    Поэтому забытое подметает `tests/conftest.py` на старте следующего прогона.
    """
    before = _session_ids()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1600, 'height': 1000})
            page = context.new_page()
            _login(page)
            try:
                yield page
            finally:
                browser.close()
    finally:
        _sessions_drop(_session_ids() - before)


class TestSiteOpenSwitchesSite:
    """Открытие карточки — это и есть выбор сайта."""

    def test_open_switches_current_site(self, page: Page):
        """
        Главный случай: в памяти один сайт, открываем другой — выбранным должен стать
        открытый. Прошлый выбор ставим руками, иначе тест зависел бы от того, чем
        пользовались в браузере до него.
        """
        rows = _sites(page)
        if len(rows) < 2:
            pytest.skip('нужно хотя бы два сайта, чтобы было что перепутать')

        first, second = rows[0], rows[1]
        page.evaluate(f"localStorage.setItem('{SITE_KEY}', '{first['id']}')")
        page.goto(f'{BASE_URL}/admin/browser')
        page.wait_for_selector('.site-card', timeout=15000)
        page.wait_for_timeout(1500)

        _open_card(page, second['id'])

        assert page.evaluate(f"localStorage.getItem('{SITE_KEY}')") == str(second['id'])

    def test_url_bar_matches_opened_site(self, page: Page):
        """
        Адрес в строке — открытого сайта. Именно на этом дефект и заметили: в шапке
        стоял один сайт, в адресе другой.
        """
        rows = _sites(page)
        if len(rows) < 2:
            pytest.skip('нужно хотя бы два сайта')

        page.evaluate(f"localStorage.setItem('{SITE_KEY}', '{rows[0]['id']}')")
        page.goto(f'{BASE_URL}/admin/browser')
        page.wait_for_selector('.site-card', timeout=15000)
        page.wait_for_timeout(1500)

        _open_card(page, rows[1]['id'])
        shown = page.locator('#urlInput').input_value().rstrip('/')

        assert shown == rows[1]['url'].rstrip('/')

    def test_select_follows_opened_site(self, page: Page):
        """
        Селект в шапке синхронизирован с открытым сайтом. Он не декоративный: по нему
        человек читает, с чьими переменными и сценариями работает.
        """
        rows = _sites(page)
        if len(rows) < 2:
            pytest.skip('нужно хотя бы два сайта')

        page.evaluate(f"localStorage.setItem('{SITE_KEY}', '{rows[0]['id']}')")
        page.goto(f'{BASE_URL}/admin/browser')
        page.wait_for_selector('.site-card', timeout=15000)
        page.wait_for_timeout(1500)

        _open_card(page, rows[1]['id'])

        # Селект живёт на странице сайта (`/admin/browser/site`), а не в списке
        # карточек: там он шапка, по которой человек читает, с чьими переменными и
        # сценариями работает. Переходим туда и проверяем, что он показывает тот
        # сайт, который был открыт, а не сохранённый с прошлого захода.
        page.goto(f'{BASE_URL}/admin/browser/site')
        page.wait_for_selector('#browserSiteSelect', timeout=15000)
        page.wait_for_timeout(2500)
        select = page.locator('#browserSiteSelect')

        assert select.input_value() == str(rows[1]['id'])


def _sites(page: Page) -> list:
    """Сайты установки как их отдаёт API — по ним же строятся карточки."""
    data = page.evaluate(
        "async () => (await (await fetch('/api/browser/site',"
        " {credentials: 'include'})).json()).result")

    return [row for row in (data or []) if row.get('url')]


def _session_ids() -> set:
    """
    Сессии контейнера-браузера прямо сейчас.

    Ходим в контейнер напрямую (`:8014`), а не через админку: уборка нужна и тогда,
    когда тест упал на входе и залогиненной страницы у нас нет. Порт опубликован на
    петле для отладки — ровно такой случай. Не отвечает — возвращаем пустое: уборка
    не должна ронять тест, который сам по себе прошёл.
    """
    import httpx

    try:
        response = httpx.get(f'{BROWSER_URL}/browser/session', timeout=10.0,
                             headers=_browser_headers())
        response.raise_for_status()
        return {str(row['session_id']) for row in response.json().get('sessions') or []}
    except Exception:
        return set()


def _sessions_drop(session_ids: set) -> None:
    """Погасить названные сессии. Промах не важен: повторный DELETE не ошибка."""
    import httpx

    for session_id in session_ids:
        with suppress(Exception):
            httpx.delete(f'{BROWSER_URL}/browser/session/{session_id}', timeout=10.0,
                         headers=_browser_headers())


def _browser_headers() -> dict:
    """Токен контейнера, если он задан: с пустым `BROWSER_API_TOKEN` проверки нет."""
    token = os.getenv('BROWSER_API_TOKEN', '')

    return {'X-Browser-Token': token} if token else {}


def _open_card(page: Page, site_id: int) -> None:
    """
    Нажать «Открыть» на карточке сайта.

    Карточку ищем по `data-site-id`, а не по имени: имена сайтов вкладываются одно в
    другое («Ladadate» и «Ladadate тест»), и поиск по тексту брал бы первую попавшуюся —
    тест сравнивал бы адрес не той карточки, что открыл.

    Именно кнопку, а не карточку: клик по самой карточке открывает окно правки, и
    тест, кликающий мимо, был бы зелёным при любом состоянии кода.
    """
    card = page.locator(f'.site-card[data-site-id="{site_id}"]').first
    card.locator('.site-open').click()
    page.wait_for_timeout(3000)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
