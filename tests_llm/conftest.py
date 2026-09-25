"""Общая оснастка тестов workflow: прогон агента и чтение его маршрута.

## ⚠⚠ Зачем отдельная папка, а не группа в `tests/`

Сюита `tests/` намеренно не зовёт модель: «LLM для этого не нужна, а лишний прогон
workflow стоил бы минуту и токены» (`tests/test_agent_variable.py`). Но ход
разговора без модели не проверить — развилка «о чём сейчас речь» это шаг
`llm_to_json`, и решает его только она.

## ⚠⚠ Две группы: подменная модель и живая

**`llm` — идут сами, вместе со всей сюитой.** Ответы модели даёт подмена
(`ai.ai_llm_fake`): сценарий кладёт сам тест, прогон стоит секунды, наружу не
уходит ни один запрос. Сервис поднимается фикстурой автоматически.

**`llm_live` — не идут сами. Никогда.** Нода модели одна на тесты и на прод: та
же, что отвечает здесь, отвечает живым людям на сайте знакомств, и прогон —
отнятые у них ответы. Исключены в `addopts`, запускает человек:

    LLM_LIVE=1 .venv/bin/python3 -m pytest tests_llm -m llm_live -q

⚠ Так было не всегда: до подмены папки не было в `testpaths` вовсе, и запускал
всё человек. Ограничение сняла подмена, а не решение «и так сойдёт», — живые
тесты как стоили ответов живых людей, так и стоят.

⚠ Подменные проверяют **маршрут и передачу переменных**; качество текста, работу
судьи и осмысленность решений — только живые. Подробности —
`.claude/docs/testing_llm.md`.

## ⚠⚠ Раскладка: папка на workflow

    tests_llm/
        conftest.py              ← этот файл: общее на все workflow
        mark.py                  ← признак тестовых данных
        datingai.py              ← что кладёт и чего ждёт сосед
        dating_talk/             ← имя папки = имя workflow у соседа
            conftest.py          ← приметы шагов и своя фикстура вызова
            test_facts.py
        dating_invite_write/
            …

Имя папки — **системное имя workflow** (`agent_workflow.name`), без приставок и
сокращений. По упавшему тесту видно, что чинить, не открывая файла: путь
`tests_llm/dating_mail_write/test_marks.py` называет workflow сам.

⚠ **Приметы шагов живут в папке своего workflow, а не здесь.** Здесь — только то,
что верно для всех: как позвать агента, как прочитать трассу, как пометить
тестовые данные. Сложи имена шагов в общий `conftest`, и он через полгода станет
свалкой из шести наборов констант, где `STEP_JUDGE` неизвестно чей.

⚠⚠ **Совпадение — не дубль.** `'Правка по замечанию'` стоит и у инвайтов, и у
писем избранным, но это **разные строки** `agent_workflow_step` у разных
workflow: переименуй шаг одному, второй останется прежним. Общая константа
связала бы их насильно.

Обратный случай — `datingai.py`: карточки, указание про метки и конверт ответа
кладёт **одна** функция соседа, и владелец у них поэтому один.

Подробности правил — `.claude/docs/testing_llm.md`.

## ⚠⚠ Главное правило: проверяем маршрут, а не формулировку

Модель каждый раз отвечает иначе. Тест, сверяющий текст, красен через прогон и
приучает не смотреть на красное. Поэтому утверждения ставим там, где ответ
однозначен:

| Что проверяем | Чем |
|---|---|
| прогон дошёл до конца | `status` запуска в трассе |
| каким путём пошёл | `route` (верх), `route_all` (с подпрогонами) |
| был ли шаг на маршруте | `went_through(шаг)`, `times(шаг)` |
| **отработал** ли шаг | `ran(шаг)`, `times_ran(шаг)` |
| что модель **увидела** | `prompt_of(шаг)`, `prompt_each(шаг)` |
| что вернул шаг | `output_of(шаг)`, `output_each(шаг)` |
| текст ответа | **ничем. Никогда** |

## ⚠⚠ «Был на маршруте» — это не «отработал»

Шаг, с которого поток ушёл `transitions_before`, **пишется в трассу** наравне с
выполненными (`ai_framework_manager`: `trace_current_step()` перед `continue`).
Так и задумано — иначе развилки не было бы видно в журнале, — но для проверок это
ловушка: `went_through('Ответ в чат')` истинно и тогда, когда ветка чата уступила
дорогу письму.

Различает их `ran`: он не считает проходы, помеченные `phase = "before"`. Поэтому
«какой веткой пошло» спрашивают у `ran`, а `went_through` оставляют вопросам вида
«поток вообще добирался сюда».

⚠⚠ **Структурное поле — развилка проверки, а не её предмет.** Написать
`assert got.vars['invite_ok'] in ('yes', 'no', 'fixed')` нельзя: слово выбирает
модель, и тест краснел бы от её оговорки, а не от поломки. Утверждать можно
**связь, которую держит движок**: пришло `fixed` — шаг правки обязан быть на
маршруте. Вердикт при этом стоит в `if`, а не в `assert`.

## ⚠⚠ Трассу читаем ручкой, а не из базы

Соблазн сходить в `agent_workflow_trace` напрямую велик — и он приводит к
`RuntimeError: Event loop is closed`. Пул `mysql_` модульный и привязан к циклу
событий, в котором создан, а `pytest-asyncio` даёт каждому тесту **свой** цикл:
второй тест получает пул от первого и падает на освобождении соединения.

Ручка `/workflow_trace/run/…` отдаёт то же самое и живёт в клиенте теста. Заодно
сюита ходит по HTTP целиком, как и остальная.

⚠ Свой прогон ищем по `prompt_user` среди свежих: `session_uuid` ручка списка не
отдаёт. Работает это потому, что вопрос **уникален** — метку ему даёт `ask`
(см. `_unique`), — а не потому, что тесты идут по одному.

## ⚠⚠ Прогонов может идти сколько угодно разом

Подменный сервис держит сценарий **по ячейке на прогон**, ключ — `session_uuid` в
заголовке `X-Fake-Session`. Прежде сценарий был один на сервис, и два `pytest`
затирали друг другу правила: второй зеленел на чужих ответах либо краснел
непонятно. Теперь их можно гонять параллельно — проверено двумя одновременными
прогонами.

⚠ Ключ не заводим свой: `session_uuid` уже уникален, уже уходит в `/chat/ask` и
уже идёт до самой модели, включая подпрогоны. Второй ключ на то же значило бы
держать их в согласии.

## ⚠ Что здесь сбой, а что шум

Разово падает инфраструктура, а не код: локальный Qdrant отдавал `ReadTimeout` на
одном поиске из трёх подряд, и прогон валился с 500. Поэтому вызов повторяется
(`LLM_ATTEMPTS`) и показывает в `attempts`, со скольких попыток вышло. Красное
после повторов — повод смотреть, а не перезапускать.

## ⚠ Мусор, который остаётся

Собеседник теста заводится один раз и **не удаляется**: ручки удаления у соседа
нет, а факты разговора уже легли в Qdrant под его ключ. Это нарочно — свой
собеседник не даёт тестам писать факты в документ живого `dating_person`.
"""

