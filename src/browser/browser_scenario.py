"""Сценарий — последовательность действий над страницей и её проверка.

Здесь только схема, подстановка переменных и маскирование секретов. Ни Playwright,
ни MySQL: файл читают обе стороны — контейнер, который сценарий выполняет
(`browser_scenario_run`), и `uvicorn`, который его хранит и проверяет на
сохранении (`src/uvicorn/routers/browser/browser_scenario.py`). Две копии одной
схемы разошлись бы на первой правке.

Сценарий детерминирован: ни один шаг не «ищет похожее». Селектор обязан совпасть
ровно с одним элементом (`page.locator` в строгом режиме), ожидание задано явно,
а таймаут — у каждого шага свой. Сценарий, который сработал случайно, хуже
упавшего: упавший заводит задачу на переписывание, случайный молча врёт.

**Пароль в сценарии не хранится.** Значения приходят на прогон: `variables`
попадают в журнал, `secrets` — нет, они замазываются в тексте ошибок, а сам шаг
журналируется до подстановки, то есть как `{{password}}`.
"""

import re

from pydantic import BaseModel, Field, field_validator, model_validator

# Действие → поля, без которых оно бессмысленно. Список закрытый: чего здесь нет,
# того сценарий сделать не может, и автор сценария (LLM на этапе 4) увидит отказ
# схемы, а не молча пропущенный шаг.
BROWSER_SCENARIO_ACTIONS = {
    'goto':        ('url',),
    'click':       ('selector',),
    'fill':        ('selector', 'value'),
    'type':        ('selector', 'value'),
    'press':       ('key',),
    'select':      ('selector', 'value'),
    'wait_for':    ('selector',),
    'wait_url':    ('url',),
    'wait_ms':     ('value',),
    'scroll':      ('value',),
    'extract':     ('selector', 'name'),
    'assert_text': ('selector', 'value'),
}

# 10 с на шаг: столько ждёт Playwright появления элемента, прежде чем признать,
# что вёрстка изменилась. Больше — и упавший сценарий висит минутами вместо того,
# чтобы быстро завести задачу на починку.
BROWSER_SCENARIO_STEP_TIMEOUT_MS = 10000

BROWSER_SCENARIO_STEP_LIMIT = 100
BROWSER_SCENARIO_MASK = '***'

# Имена переменных — только буквы, цифры и подчёркивание: подстановка идёт в
# селекторы и URL, где фигурные скобки встречаются и сами по себе (CSS, JSON).
BROWSER_SCENARIO_VAR_RE = re.compile(r'\{\{\s*([A-Za-z0-9_]+)\s*\}\}')

# Секрет короче этого не замазывается: затирать в тексте каждую «1» или «ok»
# вреднее, чем оставить — от такой маски журнал перестаёт читаться.
BROWSER_SCENARIO_MASK_MIN_LEN = 4

# `value: "@src"` у `extract` — снять атрибут, а не текст. Иначе адрес картинки
# не достать: у `<img>` текста нет, и шаг вернул бы пустую строку.
BROWSER_SCENARIO_ATTR_MARK = '@'


class BrowserScenarioStep(BaseModel):
    """Один шаг. Поля общие на все действия, обязательные — по таблице выше."""

    action: str
    selector: str = Field('', max_length=500, description='CSS или text=… — ровно один элемент')
    url: str = Field('', max_length=1000)
    value: str = Field('', max_length=2000,
                       description='Текст, вариант списка, мс, пиксели; у extract «@src» — атрибут')
    key: str = Field('', max_length=50, description='Enter, Control+a')
    name: str = Field('', max_length=50, description='Под каким именем сложить результат extract')
    timeout_ms: int = Field(BROWSER_SCENARIO_STEP_TIMEOUT_MS, ge=100, le=120000)
    optional: bool = Field(False, description='Шаг может не сработать — прогон продолжится')

    @field_validator('action')
    @classmethod
    def _action_check(cls, value: str) -> str:
        if value not in BROWSER_SCENARIO_ACTIONS:
            raise ValueError(f'action: ожидается одно из {", ".join(sorted(BROWSER_SCENARIO_ACTIONS))}')
        return value

    @model_validator(mode='after')
    def _fields_check(self):
        for field in BROWSER_SCENARIO_ACTIONS.get(self.action, ()):
            if not str(getattr(self, field, '')).strip():
                raise ValueError(f'{self.action}: не заполнено поле {field}')
        if self.action in ('wait_ms', 'scroll') and not self.value.strip().lstrip('-').isdigit():
            raise ValueError(f'{self.action}: value должно быть числом')
        return self


class BrowserScenario(BaseModel):
    """Сценарий целиком. `goal` — не украшение: по нему агент перепишет шаги,
    когда вёрстка сайта изменится, а цель останется прежней."""

    name: str = Field(..., min_length=1, max_length=100)
    goal: str = Field('', max_length=255)
    steps: list[BrowserScenarioStep] = Field(..., min_length=1, max_length=BROWSER_SCENARIO_STEP_LIMIT)


def browser_scenario_variables_used(scenario: BrowserScenario) -> list[str]:
    """Имена всех `{{переменных}}` сценария в порядке появления, без повторов."""
    names: list[str] = []

    for step in scenario.steps:
        for text in (step.selector, step.url, step.value, step.key):
            for name in BROWSER_SCENARIO_VAR_RE.findall(text):
                if name not in names:
                    names.append(name)

    return names


def browser_scenario_variables_missing(scenario: BrowserScenario, values: dict) -> list[str]:
    """Чего не хватает для прогона.

    Проверяется до первого шага, а не по ходу: иначе сценарий входа успел бы
    открыть форму и только на пароле сообщить, что его не передали.
    """
    return [name for name in browser_scenario_variables_used(scenario) if name not in values]


def browser_scenario_render(text: str, values: dict) -> str:
    """Подставляет значения. Неизвестное имя остаётся как есть — про него уже
    сказал `browser_scenario_variables_missing`, и второй раз падать незачем."""
    if not text:
        return text

    return BROWSER_SCENARIO_VAR_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


def browser_scenario_mask(text: str, secrets: dict) -> str:
    """Замазывает значения секретов в тексте — журнал и ошибки идут через это.

    Сообщения Playwright цитируют то, что вводили: `fill("hunter2")` в тексте
    таймаута сохранил бы пароль в БД навсегда.
    """
    if not text:
        return text

    for value in secrets.values():
        value = str(value)
        if len(value) >= BROWSER_SCENARIO_MASK_MIN_LEN:
            text = text.replace(value, BROWSER_SCENARIO_MASK)

    return text


def browser_scenario_step_target(step: BrowserScenarioStep) -> str:
    """На что смотрел шаг — для журнала. Строка до подстановки: значения
    переменных в журнал не попадают, а `{{password}}` читается и так."""
    return step.url or step.selector or step.key or step.value
