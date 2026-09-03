"""
Страница `/docs` собирается из своей статики, а не с чужих доменов.

Встроенный Swagger UI у FastAPI тянет три файла извне: скрипт и стили с
`cdn.jsdelivr.net`, favicon — с `fastapi.tiangolo.com`. Для админки это внешняя точка
отказа (нет интернета — нет документации), утечка факта захода к третьей стороне и
плавающая версия: тег `@5` завтра отдаёт другую сборку. Правило проекта — зависимости
локально, без CDN (`docs-common/frontend_rules.md`).

Сторожат здесь две вещи, и обе нужны порознь. Первая — что в разметке нет ни одного
внешнего адреса: вернись умолчание FastAPI (например, кто-то снимет `docs_url=None`),
страница снова заработает, и по её виду подмену не заметить — пока не пропадёт
интернет. Вторая — что файлы, на которые она ссылается, действительно отдаются: ссылка
на несуществующий путь ломает страницу молча, пустым белым экраном.

Тесты ходят по HTTP к запущенному серверу, как остальная сюита: адрес — `BASE_URL`
(`conftest.py`), по умолчанию `http://localhost:8011`.
"""
import re

import httpx
import pytest

from tests.conftest import BASE_URL

pytestmark = pytest.mark.core

# Адрес страницы и файлы, которыми она обязана обходиться. Пути — те же, что в
# `swagger_ui_docs` (`main_uvicorn.py`); разъедься они, тест покраснеет на втором
# случае, а не на первом.
API_DOCS_URL = '/docs'
API_DOCS_ASSETS = (
    '/static/js/vendor/swagger-ui-bundle.js',
    '/static/css/vendor/swagger-ui.css',
    '/static/assets/swagger-favicon.png',
)


def _docs_html() -> str:
    """Разметка страницы документации. Сервер обязан отдать её без входа."""
    response = httpx.get(f'{BASE_URL}{API_DOCS_URL}', timeout=15.0, follow_redirects=False)
    assert response.status_code == 200, f'{API_DOCS_URL} ответил {response.status_code}'

    return response.text


def test_api_docs_page_has_no_external_links():
    """Ни одного адреса наружу: ни CDN, ни favicon с чужого сайта."""
    external = sorted(set(re.findall(r'https?://[^\s"\'<>]+', _docs_html())))

    assert not external, f'страница документации ходит наружу: {external}'


def test_api_docs_page_uses_local_assets():
    """Скрипт, стили и значок берутся из своей статики — по тем самым путям."""
    html = _docs_html()

    for asset in API_DOCS_ASSETS:
        assert asset in html, f'{asset} со страницы пропал — она собрана не из своей статики'


@pytest.mark.parametrize('asset', API_DOCS_ASSETS)
def test_api_docs_assets_are_served(asset: str):
    """
    Файл по ссылке действительно есть.

    Проверка отдельная от предыдущей: ссылка на несуществующий путь оставляет разметку
    правильной, а страницу — белой. Так же ловится и обратное — файл забыли положить в
    репозиторий, и на чистом чекауте документация пуста.
    """
    response = httpx.get(f'{BASE_URL}{asset}', timeout=30.0, follow_redirects=False)

    assert response.status_code == 200, f'{asset} ответил {response.status_code}'
    assert len(response.content) > 500, f'{asset} подозрительно пуст: {len(response.content)} байт'


def test_api_docs_schema_is_reachable():
    """
    Схема на месте: без неё страница отрисуется пустой оболочкой.

    Смотрим не только код ответа, но и наличие путей: `openapi.json` с пустым `paths`
    — это работающий сервер, который ничего не документирует, и по виду страницы такое
    отличить нельзя.
    """
    response = httpx.get(f'{BASE_URL}/openapi.json', timeout=15.0, follow_redirects=False)

    assert response.status_code == 200, f'/openapi.json ответил {response.status_code}'
    assert response.json().get('paths'), 'схема пуста — документировать нечего'