import asyncio
import json
import os
import pathlib
import sys
import time
import uuid
from dataclasses import dataclass, field

import httpx
import pytest

from tests_llm.mark import TEST_GIRL_ID, TEST_MARK

from tests.constants import TEST_AUTH

BASE_URL = os.getenv('BASE_URL', '').strip().rstrip('/') or 'http://localhost:8011'

# Сколько ждём ответа агента **на стороне теста**. ⚠ Не запас «на всякий случай»:
# обычная реплика идёт 11–12 секунд, а заход, где модель заводит факты девушки с
# нуля, — минуту.
#
# ⚠⚠ **Это не таймаут движка.** У соседа свой, 60 секунд, и поднимается он
# переменной `chat_timeout` — но только там, где она объявлена входящей (у
# `dating_talk`). Почтовым workflow её слать нельзя: незаявленную переменную
# ручка отвергает `400`. Им хватает своих шестидесяти — замерено, укладываются в
# 6–8 секунд.
LLM_TIMEOUT = float(os.getenv('LLM_TIMEOUT', '220'))

# Сколько раз повторить вызов, сорвавшийся не по вине кода. Два, а не один: один
# разовый `ReadTimeout` от Qdrant валит прогон целиком, и без повтора половина
# запусков красная без причины.
LLM_ATTEMPTS = int(os.getenv('LLM_ATTEMPTS', '2'))

# Сайт, чьими агентами идут почтовые тесты.
#
# ⚠⚠ **Агент почты — свой у каждого сайта знакомств**: `invite_ladadate`,
# `mail_write_goldenbride`. Так заведено в DatingAi (`mail_agent.py`): у агента
# один workflow, а метка сайта обязательна при заведении. Значит и тест обязан
# назвать сайт — «агента инвайтов» вообще не существует.
#
# ⚠ Нет агента с таким именем — тест **пропускается**, а не падает: на чистой
# установке почтовых агентов нет вовсе, их заводит первое обращение из DatingAi.
LLM_SITE = os.getenv('LLM_SITE', 'ladadate').strip()

