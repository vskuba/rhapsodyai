"""Сторожа самих LLM-тестов: правило утверждений, приметы шагов, ключ девушки.

## ⚠⚠ Почему эти три живут здесь, а не рядом с тем, что стерегут

Они стерегут `tests_llm/`, но **модель не зовут вовсе**: один читает исходники
разбором, другой спрашивает список шагов обычной ручкой, третий смотрит на
константу. Стояли они в `tests_llm/` под меткой `llm_live` — «его красное чинится
без прогона дорогих соседей», — и это обернулось против них: `llm_live` исключён из
`addopts`, то есть **не идёт никогда**, пока человек не позовёт руками.

Сторож, которого не зовут, не стережёт. Здесь они идут со всей сюитой и стоят
четверть секунды на все три.

⚠ Обратная сторона переноса: файлы, за которыми они смотрят, лежат в соседней
папке, и путь к ним теперь **явный** (`LLM_DIR`). Сломай кто-нибудь раскладку
`tests_llm/` — тесты скажут об этом словами, а не пустой выборкой.
"""

import pathlib
import re
from typing import AsyncGenerator

import httpx
import pytest

from tests.conftest import BASE_URL
from tests.constants import TEST_AUTH
from tests_llm.mark import TEST_GIRL_ID, TEST_MARK

pytestmark = pytest.mark.ai

# Папка с тестами workflow. ⚠ Отсчитывается от корня репозитория, а не от
# `__file__`: сюита гоняется из корня, и относительный путь читается проще, чем
# `parent.parent`.
LLM_DIR = pathlib.Path('tests_llm')

# Примета шага в оснастке: `STEP_CHAT = 'Ответ в чат'`.
STEP_MARK_RE = re.compile(r"^(STEP_[A-Z_]+) = '([^']+)'", re.M)


class TestTheAnswerTextIsNeverAsserted:
    """⚠⚠ Ни один тест workflow не смотрит на текст ответа модели.

    Правило легко нарушить по привычке — `got.text` лежит под рукой и читается
    естественно. А нарушение стоит дорого и не сразу видно: тест зеленеет на удачной
    формулировке и краснеет на другой, одинаково ничего не проверяя.

    Правило целиком — `.claude/docs/testing_llm.md`, «утверждения только по трассе».
    """

    def test_no_llm_test_reads_the_answer_text(self):
        """`got.text` в утверждении запрещён.

        ⚠⚠ **Смотрим разобранный код, а не строки файла.** Первая проверка искала
        подстроку — и поймала три ложных: объяснение в докстринге, где `got.text`
        упомянут нарочно, и саму себя. Правило про **обращения в коде**, а
        комментарии и описания к коду не относятся: запретив их, мы запретили бы
        объяснять, почему так делать нельзя.
        """
        import ast

        seen = sorted(LLM_DIR.rglob('test_*.py'))

        assert seen, (f'в {LLM_DIR} не нашлось ни одного теста — раскладка папки '
                      f'изменилась, и сторож смотрит в пустоту')

        bad = []
        for path in seen:
            tree = ast.parse(path.read_text(encoding='utf-8'))

            for node in ast.walk(tree):
                # `что-то.text` — обращение к полю. Строки и комментарии сюда не
                # попадают вовсе: разбор их не видит.
                if isinstance(node, ast.Attribute) and node.attr == 'text':
                    bad.append(f'{path.name}:{node.lineno}')

        assert not bad, ('тест смотрит на текст ответа — так нельзя '
                         '(`.claude/docs/testing_llm.md`): ' + ', '.join(bad))


class TestTheStepMarkersAreAlive:
    """⚠⚠ Приметы шагов сверяются с базой — иначе они тихо умирают.

    Имя шага живёт в двух местах: в админке и в оснастке тестов. Переименуй шаг — и
    примета перестаёт совпадать ни с чем, а `prompt_of` возвращает пустоту. Тест
    падает на «промпт не прочитался», и настоящая причина в этих словах не названа.

    Так уже было: разбиение на ветки переименовало «Генерация ответа» в «Ответ в
    чат», и семь проверок в трёх файлах оказались красными разом — каждая жаловалась
    на промпт, ни одна на имя.

    ⚠ К модели не ходит: список workflow и шаги к нему — обычные ручки.
    """

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as client:
            await client.post('/auth/login', json=TEST_AUTH)
            yield client

    @pytest.fixture
    async def workflow_steps(self, client) -> set:
        """Имена всех шагов всех workflow — чтобы сверять с ними приметы.

        ⚠⚠ **Всех, а не только одного workflow.** Часть примет указывает на шаги
        подпрогонов (`fact_collection_add_companion` живёт в
        `companion_fact_extract`), и они приезжают в трассу наравне со своими.
        Ограничь выборку — сторож объявил бы законные приметы мёртвыми.
        """
        got = await client.get('/workflow/list')

        if got.status_code != 200:
            pytest.fail(f'список workflow не читается ({got.status_code})')

        out = set()
        for one in (got.json().get('result') or []):
            steps = await client.get(f'/workflow/{one.get("id")}/steps')

            if steps.status_code != 200:
                continue

            out |= {str(step.get('title') or '')
                    for step in (steps.json().get('result') or [])}

        return out

    async def test_every_step_marker_exists_in_the_workflow(self, workflow_steps):
        """⚠ Сверяются приметы **всех** папок, а не одной.

        Прежняя версия читала `conftest.py` своей папки — то есть стерегла 21 примету
        `dating_talk` и не видела 23 остальных. Переименуй шаг письма, и красным
        становился бы тест письма, жалуясь на пустой промпт.
        """
        seen = sorted(LLM_DIR.glob('*/conftest.py'))

        assert seen, (f'в {LLM_DIR} не нашлось оснастки ни одного workflow — '
                      f'раскладка папки изменилась')

        marks = {}
        for path in seen:
            for name, value in STEP_MARK_RE.findall(path.read_text(encoding='utf-8')):
                marks[f'{path.parent.name}.{name}'] = value

        assert marks, 'ни одной приметы шага не нашлось — изменился их вид в оснастке'

        dead = {name: value for name, value in marks.items()
                if value not in workflow_steps}

        assert not dead, (
            'приметы шагов не совпадают ни с одним шагом workflow — '
            'их переименовали в админке: '
            + ', '.join(f'{n} = «{v}»' for n, v in sorted(dead.items())))


class TestTheGirlKeyIsTheTestOne:
    """⚠⚠ Сторож изоляции: факты уходят в тестовый документ, а не в рабочий.

    Шаг `girl_fact_invent` **дописывает** придуманное в документ девушки. Без своего
    ключа каждый прогон засорял бы память анкеты, которая пишет живым людям на сайте
    знакомств.

    ⚠ Здесь проверяется сама метка. Что она доходит до фильтра поиска — проверяет
    `tests_llm/dating_talk/test_girl_bio.py`: для этого нужен прогон.
    """

    def test_the_default_key_is_marked(self):
        assert TEST_GIRL_ID.startswith(TEST_MARK), \
            f'ключ девушки для тестов не помечен «{TEST_MARK}»: {TEST_GIRL_ID}'
