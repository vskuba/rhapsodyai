"""Общая оснастка LLM-тестов: живой вызов агента и чтение его маршрута.

## ⚠⚠ Зачем отдельная папка, а не группа в `tests/`

Сюита `tests/` намеренно не зовёт модель: «LLM для этого не нужна, а лишний прогон
workflow стоил бы минуту и токены» (`tests/test_agent_variable.py`). Но ход
разговора без модели не проверить — развилка «о чём сейчас речь» это шаг
`llm_to_json`, и решает его только она.

## ⚠⚠ Сами эти тесты не запускаются. Никогда

Папки **нет в `testpaths`**, и это не забывчивость: **модель одна на тесты и на
прод**. Та же нода, что отвечает здесь на `pytest`, отвечает живым людям на сайте
знакомств; очередь у неё общая, и прогон сюиты — это отнятые у них ответы.

Запускает их человек, явным путём и по своему решению:

    .venv/bin/python3 -m pytest tests_llm/dating_invite_write -q

⚠ Правишь workflow — **предложи прогон и дождись ответа**. Предложение входит в
работу; запуск без ответа — нет. Подробности — `.claude/docs/testing_llm.md`.

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
отдаёт. Тесты идут **по одному** (без `xdist`), поэтому «самый свежий с таким
вопросом» — это наш. Отсюда же требование к вопросу: он обязан быть уникальным,
и уникальность ему даёт `ask` (см. `_unique`).

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
async def ask(client, agent_of, companion_id):
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
        agent_id = await agent_of(agent)
        asked = _unique(question)
        session = str(uuid.uuid4())
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
            await asyncio.sleep(2)

        broken = await _trace_read(client, agent_id, asked)
        pytest.fail(f'агент «{agent}» не ответил за {LLM_ATTEMPTS} попыт(ки).'
                    f' Последнее: {last}\n'
                    f'маршрут оборванного прогона:'
                    f' {" → ".join(broken.route) or "пусто"}')

    return _ask


# ── Приватное ────────────────────────────────────────────────────────────────

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
    """
    return f'{str(question).strip()} [{TEST_MARK}:{uuid.uuid4().hex[:8]}]'


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