# Ключ девушки: тестовый, а не рабочий. Владелец — `mark.py`, здесь только
# возможность переопределить переменной окружения.
LLM_GIRL_ID = os.getenv('LLM_GIRL_ID', TEST_GIRL_ID)

LLM_COMPANION_NAME = 'test_llm_companion'
LLM_COMPANION_TITLE = 'Gerard'


@dataclass
class Talk:
    """Один прогон workflow: что вернулось и каким путём к этому пришли."""

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
    # Что шаг вернул. ⚠ Нужно там, где решение принято **по результату шага**, а
    # имя его переменной знать нельзя: у поиска фактов оно несёт номер шага
    # (`qdrant_fact_search_1529_result_str`), а номера у каждой базы свои.
    outputs: dict = field(default_factory=dict)
    # Все отрисовки шага по порядку — там, где шаг проходится не раз.
    #
    # ⚠⚠ **Первой отрисовки хватает не всегда, и цикл инвайтов это доказывает.**
    # Он гонит один и тот же шаг по разу на реплику, и вся его суть в том, что
    # вторая реплика **видит первую**: в промпт подставляется `invite_done`.
    # Смотри тест только на первую — и проверял бы он ровно тот заход, где
    # накопленного ещё нет.
    prompts_each: dict = field(default_factory=dict)
    outputs_each: dict = field(default_factory=dict)
    # Сколько раз с шага ушли, **не выполнив** его: сработал `transitions_before`.
    #
    # ⚠⚠ Такой проход движок пишет в трассу наравне с выполненным, и без этого
    # счёта «шаг был на маршруте» и «шаг отработал» неразличимы. У развилки они
    # значат прямо противоположное: шаг ветки чата попадает в трассу и тогда,
    # когда поток ушёл с него в ветку письма.
    jumps: dict = field(default_factory=dict)

    def went_through(self, step: str) -> bool:
        """Встретился ли шаг на маршруте — в главном прогоне или в подпрогоне.

        ⚠ **Это не «отработал».** Шаг, покинутый `transitions_before`, тоже
        встретился. Про работу спрашивают `ran`.
        """
        return step in self.route_all

    def ran(self, step: str) -> bool:
        """Отработал ли шаг вправду — хоть раз, не считая уходов с него.

        ⚠⚠ Единственный честный способ спросить «какой веткой пошло». Развилка
        `dating_talk` уводит с шага чата `transitions_before`, и `went_through`
        на нём истинен при любой ветке.
        """
        return self.times_ran(step) > 0

    def times(self, step: str) -> int:
        """Сколько раз шаг встретился на маршруте — вместе с уходами с него.

        ⚠ Нужно там, где повтор и есть предмет проверки: цикл инвайтов гоняет
        одни и те же шаги по разу на реплику, и «был ли шаг» на такой вопрос не
        отвечает.
        """
        return self.route_all.count(step)

    def times_ran(self, step: str) -> int:
        """Сколько раз шаг **отработал**: проходы минус уходы `before`."""
        return self.times(step) - int(self.jumps.get(step) or 0)

    def prompt_of(self, step: str) -> str:
        """Отрисованный промпт шага. Пусто — шага не было или промпта у него нет."""
        return str(self.prompts.get(step) or '')

    def output_of(self, step: str) -> str:
        """Что вернул шаг. Пусто — шага не было либо он вернул пустоту.

        ⚠ Эти два случая **не различаются**, и различать их здесь незачем: оба
        значат «на результат этого шага рассчитывать нельзя». Кто ходил, а кто
        нет — отвечает `went_through`.
        """
        return str(self.outputs.get(step) or '')

    def prompt_each(self, step: str) -> tuple:
        """Промпты шага по порядку прохождений: первый, второй, третий."""
        return tuple(self.prompts_each.get(step) or ())

    def output_each(self, step: str) -> tuple:
        """Выводы шага по порядку прохождений."""
        return tuple(self.outputs_each.get(step) or ())

    def __str__(self) -> str:
        # ⚠ Уходы показываем отдельной строкой: в маршруте они неотличимы от
        # работы, и упавшая проверка ветки без них читается как «шаг был, а
        # проверка врёт».
        left = ', '.join(f'{name} ×{qty}' for name, qty in self.jumps.items())

        return (f'\nответ: {self.text!r}\n'
                f'маршрут: {" → ".join(self.route) or "пусто"}\n'
                f'подпрогоны: {" → ".join(self.route_all) or "пусто"}\n'
                f'ушли не выполнив: {left or "нет"}\n'
                f'попыток: {self.attempts}, статус: {self.status}, сессия: {self.session}')


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
async def companion_id(client) -> int:
    """Свой собеседник тестов: заводится один раз, дальше переиспользуется.

    ⚠ Не `dating_person` (тот, которым ходит боевой код): факты разговора ложатся
    в Qdrant под ключ собеседника, и тесты засоряли бы живой документ.

    ⚠ Почтовым workflow собеседник не нужен по смыслу — шаблон пишется на весь
    пул, — но поле `companion_id` у ручки обязательное, и ссылаться ему нужно на
    честную строку. Тот же приём, что в DatingAi (`MAIL_AGENT_COMPANION_ID`).
    """
    if 'companion' in _FOUND:
        return _FOUND['companion']

    async def _find() -> int:
        answer = await client.get('/companion/list')

        if answer.status_code != 200:
            return 0

        for one in (answer.json().get('result') or []):
            # ⚠ Ищем по `unique_id`: столбец звался `name`, но всегда был
            # ключом записи, а не именем человека — имя лежит в `title`
            # (`…_companion_unique_id`). Поле **запроса** осталось `name`: его
            # шлют соседние проекты, и менять договор ради ясности внутри
            # незачем.
            if str(one.get('unique_id')) == LLM_COMPANION_NAME:
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
async def agent_of(client):
    """Номер агента по системному имени. Нет такого — тест пропускается.

    ⚠⚠ **Пропуск, а не падение, и это решение.** Агенты почты заводит первое
    обращение из DatingAi (`mail_agent._agent_id`), и на установке, где рассылкой
    не занимались, их нет. Красный тест сказал бы «сломано», хотя ломать нечего:
    занятие просто не заводили.

    ⚠ Агента ищем **по имени**, а не по номеру: номер разъезжается между
    установками (локально 1663, на проде свой), и прибитая константа сломала бы
    тесты на первом же переносе базы.
    """

    async def _agent_of(name: str) -> int:
        name = str(name).strip()

        if name in _FOUND:
            return _FOUND[name]

        answer = await client.get(f'/agent/name/{name}')

        if answer.status_code == 404:
            pytest.skip(f'агента «{name}» нет в этой базе — занятие тут не заводили')

        if answer.status_code != 200:
            pytest.fail(f'агент «{name}» не читается ({answer.status_code}):'
                        f' {answer.text[:200]}')

        _FOUND[name] = int((answer.json().get('result') or {}).get('id') or 0)

        return _FOUND[name]

    return _agent_of


