"""Подсветка большого окна промпта: четыре правила сверх меток и блоков.

## ⚠⚠⚠ Что здесь главное

**Текст слоя цвета обязан побайтно совпадать с текстом поля.** Цвет рисует
`<pre>` позади прозрачной `textarea`; добавь подсветка хоть один знак — цвет
уедет от буквы, и человек будет править промпт по неверным краскам. Этот
инвариант проверяется в каждом случае отдельной строкой, а не один раз.

Остальное — про то, что подсветка обещает:

* **красное молчит на здоровом промпте.** Ложная тревога дороже отсутствующей:
  покрасневший рабочий блок учит не верить красному вообще. Проверено и на
  живой базе — 33 поля с разметкой, ни одного ложного;
* **красное говорит о том, что движок не соберёт**: беспарная метка и прежний
  синтаксис (`WORKFLOW_BLOCK_OLD`). Такой блок уезжает в модель словами, и в
  журнале при этом чисто;
* **`%endif%` не метка.** Шаблон `%имя%` подходит к нему слово в слово, и
  порядок правил в `HL_RE` — единственное, что отличает прежний блок от
  переменной.

## ⚠ Почему через node, а не браузером

Функция чистая: текст (и положение курсора) на входе, HTML на выходе. Тот же
приём, что у `test_workflow_text_indent.py`: **настоящий** модуль импортом.
"""
from __future__ import annotations

import json
import os
import re
import shutil

import pytest

from js_.js_static import js_static_run

JS_ROOTS = [os.path.join(os.getcwd(), 'data', 'uvicorn', 'public'),
            os.path.join(os.getcwd(), 'dashboard')]

pytestmark = pytest.mark.core

MODAL = './data/uvicorn/public/js/workflow/text-modal.js'

# Цвета-приметы. ⚠ Сверяемся по значению из модуля, а не по имени стиля: в
# разметку уезжает именно оно, и своего списка цветов тест не заводит.
BAD = '#b91c1c'      # сломанная разметка
HEAD = '#334155'     # заголовок секции
MARK = '#1d4ed8'     # метка и имя переменной
GUIDE = 'inset 1px 0 0'      # направляющая уровня
PAIR = 'outline: 1px solid'     # обводка пары под курсором


class TestTheLayerMatchesTheFieldByteForByte:
    """⚠⚠⚠ Главное. Всё остальное не имеет значения, если это неверно."""

    @pytest.mark.parametrize('text', [
        "[<if count > 5 and kind == 'chat'>]a[<else>]b[<endif>]\n",
        '=== %companion_title% writes ===\n',
        '%if girl_bio%\nx\n%endif%\n',
        '[<if a>]\n        %x%\n[<endif>]\n',
        '[<for k,v in items>][<set k = k + 1>]%k%[<endfor>]\n',
        'Текст без разметки вовсе.\n',
        '',
    ])
    def test_stripping_the_tags_gives_the_source_back(self, text):
        assert _bare(text) == text + '\n'

    def test_the_caret_changes_colours_but_not_text(self):
        """⚠ Подсветка пары добавляет обводку — и ни одного знака."""
        text = '[<if a>]\nx\n[<endif>]\n'

        assert _bare(text, caret=2) == text + '\n'


class TestRedMeansTheEngineWillNotFoldIt:
    """⚠⚠ Красным — ровно то, что уедет в модель словами."""

    def test_a_closing_tag_without_an_opener(self):
        got = _html('[<if a>]x[<endif>]\n[<endif>]\n')

        assert got.count(BAD) == 1, 'лишний [<endif>] не назван'

    def test_an_opener_never_closed(self):
        assert _html('[<if a>]\nx\n').count(BAD) == 1

    def test_a_closer_of_the_wrong_kind(self):
        """`[<endfor>]` поверх `[<if …>]` — беспарны оба, и сказать надо об обоих."""
        assert _html('[<if a>]x[<endfor>]\n').count(BAD) == 2

    def test_an_operator_the_engine_does_not_know(self):
        """⚠ `&&` — примета, а не разбор условия: таких связок у движка нет."""
        assert _html('[<if a && b>]x[<endif>]\n').count(BAD) == 1

    def test_a_broken_tag_is_not_split_into_names(self):
        """⚠⚠ Имена внутри несобирающегося блока не красятся переменной:
        цвет имени — обещание, что блок работает."""
        assert _html('[<if a>]\nx\n').count(MARK) == 0


class TestTheOldSyntaxIsRedAndIsNotAMark:
    """⚠⚠⚠ `%endif%` подходит под шаблон `%имя%` слово в слово.

    Порядок правил в `HL_RE` — единственное, что отличает прежний блок от
    переменной. Переставь их — и `%endif%` покрасится меткой, то есть ровно
    тем, чем он не является.
    """

    @pytest.mark.parametrize('text,qty', [
        ('%if girl_bio%\nx\n%endif%\n', 2),
        ('%else%\n', 1),
        ('[[if a]]x[[endif]]\n', 2),
        ('[[else]]\n', 1),
    ])
    def test_the_old_block_is_red(self, text, qty):
        assert _html(text).count(BAD) == qty

    def test_the_old_block_is_never_painted_as_a_mark(self):
        assert _html('%endif%\n').count(MARK) == 0


