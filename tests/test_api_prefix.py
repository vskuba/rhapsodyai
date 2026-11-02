"""Публичные ручки живут под `/api`, и в схеме их видно только там.

## ⚠⚠ Что стережётся

`/docs` — это лицо установки для соседних проектов: по нему пишут вызовы в
DatingAi и BlogAi. Пока половина ручек лежала под `/api`, а половина в корне
(`/chat/ask`, `/agent/list`, `/detective/case_agents`), угадать правило было
нельзя — его просто не было.

Префикс ставится **в одном месте** (`main_uvicorn.py`, `API_PREFIX`), а не в
каждом роутере: смысл правки — «всё наружу под одним префиксом», и проверить
это должно быть можно одним взглядом. Разложенный по пятидесяти файлам, он
проверяется их обходом, и первый же забытый не заметит никто.

## ⚠⚠⚠ Двойной префикс — не теория

У `blog` и `stt` префикс стоит **в самом роутере**
(`APIRouter(prefix="/api/blog")`). Добавленный вторым при подключении, он дал
`/api/api/blog/compose` — девять маршрутов, и поймано это было схемой на
первом же прогоне, а не рассуждением. Отсюда первая проверка здесь.

## ⚠ Старый путь жив, но скрыт

Между выкладкой соседа и переездом вызывающих проходят минуты. Сними мы
старый путь сразу — у DatingAi встали бы чат и агенты. Поэтому роутер
подключён дважды: новый в схеме, старый скрытым. Снимается третьим заходом,
когда вызывающих не останется; сторож перевернётся вместе с ним.

⚠ Проверяется **по схеме приложения**, а не запросами в сеть: сюите не нужен
ни поднятый сервер, ни чужой токен, а список маршрутов FastAPI знает сам.
"""

import pytest

pytestmark = pytest.mark.core

# Ручки, которые видны соседним проектам. Они и обязаны лежать под `/api`.
PUBLIC_HEADS = ('/chat/', '/agent/', '/detective/', '/blog/', '/stt/')


def _paths() -> set:
    """Маршруты приложения — как их видит FastAPI."""
    from main_uvicorn import app

    out = set()
    for route in app.routes:
        path = getattr(route, 'path', '')
        if path:
            out.add(path)

    return out


def _schema() -> set:
    """Маршруты, попавшие в `/docs`."""
    from main_uvicorn import app

    return set(app.openapi().get('paths') or {})


class TestNothingIsPrefixedTwice:
    """⚠⚠⚠ `/api/api/...` — то, чем кончилась первая редакция правки."""

    def test_no_double_prefix_anywhere(self):
        doubled = sorted(p for p in _paths() if p.startswith('/api/api'))

        assert not doubled, (
            f'префикс поставлен дважды: {doubled[:3]}. У `blog` и `stt` он '
            'стоит в самом роутере — второй при подключении не нужен')

    def test_the_schema_is_clean_too(self):
        """Схема отдельно: её читают глазами, и в ней двойной особенно заметен."""
        doubled = sorted(p for p in _schema() if p.startswith('/api/api'))

        assert not doubled, doubled


class TestThePublicDoorsAreUnderApi:
    """⚠⚠ Ради этого всё: в `/docs` публичные ручки видны только под `/api`."""

    def test_every_public_path_in_the_schema_starts_with_api(self):
        loose = sorted(p for p in _schema()
                       if any(p.startswith(h) for h in PUBLIC_HEADS))

        assert not loose, (
            f'в схеме остались ручки без префикса: {loose}. Префикс ставится '
            'в `main_uvicorn.py` — либо `API_PREFIX` при подключении, либо '
            '`APIRouter(prefix=…)` у самого роутера, но не оба сразу')

    def test_the_known_doors_are_there(self):
        """⚠ Сторож обязан хоть что-то находить.

        Без этой проверки переименование роутеров сделало бы весь файл
        зелёным и пустым: проверка «ничего не осталось» на пустом множестве
        не падает никогда.
        """
        schema = _schema()

        for one in ('/api/chat/ask', '/api/chat/message/add',
                    '/api/agent/list', '/api/agent/create',
                    '/api/detective/case_agents'):
            assert one in schema, f'{one} пропал из схемы'


class TestEveryDoorHasItsSection:
    """⚠⚠ В `/docs` у каждой ручки свой раздел, и `default` быть не должно.

    `default` — не раздел, а его отсутствие: туда FastAPI складывает всё, чему
    тега не поставили. Девять ручек чата, агентов и детектива лежали там одной
    кучей рядом с осмысленными `stt` и `blog`, и читающий документацию не
    видел границ между делами.

    ⚠ Тег — свойство **роутера** (`APIRouter(tags=…)`), как у `stt` и `blog`:
    он описывает, что это за ручки. Префикс при этом остался в
    `main_uvicorn.py` — он переходный, и его место там, где виден весь список
    сразу.
    """

    @staticmethod
    def _tags() -> dict:
        """Путь → теги, которыми он подписан в схеме."""
        from main_uvicorn import app

        out = {}
        for path, methods in (app.openapi().get('paths') or {}).items():
            for one in methods.values():
                out.setdefault(path, set()).update(one.get('tags') or [])

        return out

    def test_nothing_falls_into_default(self):
        loose = sorted(p for p, tags in self._tags().items() if not tags)

        assert not loose, (
            f'без раздела остались: {loose}. Поставьте тег в `APIRouter(...)` '
            'самого роутера — так сделано у `stt` и `blog`')

    def test_the_public_sections_are_named(self):
        """⚠ Сторож обязан находить сами разделы, иначе он зеленеет впустую."""
        tags = set()
        for one in self._tags().values():
            tags |= one

        for want in ('chat', 'agent', 'detective', 'stt', 'blog'):
            assert want in tags, f'раздел «{want}» пропал из схемы'


class TestTheOldPathStillAnswers:
    """⚠ Переходный период: старый путь жив, но скрыт из схемы.

    Сними его раньше, чем переедут вызывающие, — у DatingAi встанут чат и
    агенты. Этот класс уходит третьим заходом вместе с самим путём.
    """

    def test_the_old_paths_are_still_routed(self):
        paths = _paths()

        for one in ('/chat/ask', '/chat/message/add', '/agent/list',
                    '/agent/create', '/detective/case_agents'):
            assert one in paths, (
                f'{one} больше не отвечает — вызывающие в DatingAi встанут')

    def test_but_they_are_hidden_from_the_docs(self):
        """В схеме их быть не должно: два адреса одной ручки читаются как
        два разных дела."""
        schema = _schema()

        for one in ('/chat/ask', '/agent/list', '/detective/case_agents'):
            assert one not in schema, f'{one} виден в /docs вторым адресом'