@pytest.fixture
def llm_plan():
    """Ответы модели по умолчанию — заготовка **этого** workflow.

    ⚠⚠ Здесь пусто нарочно: наполняет её `conftest.py` своей папки, переопределив
    фикстуру. Так каждый тест папки получает рабочий сценарий даром, а тот, кому
    нужно иное, перебивает его через `llm_answers`.

    Без этого каждый тест начинался бы с десяти строк «чем отвечает модель» —
    то есть с устройства workflow вместо своего предмета.
    """
    return []


@pytest.fixture
async def ask(client, agent_of, companion_id, llm_answers, llm_plan):
    """Позвать агента по имени и получить ответ вместе с маршрутом.

    Args:
        agent: системное имя агента у соседа (`invite_ladadate`).
        question: повод запустить workflow. ⚠ Уходит в `prompt_user`, и по нему
            же тест потом находит свой прогон — поэтому к нему приписывается
            случайный хвост.
        variables: переменные вызова. ⚠ Только объявленные входящими у этого
            workflow: незаявленную ручка отвергает `400` (`chat.py`).

    Returns:
        Talk: ответ, маршрут, промпты и выводы шагов.

    ⚠ Каждый вызов — **своя сессия**: иначе история одного теста доезжает до
    следующего, и маршрут зависит от порядка запуска.
    """

    async def _ask(agent: str, question: str, variables: dict = None) -> Talk:
        # ⚠⚠ Заготовка папки — **запасной вариант, а не указ**. Тест, которому
        # нужен иной сценарий, зовёт `llm_answers` сам, и его выбор обязан
        # победить.
        #
        # Пока здесь стояло безусловное `await llm_answers(llm_plan)`, победа
        # была за заготовкой: свой сценарий теста затирался на каждом вызове
        # `ask`. Оттого фикстуры брака (`PLAN_LANG_BAD`, `PLAN_SAME`,
        # `PLAN_JUDGE_FIXES`, …) не звал **ни один** тест — они не могли
        # сработать, и путь брака оставался непроверенным. При этом в докстринге
        # `llm_plan` способ был описан как рабочий.
        if llm_plan and 'rules' not in LLM_HELD:
            await llm_answers(llm_plan)


        agent_id = await agent_of(agent)
        asked = _unique(question)
        session = str(uuid.uuid4())

        # ⚠⚠ Сценарий кладём **под ключ этого вызова**: у подменного сервиса ячейка
        # на прогон, и ключом служит `session_uuid`. Без этого правила лежали бы в
        # общей ячейке — и два pytest разом затирали бы друг другу ответы.
        await _plan_put(llm_answers, session)

        payload = {'question': asked, 'agent_id': agent_id,
                   'companion_id': companion_id, 'session_uuid': session,
                   'variables': dict(variables or {})}
        last = ''

        for attempt in range(1, LLM_ATTEMPTS + 1):
            try:
                answer = await client.post('/chat/ask', json=payload)
            except httpx.HTTPError as e:
                last = f'связь: {e}'
                await asyncio.sleep(2)
                continue

            if answer.status_code == 200:
                got = await _trace_read(client, agent_id, asked)
                got.text = str(answer.json().get('result') or '')
                got.session = session
                got.attempts = attempt

                return got

            # ⚠ Отказ про переменные — не повод повторять: он не про удачу, а про
            # договор, и вторая попытка даст тот же `400`. Показываем сразу.
            if answer.status_code == 400:
                pytest.fail(f'ручка отвергла вызов: {answer.text[:300]}')

            last = f'{answer.status_code}: {answer.text[:300]}'
            # ⚠ Новая сессия на повтор: прошлая уже несёт оборванный прогон, и
            # маршрут смешался бы из двух попыток.
            session = str(uuid.uuid4())
            payload['session_uuid'] = session
            # ⚠⚠ И сценарий — под новый ключ. Забудь мы это, повтор пошёл бы к
            # пустой ячейке и ответил бы пустотой: «модель решила иначе» вместо
            # понятного отказа.
            await _plan_put(llm_answers, session)
            await asyncio.sleep(2)

        broken = await _trace_read(client, agent_id, asked)
        pytest.fail(f'агент «{agent}» не ответил за {LLM_ATTEMPTS} попыт(ки).'
                    f' Последнее: {last}\n'
                    f'маршрут оборванного прогона:'
                    f' {" → ".join(broken.route) or "пусто"}')

    return _ask