class TestRedIsSilentOnAHealthyPrompt:
    """⚠⚠ Ложная тревога дороже отсутствующей: покрасневший рабочий блок
    учит не верить красному вообще."""

    @pytest.mark.parametrize('text', [
        "[<if count > 5 and kind == 'chat'>]a[<else>]b[<endif>]\n",
        '[<for k,v in items, start=1>]%k%. %v%\n[<endfor>]\n',
        '[<set n = n + 1>]%n%\n',
        '[<if a>][<if b>]x[<endif>][<endif>]\n',
        '[<if a>]x[<else>]y[<endif>]\n',
        'Проценты в тексте: 50% скидки, 100% готово.\n',
    ])
    def test_nothing_turns_red(self, text):
        assert BAD not in _html(text), text


class TestTheHeadingGivesThePromptATableOfContents:

    def test_a_heading_is_dimmed(self):
        assert HEAD in _html('=== Current time ===\n')

    def test_a_mark_inside_a_heading_stays_a_mark(self):
        """⚠ Имя в заголовке — единственное, что там подставляется; выкрасься
        оно заодно с заголовком, проверить его стало бы негде."""
        got = _html('=== %companion_title% writes ===\n')

        assert HEAD in got and MARK in got

    def test_a_heading_glued_to_a_block_tag_keeps_them_apart(self):
        """⚠⚠ В живых промптах заголовок сплошь и рядом сросся с разметкой.

        ⚠ Блок здесь закрыт нарочно: `[<if …>]` без `[<endif>]` — сам по себе
        беспарная метка, и красное на ней законно. Первая запись этого случая
        про это забыла и уронила тест на верном коде.
        """
        text = '[<if prompt_user>]=== %companion_title% writes ===\n[<endif>]\n'
        got = _html(text)

        assert BAD not in got
        assert HEAD in got and MARK in got
        assert _bare(text) == text + '\n'


class TestTheGuidesFollowTheStairs:

    def test_one_guide_per_whole_step(self):
        assert _html('[<if a>]\n        %x%\n[<endif>]\n').count(GUIDE) == 2

    def test_a_partial_indent_gets_no_guide(self):
        """⚠ Два пробела — чужой отступ, не от лестницы. Черта на нём читалась
        бы уровнем вложенности, которого нет."""
        assert GUIDE not in _html('[<if a>]\n  %x%\n[<endif>]\n')

    def test_the_very_first_line_is_not_forgotten(self):
        """⚠ Перед первой строкой `\\n` нет, и без отдельной ветки ступени у
        неё не нарисовались бы вовсе."""
        assert _html('    %x%\n[<if a>]x[<endif>]\n').count(GUIDE) == 1


class TestThePairLightsUpUnderTheCaret:

    def test_without_a_caret_nothing_is_outlined(self):
        assert PAIR not in _html('[<if a>]\nx\n[<endif>]\n')

    def test_the_caret_on_the_opener_lights_the_closer(self):
        assert _html('[<if a>]\nx\n[<endif>]\n', caret=2).count(PAIR) == 2

    def test_the_caret_on_the_closer_lights_the_opener(self):
        assert _html('[<if a>]\nx\n[<endif>]\n', caret=12).count(PAIR) == 2

    def test_else_belongs_to_the_same_family(self):
        """⚠ `[<else>]` — середина блока: он обязан загораться вместе с ним."""
        assert _html('[<if a>]x[<else>]y[<endif>]\n', caret=2).count(PAIR) == 3

    def test_the_caret_in_plain_text_lights_nothing(self):
        assert PAIR not in _html('[<if a>]\nxxxx\n[<endif>]\n', caret=10)

    def test_the_inner_block_lights_and_not_the_outer(self):
        """⚠⚠ Вложенность: курсор на внутреннем `[<if b>]` зажигает его пару,
        а не ближайший `[<endif>]` снаружи."""
        got = _html('[<if a>][<if b>]x[<endif>][<endif>]\n', caret=10)

        assert got.count(PAIR) == 2


def _html(text: str, caret: int = -1) -> str:
    """HTML слоя цвета от настоящего модуля окна."""
    if not shutil.which('node'):
        pytest.skip('node недоступен — подсветку проверить нечем')

    done = js_static_run(f"""
        const m = await import('{MODAL}');
        console.log(JSON.stringify(
            m.textModalHighlight({json.dumps(text)}, {caret})));
    """, JS_ROOTS)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)


def _bare(text: str, caret: int = -1) -> str:
    """Текст слоя цвета: теги сняты, экранирование развёрнуто обратно.

    ⚠⚠ Порядок обязателен и проверен ошибкой: сперва **снять теги**, и только
    потом разворачивать `&lt;`. Разверни раньше — `[<if a>]` превратится в
    `[<if a>]` ещё до снятия тегов, и снималка выкусит его как разметку.

    ⚠ `&amp;` разворачивается последним, иначе `&amp;lt;` в исходном тексте
    стал бы `<`.
    """
    html = re.sub(r'<[^>]*>', '', _html(text, caret))

    return html.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
