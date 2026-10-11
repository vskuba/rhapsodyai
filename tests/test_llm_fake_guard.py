"""Сторож режима подмены: выход к живой модели при `LLM_FAKE` — отказ.

## ⚠⚠ Что стережётся и какой ценой узнано

Подмена уводит на подменный сервис **ход workflow** (`llm_model_get`). Мимо неё
есть пути: зрение (`ai_vision`), генерация картинок, пинг пула — каждый берёт
адрес сервиса сам. Уйди запрос туда, и он пойдёт к живой модели **молча**:
подмена не кричит о том, что её обошли.

Цена молчания измерена. Выключатель подмены пролежал неподключённым с 24.09 по
11.10.2026: все `tests_llm` ходили к живой `gx10/qwen-small`, прогон сюиты шёл
**79 минут вместо шести**, а узнать это можно было только запросом в базу — ни
одного обращения к `fake/echo` за всю её историю. Платили ответами живых людей:
нода одна на тесты и на прод.

⚠ Тесты чистые: сторож ставится и снимается внутри теста, живой сети не
касается — проверяется именно отказ **до** выхода наружу. Клиент заводится
разовый, короткого срока: предмет проверки — сам транспорт, и общий пул слоя
(`http_pool_transport`) тут только скрыл бы его за переиспользованием.

⚠⚠ У самого прогона `LLM_FAKE` не стоит (переменная живёт в окружении
контейнера, `docker-compose.override.yml`), поэтому выключатель здесь
подменяется. Иначе тест проверял бы «ничего не делает», а не сторож.
"""
import asyncio

import httpx
import pytest

from ai.provider import ai_provider_registry as registry
from ai.provider.ai_provider_registry import (AiProviderFakeEscapeError,
                                              ai_provider_registry_fake_guard_start,
                                              ai_provider_registry_live_allowed,
                                              ai_provider_registry_live_hosts)

pytestmark = pytest.mark.ai

# Заведомо чужой адрес: сторож обязан пропускать всё, что не LLM-сервис.
GUARD_FOREIGN_URL = 'http://127.0.0.1:9/ping'


@pytest.fixture
def fake_on(monkeypatch):
    """Включить подмену на время теста — как если бы сервер поднялся с `LLM_FAKE`."""
    monkeypatch.setattr(registry, 'ai_provider_fake_on', lambda: True)


class TestWhatCountsAsLive:
    """Список запрещённых адресов: что в нём обязано быть и чего быть не должно."""

    def test_a_model_specific_address_is_covered(self):
        """⚠⚠ Адрес, который знает только провайдер, — главный случай.

        У gx10 общего `GX10_API_URL` нет вовсе: адрес свой на каждый размер
        (`GX10_SMALL_API_URL`), и спросить его можно только с именем модели в
        руках. Это ровно та модель, к которой ходили тесты, — сторож без неё
        прикрывал бы всё, кроме главного.
        """
        plain = ai_provider_registry_live_hosts()
        named = ai_provider_registry_live_hosts(['gx10/qwen-small'])

        assert named - plain, \
            'имя модели не добавило ни одного адреса — gx10 остался открыт'

    def test_the_fake_service_is_never_forbidden(self):
        """⚠ К подмене и ведут все дороги — запретить её значило бы всё сломать."""
        from tests_llm.conftest import LLM_FAKE_URL

        fake_host = httpx.URL(LLM_FAKE_URL).host
        hosts = ai_provider_registry_live_hosts(['gx10/qwen-small', 'fake/echo'])

        assert not [one for one in hosts if one[0] == fake_host], \
            f'подмена ({fake_host}) попала в запрет'

    def test_a_neighbour_service_is_not_mistaken_for_a_model(self):
        """⚠⚠ Оболочка Claude Code моделью не является.

        Её адрес зовётся `CLAUDE_SHELL_API_URL`, и угадывание по шаблону
        `<СЕРВИС>_*_API_URL` утащило бы её в запрет вместе с `CLAUDE_API_URL`.
        Поэтому адреса под модель спрашиваются у провайдера, а не по шаблону.
        """
        from config.config import config_get

        raw = str(config_get('CLAUDE_SHELL_API_URL') or '').strip()
        if not raw:
            pytest.skip('на этой установке нет CLAUDE_SHELL_API_URL')

        shell = httpx.URL(raw if '://' in raw else f'http://{raw}')
        hosts = ai_provider_registry_live_hosts(['gx10/qwen-small'])

        assert (str(shell.host), int(shell.port or 0)) not in hosts, \
            'оболочка Claude Code принята за LLM-сервис'