# ── Подменная модель ────────────────────────────────────────────────────────

# Адрес подменного сервиса **со стороны теста**. ⚠ Не тот же, что у сервера: тот
# ходит из контейнера (`host.docker.internal`), а тест — с машины.
LLM_FAKE_PORT = int(os.getenv('LLM_FAKE_PORT', '8099'))
LLM_FAKE_URL = os.getenv('LLM_FAKE_URL', f'http://127.0.0.1:{LLM_FAKE_PORT}')

# Сколько десятых долей секунды ждём старта сервиса, прежде чем сдаться.
LLM_FAKE_WAIT = 50

# Заголовок, которым прогон называет себя подменному сервису. ⚠ То же имя, что в
# `ai_llm_fake.FAKE_SESSION_HEADER` и в провайдере: разойдись они — правила лягут в
# одну ячейку, ответы придут из другой, и тест покраснеет на пустых без причины.
LLM_FAKE_SESSION_HEADER = 'X-Fake-Session'

# Сценарий, который тест задал, и ключ, под которым он последний раз лёг.
#
# ⚠⚠ Нужен посредник, потому что порядок обратный: тест пишет ответы **до** того,
# как появился прогон, а ключ (`session_uuid`) заводит `ask` в момент вызова.
# Здесь сценарий лежит между этими двумя мгновениями.
#
# ⚠ Обычный словарь, а не фикстура: у сессионных async-фикстур в `pytest-asyncio`
# 1.x своя беда с циклом событий (см. `_FOUND` ниже).
LLM_HELD: dict = {}

# Идти ли к живой модели. ⚠⚠ По умолчанию **нет**: модель одна на тесты и на
# прод, и прогон сюиты — отнятые у людей ответы. Живой прогон включают руками
# (`LLM_LIVE=1`) и на сервере без `LLM_FAKE`.
LLM_LIVE = str(os.getenv('LLM_LIVE', '')).strip().lower() \
    not in ('', '0', 'false', 'no', 'off')


