"""Обвязка LLM-тестов: живой вызов агента и чтение его маршрута.

## ⚠⚠ Зачем отдельная папка, а не группа в `tests/`

Сюита `tests/` намеренно не зовёт модель: «LLM для этого не нужна, а лишний прогон
workflow стоил бы минуту и токены» (`tests/test_agent_variable.py`). Правило верное,
и ломать его группой внутри той же папки нельзя — `pytest tests/` перед выкладкой
подхватил бы её вместе со всем остальным.

Поэтому своя папка, и **её нет в `testpaths`**: полный прогон её не видит, запуск
только руками и по имени пути.

## ⚠⚠ Главное правило: проверяем маршрут, а не формулировку

Модель каждый раз отвечает иначе. Тест, сверяющий текст, красен через прогон и
приучает не смотреть на красное. Поэтому утверждения ставим там, где ответ
однозначен:

| Что проверяем | Чем |
|---|---|
| прогон дошёл до конца | `status` запуска в трассе |
| каким путём пошёл | список шагов: встретилась ли ветка |
| что решила модель | структурные поля шагов: `talk_topic`, `photo_deal` |
| текст | только «не пустой» и узкий список примет отказа |

Структурные поля — то, что шаг просит у модели в JSON. Их множество закрытое, и
сверять их можно как обычные значения.

## ⚠⚠ Трассу читаем ручкой, а не из базы

Соблазн сходить в `agent_workflow_trace` напрямую велик — и он приводит к
`RuntimeError: Event loop is closed`. Пул `mysql_` модульный и привязан к циклу
событий, в котором создан, а `pytest-asyncio` даёт каждому тесту **свой** цикл:
второй тест получает пул от первого и падает на освобождении соединения.

Ручка `/workflow_trace/run/…` отдаёт то же самое и живёт в клиенте теста. Заодно
сюита ходит по HTTP целиком, как и остальная.

⚠ Свой прогон ищем по `prompt_user` среди свежих: `session_uuid` ручка списка не
отдаёт. Тесты идут **по одному** (без `xdist`), поэтому «самый свежий с таким
вопросом» — это наш.

## ⚠ Что здесь сбой, а что шум

Разово падает инфраструктура, а не код: локальный Qdrant отдавал `ReadTimeout` на
одном поиске из трёх подряд, и прогон валился с 500. Поэтому `talk()` повторяет
вызов (`LLM_ATTEMPTS`) и показывает в `attempts`, со скольких попыток вышло.
Красное после повторов — повод смотреть, а не перезапускать.

## ⚠ Мусор, который остаётся

Собеседник теста заводится один раз и **не удаляется**: ручки удаления у соседа
нет, а факты разговора уже легли в Qdrant под его ключ. Это нарочно — свой
собеседник не даёт тестам писать факты в документ живого `dating_person`.
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field

import httpx
import pytest

from tests.constants import TEST_AUTH

BASE_URL = os.getenv('BASE_URL', '').strip().rstrip('/') or 'http://localhost:8011'

# Сколько ждём ответа агента. ⚠ Не запас «на всякий случай»: обычная реплика идёт
# 11–12 секунд, а заход, где модель заводит факты девушки с нуля, — минуту. Число
# уходит в `chat_timeout` переменной вызова, иначе движок оборвёт прогон на своих
# шестидесяти.
LLM_TIMEOUT = float(os.getenv('LLM_TIMEOUT', '220'))

# Сколько раз повторить вызов, сорвавшийся не по вине кода. Два, а не один: один
# разовый `ReadTimeout` от Qdrant валит прогон целиком, и без повтора половина
# запусков красная без причины.
LLM_ATTEMPTS = int(os.getenv('LLM_ATTEMPTS', '2'))

# Агент и собеседник, от чьего имени идёт разговор.
#
# ⚠ Агента ищем **по имени**, а не по номеру: номер разъезжается между
# установками (локально 1663, на проде свой), и прибитая константа сломала бы
# тесты на первом же переносе базы.
LLM_AGENT_NAME = os.getenv('LLM_AGENT_NAME', 'dating_girl_universal')
LLM_COMPANION_NAME = 'test_llm_companion'
LLM_COMPANION_TITLE = 'Gerard'

# Шаги-приметы маршрута. Названия берутся из трассы как есть.
STEP_TOPIC = 'Тема разговора'
STEP_BRANCH = 'Ветка: письма и фото'
STEP_FACTS_TAGS = 'qdrant_fact_search_girl_tags'
STEP_FACTS_PLAIN = 'qdrant_fact_search_girl'
STEP_ANSWER = 'Ответ'
# Шаг, сочиняющий реплику. ⚠ Не путать с `STEP_ANSWER`: тот отдаёт готовое
# наружу, а здесь собирается промпт — то, что вправду видит модель.
STEP_MAKE = 'Генерация ответа'
STEP_SILENCE = 'Тишина'

# Что нашли один раз — номер агента и собеседника. ⚠ Обычный словарь, а не
# сессионная фикстура: в `pytest-asyncio` 1.x сессионная async-фикстура живёт в
# цикле событий **первого** теста и со второго падает «Event loop is closed».
_FOUND = {}


@dataclass
class Talk:
    """Один разговор: что ответили и каким путём к этому пришли."""

    text: str = ''
    session: str = ''
    status: str = ''
    attempts: int = 0
    route: tuple = ()
    route_all: tuple = ()
    vars: dict = field(default_factory=dict)
    # Промпты шагов **после подстановки** — то, что вправду ушло в модель.
    #
    # ⚠⚠ Нужны затем, что по ответу нельзя судить о входе. Модель пересказывает
    # своими словами: получив «Занятие: lighthouse keeper», она отвечает «i bet
    # you're good with lights» — данные дошли, а искомого слова в ответе нет.
    # Проверка «вошло ли» обязана смотреть на вход, иначе она проверяет
    # красноречие.
    prompts: dict = field(default_factory=dict)

    def went_through(self, step: str) -> bool:
        """Встретился ли шаг на маршруте — в главном прогоне или в подпрогоне."""
        return step in self.route_all

    def prompt_of(self, step: str) -> str:
        """Отрисованный промпт шага. Пусто — шага не было или промпта у него нет."""
        return str(self.prompts.get(step) or '')

    def __str__(self) -> str:
        return (f'\nответ: {self.text!r}\n'
                f'маршрут: {" → ".join(self.route) or "пусто"}\n'
                f'решения: talk_topic={self.vars.get("talk_topic")!r} '
                f'photo_deal={self.vars.get("photo_deal")!r}\n'
                f'попыток: {self.attempts}, статус: {self.status}, сессия: {self.session}')


def _walk(run: dict, main: list, every: list, merged: dict, prompts: dict,
          top: bool = True) -> None:
    """Обходит дерево прогона: шаги родителя и всех подпрогонов."""
    for step in run.get('steps') or []:
        title = str(step.get('step_title') or '')

        if title:
            every.append(title)

            if top:
                main.append(title)

            # ⚠ Берём **первую** отрисовку шага: повтор после неудачной проверки
            # идёт с тем же входом, а последняя запись затёрла бы то, с чего
            # разговор начался.
            if title not in prompts:
                prompts[title] = _rendered_prompt(step)

        changed = step.get('variables_changed')
        try:
            merged.update(json.loads(changed) if isinstance(changed, str)
                          else (changed or {}))
        except (TypeError, ValueError):
            pass

    for child in run.get('children') or []:
        _walk(child, main, every, merged, prompts, top=False)


def _rendered_prompt(step: dict) -> str:
    """Промпт шага после подстановки переменных. Пусто — у шага его нет.

    ⚠ Поле приходит то строкой, то разобранным словарём — зависит от того, как
    его положили. Читаем оба вида: разбираться в этом на каждой проверке значило
    бы размазать знание о хранении по тестам.
    """
    meta = step.get('metadata_rendered')

    if isinstance(meta, str):
        try:
            meta = json.loads(meta or '{}')
        except (TypeError, ValueError):
            return ''

    return str((meta or {}).get('prompt_user') or '')


async def _trace_read(client, agent: int, question: str) -> tuple:
    """Маршрут и решения свежего прогона по тексту вопроса.

    ⚠ Ручка списка отдаёт только верхний уровень (`depth = 0`) и сортирует по
    убыванию номера — первый совпавший и есть наш последний прогон. Шаги и
    подпрогоны приходят уже ручкой подробностей.
    """
    answer = await client.get('/workflow_trace/run/list',
                              params={'agent_id': agent, 'limit': 30})

    if answer.status_code != 200:
        return (), (), {}, '', {}

    mine = next((one for one in (answer.json().get('result') or [])
                 if str(one.get('prompt_user') or '') == str(question)), None)

    if not mine:
        return (), (), {}, '', {}

    full = await client.get(f'/workflow_trace/run/{mine.get("run_uuid")}')

    if full.status_code != 200:
        return (), (), {}, str(mine.get('status') or ''), {}

    root = full.json().get('result') or {}
    main, every, merged, prompts = [], [], {}, {}
    _walk(root, main, every, merged, prompts)

    return (tuple(main), tuple(every), merged, str(root.get('status') or ''),
            prompts)


@pytest.fixture
async def client():
    """Вошедший клиент. ⚠ На каждый тест свой — вместе с его циклом событий.

    Вход стоит десятков миллисекунд против десятка секунд у вызова модели, так
    что экономить тут нечего, а сессионный клиент ломает прогон со второго теста.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=LLM_TIMEOUT + 30) as got:
        answer = await got.post('/auth/login', json=TEST_AUTH)

        if answer.status_code != 200:
            pytest.fail(f'вход не прошёл ({answer.status_code}): {answer.text[:200]}.'
                        f' Проверь QA_USERNAME/QA_PASSWORD в .env.local и что сервер'
                        f' поднят на {BASE_URL}')

        yield got