class TestTheGuard:
    """Поведение сторожа: кого держит, кого пускает, когда молчит."""

    def test_it_does_nothing_without_the_switch(self):
        """⚠ Без `LLM_FAKE` сторож не встаёт: на проде переменной нет."""
        stop = ai_provider_registry_fake_guard_start(['gx10/qwen-small'])
        try:
            assert not _guard_installed(), 'сторож встал без выключателя'
        finally:
            stop()

    def test_it_refuses_a_live_model(self, fake_on):
        """⚠⚠ Главный случай: запрос к живой модели — отказ до выхода наружу."""
        host, port = _live_pair()

        stop = ai_provider_registry_fake_guard_start(['gx10/qwen-small'])
        try:
            with pytest.raises(AiProviderFakeEscapeError) as refused:
                asyncio.run(_get(f'http://{host}:{port}/v1/models'))

            assert 'подмен' in str(refused.value), 'отказ не объясняет причину'
        finally:
            stop()

    def test_it_lets_a_foreign_address_through(self, fake_on):
        """⚠ Запрещены **только** LLM-адреса: сервер ходит к соседу и в браузер.

        Запрет «всего наружу» остановил бы его работу целиком.

        ⚠⚠ Проверяется «наш сторож промолчал», а не «запрос прошёл»: поверх
        стоит сторож сюиты (`no_outside_http`), и чужой адрес он отвергнет
        своим отказом — это правильно и к делу не относится.
        """
        stop = ai_provider_registry_fake_guard_start(['gx10/qwen-small'])
        try:
            with pytest.raises(Exception) as refused:
                asyncio.run(_get(GUARD_FOREIGN_URL))

            assert not isinstance(refused.value, AiProviderFakeEscapeError), \
                'сторож подмены принял чужой адрес за LLM-сервис'
        finally:
            stop()

    def test_the_ping_may_go_live_on_purpose(self, fake_on):
        """⚠⚠ Пингу живая модель нужна по существу.

        Его предмет — «жив ли настоящий сервис». Уведи на подмену, и он начнёт
        отвечать «все живы» всегда, то есть врать именно в том, ради чего
        заведён. Разрешение объявляется явно и только им.
        """
        host, port = _live_pair()

        stop = ai_provider_registry_fake_guard_start(['gx10/qwen-small'])
        try:
            with ai_provider_registry_live_allowed():
                # ⚠ Запрос всё равно не дойдёт: поверх стоит сторож сюиты, и
                # живой сети в тестах не бывает. Предмет проверки — что отказ
                # пришёл **не от нашего** сторожа, то есть дверь он открыл.
                with pytest.raises(Exception) as refused:
                    asyncio.run(_get(f'http://{host}:{port}/v1/models'))

                assert not isinstance(refused.value, AiProviderFakeEscapeError), \
                    'разрешение не открыло дверь — пинг упадёт при подмене'
        finally:
            stop()

    def test_stopping_puts_the_transport_back(self, fake_on):
        """⚠ Снятие возвращает транспорт: сторож не должен пережить свой вызов."""
        before = httpx.AsyncHTTPTransport.handle_async_request

        stop = ai_provider_registry_fake_guard_start(['gx10/qwen-small'])
        assert _guard_installed(), 'сторож не встал при включённом выключателе'
        stop()

        assert httpx.AsyncHTTPTransport.handle_async_request is before


class TestThePingDeclaresItself:
    """Пинг — единственный, кому разрешено живое; это под сторожем."""

    def test_the_ping_wraps_its_call(self):
        """⚠⚠ Пропади обёртка — пинг начнёт падать при включённой подмене.

        Разбором исходника: довести вызов до живой модели значило бы отнять
        ответ у человека, а подменить её здесь нечем — предмет пинга в живом
        сервисе.
        """
        from pathlib import Path

        source = Path('src/project/team/team_llm_ping.py').read_text(encoding='utf-8')

        assert 'ai_provider_registry_live_allowed()' in source, \
            'пинг больше не объявляет себя живым — при подмене он упадёт'

    def test_nobody_else_claims_the_right(self):
        """⚠⚠ Разрешение — на одного. Второй потребитель значит, что на тестовой
        машине ещё кто-то пошёл к модели, отвечающей живым людям.
        """
        import subprocess

        # ⚠ `--include=*.py`: без него grep находит и `.pyc` рядом, и список
        # не сходится с собой же на второй прогон.
        found = subprocess.run(
            ['grep', '-rl', '--include=*.py', 'ai_provider_registry_live_allowed',
             'src/', 'main_uvicorn.py'],
            capture_output=True, text=True).stdout.split()

        assert found == ['src/project/team/team_llm_ping.py'], \
            f'разрешение на живую модель взял кто-то ещё: {found}'


# ---------------------------------------------------------------------------
# Приватное
# ---------------------------------------------------------------------------

async def _get(url: str) -> None:
    """Сходить по адресу — коротким сроком: ответ не нужен, нужен сам выход."""
    async with httpx.AsyncClient(timeout=1.0) as client:
        await client.get(url)


def _guard_installed() -> bool:
    """Стоит ли **наш** сторож на транспорте httpx.

    ⚠ По своему имени обёртки, а не по факту подмены: на транспорте уже стоит
    сторож сюиты (`http_mock_guard`, фикстура `no_outside_http`), и проверка
    «транспорт подменён» была бы истинной всегда.
    """
    return (httpx.AsyncHTTPTransport.handle_async_request.__name__
            == '_ai_provider_fake_guard_async')


def _live_pair() -> tuple:
    """Пара «хост, порт» живого сервиса с явным портом — или пропуск теста."""
    hosts = ai_provider_registry_live_hosts(['gx10/qwen-small'])
    live = sorted(one for one in hosts if one[1])

    if not live:
        pytest.skip('на этой установке нет адреса модели с портом')

    return live[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