@pytest.fixture(scope='session', autouse=True)
def llm_fake_serve():
    """Поднять подменный сервис, если его ещё нет, — и погасить за собой.

    ## Обычно поднимать нечего: он живёт контейнером

    `docker compose --profile fake up -d llm_fake` — и дальше `restart: always`
    возвращает его после перезагрузки. Тогда эта фикстура видит живой сервис и не
    делает ничего.

    ⚠⚠ **Так и задумано: гасить его между прогонами незачем.** Прогон за прогоном
    поднимать и убивать процесс — это доли секунды каждый раз плюс своя порода
    отказов (порт ещё занят прошлым, старт не успел). Постоянный сервис снимает
    вопрос целиком, а тесты и так чистят за собой заготовки (`llm_answers`).

    ## ⚠ Запасной путь остаётся, и он нужен

    Контейнер погашен, машина чужая, CI без compose — тогда фикстура поднимает
    процесс сама. Требовать «сначала запусти сервис» значило бы оставить прогон
    зависящим от того, вспомнил ли об этом человек: забытый сервис — это не
    красное, а **падение всех** тестов подряд с непонятной причиной.

    ⚠ Своё гасим, чужое нет: поднятое не нами может оказаться тем самым
    контейнером, и убить его значило бы сломать следующий прогон.

    ⚠⚠ Двух прогонов разом сервис не держит: заготовки у него одни на всех, и
    второй pytest затрёт сценарий первого. Это плата за постоянный сервис, и
    видна она сразу — тесты покраснеют на чужих ответах, а не соврут.

    ⚠ При `LLM_LIVE=1` не делаем ничего: отвечает живая модель.
    """
    import subprocess

    if LLM_LIVE or _fake_alive():
        yield

        return

    started = subprocess.Popen(
        [sys.executable, '-m', 'ai.ai_llm_fake', '--port', str(LLM_FAKE_PORT)],
        cwd=str(pathlib.Path(__file__).resolve().parents[1]),
        env={**os.environ, 'PYTHONPATH': 'py_modules'},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ⚠ Ждём готовности, а не спим наугад: на холодной машине старт занимает
    # доли секунды, а прибитая пауза либо тормозит прогон, либо не хватает.
    for _ in range(LLM_FAKE_WAIT):
        if _fake_alive():
            break

        time.sleep(0.1)
    else:
        started.kill()
        pytest.fail(f'подменная модель не поднялась на {LLM_FAKE_URL}')

    yield

    started.kill()


@pytest.fixture
async def llm_answers():
    """Задать ответы модели — и прогнать цепочку целиком.

    ⚠⚠ Сценарий нужен **только шагам, которые спрашивают модель** (`llm_to_json`,
    `return_response_llm`). Инструменты, подстановка переменных и переходы
    работают по-настоящему — их подменять нечем и незачем: именно они и есть
    предмет проверки. Подмена закрывает ровно ту часть, что непредсказуема.

    ⚠ Шаги подпрогонов тоже спрашивают модель, и правило нужно и им: цепочка
    `dating_talk` зовёт `companion_fact_extract`, а тот — свою модель.

    Тест пишет, что «ответит» модель на каждом таком шаге, а потом смотрит, куда
    от этого пошёл поток:

        await llm_answers([
            ('краткая выдержка истории', {'prompt_user_ignore': '0', …}),
            ('Ответ девушки собеседнику', {'girl_response': 'hi'}),
        ])

    Первый элемент пары — **кусок промпта**, по которому шаг узнаётся. Имени шага
    в запросе к модели нет вовсе, движок его не шлёт; зато промпт у каждого шага
    свой, и куска из него довольно.

    ⚠ При `LLM_LIVE=1` фикстура **ничего не делает**: отвечает живая модель, и
    сценарий ей не указ. Тесты маршрута при этом остаются годными — они смотрят
    на трассу, а не на слова.

    ⚠⚠ Сервис не поднят — тест **падает с объяснением**, а не идёт к живой
    модели молча. Иначе «быстрый прогон без расхода» однажды оказался бы
    обычным, только никто бы не заметил.
    """
    if LLM_LIVE:
        async def _skip(_rules, default=None):
            return None

        yield _skip

        return

    async with httpx.AsyncClient(base_url=LLM_FAKE_URL, timeout=10) as fake:
        async def _put(rules, default=None, session: str = ''):
            # ⚠⚠ Сценарий **запоминается**, а кладётся под ключ прогона. Ключ —
            # `session_uuid`, и заводит его `ask` в момент вызова: до него теста
            # ещё нет, кому принадлежат правила. Поэтому тест пишет «вот ответы», а
            # раскладывает их `ask` — тем же ключом, каким пойдёт в движок.
            if not session:
                LLM_HELD['rules'] = rules
                LLM_HELD['default'] = default

            body = {'rules': [{'when': when, 'answer': answer}
                              for when, answer in (rules or [])],
                    'default': default}
            try:
                got = await fake.post('/fixtures', json=body,
                                      headers={LLM_FAKE_SESSION_HEADER: session}
                                      if session else None)
            except httpx.HTTPError as e:
                pytest.fail(
                    f'подменная модель недоступна ({LLM_FAKE_URL}): {e}.\n'
                    f'Подними её: docker compose --profile fake up -d llm_fake\n'
                    f'Живой прогон — LLM_LIVE=1 и сервер без LLM_FAKE.')

            if got.status_code != 200:
                pytest.fail(f'сценарий не принят ({got.status_code}): {got.text[:200]}')

            answered = got.json()

            # ⚠⚠ Сервис возвращает полученный ключ, и мы его сверяем. Потеряйся
            # заголовок по дороге — правила легли бы в общую ячейку, а движок искал
            # бы в своей: тест покраснел бы на пустых ответах, не сказав почему.
            if session and str(answered.get('session') or '') != session:
                pytest.fail(
                    f'сервис не увидел ключ прогона: ждали {session}, '
                    f'получили {answered.get("session")!r}. Сценарий лёг не туда, '
                    f'и ответы придут чужие.')

            return answered

        yield _put

        # ⚠ Сценарий снимаем за собой — из **своей** ячейки: `ask` кладёт правила
        # под ключ каждого вызова, и последний из них помнит `LLM_HELD`.
        last = str(LLM_HELD.get('session') or '')
        try:
            await fake.delete('/fixtures',
                              headers={LLM_FAKE_SESSION_HEADER: last}
                              if last else None)
        except httpx.HTTPError:
            pass

        LLM_HELD.clear()


@pytest.fixture
async def llm_calls():
    """Чем звали модель за этот тест: список промптов по порядку.

    ⚠ Нужен, когда правило не совпало: по журналу видно **настоящий** промпт, и
    примету можно поправить, не гадая.
    """
    async def _calls() -> list:
        if LLM_LIVE:
            return []

        # ⚠ Журнал спрашиваем **у своей ячейки**: у сервиса их по одной на прогон,
        # и без ключа он отдал бы общую — пустую, ведь вызовы шли под ключом.
        last = str(LLM_HELD.get('session') or '')

        async with httpx.AsyncClient(base_url=LLM_FAKE_URL, timeout=10) as fake:
            got = await fake.get('/calls',
                                 headers={LLM_FAKE_SESSION_HEADER: last}
                                 if last else None)

            return (got.json().get('calls') or []) if got.status_code == 200 else []

    return _calls


# ── Приватное ────────────────────────────────────────────────────────────────


async def _plan_put(llm_answers, session: str) -> None:
    """Переложить запомненный сценарий под ключ этого прогона.

    ⚠ Сценария нет — не делаем ничего: тест про ответы модели ничего не
    утверждает, и пустые правила заняли бы ячейку впустую.

    ⚠⚠ Живой прогон (`LLM_LIVE=1`) сюда тоже приходит, и `llm_answers` там —
    пустышка: она молча вернёт `None`, и ключ никуда не поедет. Так и надо —
    живой модели сценарий не указ.
    """
    if 'rules' not in LLM_HELD:
        return

    await llm_answers(LLM_HELD.get('rules'), LLM_HELD.get('default'),
                      session=session)
    LLM_HELD['session'] = session

# Что найдено один раз — номера агентов и собеседника. ⚠ Обычный словарь, а не
# сессионная фикстура: в `pytest-asyncio` 1.x сессионная async-фикстура живёт в
# цикле событий **первого** теста и со второго падает «Event loop is closed».
_FOUND = {}


def _unique(question: str) -> str:
    """Вопрос с меткой прогона: по нему тест находит свою трассу.

    ⚠⚠ **Без метки тесты путают прогоны между собой.** Трасса ищется по тексту
    вопроса среди свежих, а почтовые workflow зовутся одной и той же фразой
    («Напиши шаблон первой реплики в чат») — два теста подряд нашли бы один и тот
    же прогон, и второй проверял бы чужой маршрут.

    ⚠ Метка помечена приставкой тестов — если она вдруг доедет до промпта
    модели, по журналу будет видно, чья она.

    ⚠⚠ **Хвостовой `strip()` обязателен.** Вопрос бывает пустым — письма первыми
    зовут именно так, — и без него выходило `' [pytest:abcd]'` с ведущим
    пробелом. Ручка вопрос обрезает (`chat.py`), а трассу тест ищет по
    необрезанному тексту: прогон шёл, ответ приходил, а найти его тест уже не
    мог — и падал «до промпта не доехало», хотя доехало всё.
    """
    return f'{str(question).strip()} [{TEST_MARK}:{uuid.uuid4().hex[:8]}]'.strip()


def _walk(run: dict, got: Talk, main: list, every: list,
          top: bool = True) -> None:
    """Обходит дерево прогона, наполняя `got`: шаги родителя и подпрогонов.

    ⚠ Списки маршрута идут отдельными доводами, а не полями `got`: у готового
    `Talk` они кортежи (менять его снаружи незачем), а обходу нужен растущий
    список. Замораживает их `_trace_read` — там, где обход закончен.
    """
    for step in run.get('steps') or []:
        title = str(step.get('step_title') or '')

        if title:
            every.append(title)

            if top:
                main.append(title)

            # ⚠⚠ Уход `transitions_before` — **не работа шага**, и дальше он не
            # учитывается ни промптом, ни выводом. Промпт у такого прохода в
            # трассе есть (метаданные отрисовываются до проверки переходов), но в
            # модель он не уезжал, а `prompts` обещает ровно обратное — «то, что
            # вправду ушло в модель». Запиши его сюда, и проверка входа читала бы
            # текст, которого модель не видела.
            if _jumped_before(step):
                got.jumps[title] = int(got.jumps.get(title) or 0) + 1
            else:
                prompt = _rendered_prompt(step)
                output = str(step.get('output') or '')

                got.prompts_each.setdefault(title, []).append(prompt)
                got.outputs_each.setdefault(title, []).append(output)

                # ⚠ Берём **первую** отрисовку шага: повтор после неудачной
                # проверки идёт с тем же входом, а последняя запись затёрла бы
                # то, с чего разговор начался. Вывод — по тому же правилу и ради
                # того же. Все прохождения целиком лежат рядом (`*_each`).
                if title not in got.prompts:
                    got.prompts[title] = prompt
                    got.outputs[title] = output

        changed = step.get('variables_changed')
        try:
            got.vars.update(json.loads(changed) if isinstance(changed, str)
                            else (changed or {}))
        except (TypeError, ValueError):
            pass

    for child in run.get('children') or []:
        _walk(child, got, main, every, top=False)


def _jumped_before(step: dict) -> bool:
    """Ушли ли с шага, не выполнив его: сработал `transitions_before`.

    ⚠⚠ Метка — `phase` у перехода, и она единственная надёжная. «Пустой вывод»
    приметой не годится: шаг-развилка без промпта возвращает пустоту и тогда,
    когда честно отработал, а подпрогон наоборот кладёт вывод даже без модели.

    ⚠ Поле приходит то строкой JSON, то разобранным словарём — как и
    `metadata_rendered`, и по той же причине. Негодный JSON читается как «не
    ушли»: шаг в трассе есть, а чем он кончился, мы не знаем — и считать его
    пропущенным значило бы прятать работу, которая, возможно, была.
    """
    got = step.get('transition')

    if isinstance(got, str):
        try:
            got = json.loads(got or '{}')
        except (TypeError, ValueError):
            return False

    return str((got or {}).get('phase') or '') == 'before'


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


async def _trace_read(client, agent: int, question: str) -> Talk:
    """Свежий прогон по тексту вопроса — маршрут, промпты и решения шагов.

    Returns:
        Talk: без `text`, `session` и `attempts` — их знает вызывающий, а не
        трасса. Прогон не нашёлся — тот же `Talk`, пустой: «маршрута нет» и
        «маршрут не прочитался» для проверок значат одно.

    ⚠ **Отдаёт готовый `Talk`, а не набор кусков.** Прежде возвращался кортеж из
    восьми значений, и вызывающий раскладывал их по полям сам: любое новое поле
    приходилось вписывать в четыре места, а перепутанный порядок распаковки
    молча менял местами промпты и выводы.

    ⚠ Ручка списка отдаёт только верхний уровень (`depth = 0`) и сортирует по
    убыванию номера — первый совпавший и есть наш последний прогон. Шаги и
    подпрогоны приходят уже ручкой подробностей.
    """
    got = Talk()

    answer = await client.get('/workflow_trace/run/list',
                              params={'agent_id': agent, 'limit': 30})

    if answer.status_code != 200:
        return got

    mine = next((one for one in (answer.json().get('result') or [])
                 if str(one.get('prompt_user') or '') == str(question)), None)

    if not mine:
        return got

    got.status = str(mine.get('status') or '')

    full = await client.get(f'/workflow_trace/run/{mine.get("run_uuid")}')

    if full.status_code != 200:
        return got

    root = full.json().get('result') or {}
    main, every = [], []
    _walk(root, got, main, every)

    got.status = str(root.get('status') or got.status)
    got.route = tuple(main)
    got.route_all = tuple(every)

    return got


def _fake_alive() -> bool:
    """Отвечает ли подменный сервис. ⚠ Синхронно: зовут из сессионной фикстуры,
    а она к циклу событий теста не привязана."""
    try:
        return httpx.get(f'{LLM_FAKE_URL}/models', timeout=1).status_code == 200
    except httpx.HTTPError:
        return False