@pytest.fixture
async def agent_id(client) -> int:
    """Номер агента девушки по его системному имени."""
    if 'agent' in _FOUND:
        return _FOUND['agent']

    answer = await client.get(f'/agent/name/{LLM_AGENT_NAME}')

    if answer.status_code != 200:
        pytest.fail(f'агента «{LLM_AGENT_NAME}» нет ({answer.status_code}).'
                    f' Он заводится миграциями соседа — проверь, что они применены')

    _FOUND['agent'] = int((answer.json().get('result') or {}).get('id') or 0)

    return _FOUND['agent']


@pytest.fixture
async def companion_id(client) -> int:
    """Свой собеседник тестов: заводится один раз, дальше переиспользуется.

    ⚠ Не `dating_person` (тот, которым ходит боевой код): факты разговора ложатся
    в Qdrant под ключ собеседника, и тесты засоряли бы живой документ.
    """
    if 'companion' in _FOUND:
        return _FOUND['companion']

    async def _find() -> int:
        answer = await client.get('/companion/list')

        if answer.status_code != 200:
            return 0

        for one in (answer.json().get('result') or []):
            if str(one.get('name')) == LLM_COMPANION_NAME:
                return int(one.get('id') or 0)

        return 0

    found = await _find()

    if not found:
        made = await client.post('/companion', json={'name': LLM_COMPANION_NAME,
                                                     'title': LLM_COMPANION_TITLE})
        if made.status_code not in (200, 201):
            pytest.fail(f'собеседник теста не завёлся ({made.status_code}):'
                        f' {made.text[:200]}')

        found = await _find()

    if not found:
        pytest.fail('собеседник теста заведён, но не читается списком')

    _FOUND['companion'] = found

    return found


@pytest.fixture
async def talk(client, agent_id, companion_id):
    """Задать агенту реплику и получить ответ вместе с маршрутом.

    Args:
        question: что пишет собеседник.
        history: разговор пары строками, старое сверху (`talk_history`).
        variables: что ещё положить в переменные вызова.

    ⚠ Каждый вызов — **своя сессия**: иначе история одного теста доезжает до
    следующего, и маршрут зависит от порядка запуска.
    """

    async def _talk(question: str, history: str = '', variables: dict = None) -> Talk:
        session = str(uuid.uuid4())
        payload = {'question': str(question), 'agent_id': agent_id,
                   'companion_id': companion_id, 'session_uuid': session,
                   'variables': {'chat_timeout': LLM_TIMEOUT,
                                 'talk_history': str(history or ''),
                                 **(variables or {})}}
        last = ''

        for attempt in range(1, LLM_ATTEMPTS + 1):
            try:
                answer = await client.post('/chat/ask', json=payload)
            except httpx.HTTPError as e:
                last = f'связь: {e}'
                await asyncio.sleep(2)
                continue

            if answer.status_code == 200:
                route, every, merged, status, prompts = await _trace_read(
                    client, agent_id, question)

                return Talk(text=str(answer.json().get('result') or ''),
                            session=session, status=status, attempts=attempt,
                            route=route, route_all=every, vars=merged,
                            prompts=prompts)

            last = f'{answer.status_code}: {answer.text[:300]}'
            # ⚠ Новая сессия на повтор: прошлая уже несёт оборванный прогон, и
            # маршрут смешался бы из двух попыток.
            session = str(uuid.uuid4())
            payload['session_uuid'] = session
            await asyncio.sleep(2)

        route, _, _, _, _ = await _trace_read(client, agent_id, question)
        pytest.fail(f'агент не ответил за {LLM_ATTEMPTS} попыт(ки). Последнее: {last}\n'
                    f'маршрут оборванного прогона: {" → ".join(route) or "пусто"}')

    return _talk
