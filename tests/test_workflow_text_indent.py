"""Лестница отступов в большом окне промпта: вложенность видна формой строки.

## ⚠⚠⚠ Что здесь главное

Не красота. Отступ — **правка текста**: окно пишет значение в поле шага, и
пробелы уезжают в модель вместе с промптом. Поэтому проверяется ровно то, что
лестница может сломать:

* разметка движка цела — ни одна метка не разрезана и не сдвинута внутрь себя;
* повторное открытие окна ничего не добавляет (иначе промпт уезжал бы вправо
  на каждый просмотр, и заметили бы это через неделю);
* текст без блоков не трогается вовсе — окно открывают и над обычными полями;
* чужой отступ внутри промпта (образец JSON, список, кусок кода) переживает
  лестницу: это не пробелы, это смысл.

## ⚠ Почему через node, а не браузером

Функция чистая: текст на входе, текст на выходе. Тот же приём, что у
`test_workflow_text_translate.py`: **настоящий** модуль импортом, своей копии
правила в тесте нет — она разошлась бы с модулем на первой же правке.
"""
from __future__ import annotations

import json
import os
import shutil

import pytest

from js_.js_static import js_static_run

# ⚠ Каталоги статики в порядке поиска — свой проекта, затем общий submodule
# `dashboard`. Тот же порядок, что у раздачи панели.
JS_ROOTS = [os.path.join(os.getcwd(), 'data', 'uvicorn', 'public'),
            os.path.join(os.getcwd(), 'dashboard')]

pytestmark = pytest.mark.core

INDENT = './data/uvicorn/public/js/workflow/text-indent.js'

# Промпт как он есть: блок, вложенный блок, `[<else>]`, метки внутри.
# ⚠ Открывающая метка вложенного блока стоит на строке вместе с текстом — так
# пишут в живых промптах, и именно этот случай лестница чуть не сломала.
PROMPT = (
    '=== Current time ===\n'
    '%datetime_current_get_720_result_str%\n'
    '\n'
    '[<if mail_mode>]\n'
    '[<if talk_history_mail>]=== Correspondence with %companion_title% ===\n'
    '%talk_history_mail%\n'
    '[<endif>]\n'
    '[<else>]\n'
    '[<if talk_history_chat>]=== Chat with %companion_title% ===\n'
    '%talk_history_chat%\n'
    '[<endif>]\n'
    '[<endif>]\n'
)


class TestTheLadderMatchesTheNesting:
    """⚠ Строка отодвигается на ступень за каждый блок вокруг неё."""

    def test_the_root_level_stays_where_it_was(self):
        """Корневой уровень — как был: лишняя правка тоже правка."""
        out = _format(PROMPT).split('\n')

        assert out[0] == '=== Current time ==='
        assert out[3] == '[<if mail_mode>]'

    def test_a_nested_block_steps_right(self):
        out = _format(PROMPT).split('\n')

        assert out[4] == ('    [<if talk_history_mail>]'
                          '=== Correspondence with %companion_title% ===')
        assert out[5] == '        %talk_history_mail%'

    def test_a_closing_tag_stands_a_step_left_of_its_content(self):
        """⚠⚠ Граница блока обязана быть видна там, где её ищут.

        Встань `[<endif>]` вровень с нутром — пропадёт то единственное, ради
        чего отступ и ставился.
        """
        out = _format(PROMPT).split('\n')

        assert out[6] == '    [<endif>]'
        assert out[7] == '[<else>]', 'середина блока ушла вправо вместе с нутром'
        assert out[11] == '[<endif>]'

    def test_an_empty_line_gets_no_trailing_spaces(self):
        """⚠ Отступ на пустой строке не виден никому, а в diff'е виден."""
        assert '\n   \n' not in _format(PROMPT)
        assert _format(PROMPT).split('\n')[2] == ''


class TestTheMarkupSurvives:
    """⚠⚠⚠ Разметку движка читает `ai_workflow.py`. Порченая метка не сработает."""

    def test_every_tag_comes_through_whole(self):
        got = _format(PROMPT)

        for mark in ('[<if mail_mode>]', '[<if talk_history_mail>]',
                     '[<else>]', '[<endif>]', '%talk_history_mail%',
                     '%companion_title%'):
            assert mark in got, mark

    def test_only_leading_spaces_are_added(self):
        """Снять отступы — и текст совпадает с исходным побайтно."""
        bare = '\n'.join(one.lstrip(' ') for one in _format(PROMPT).split('\n'))

        assert bare == PROMPT

    def test_a_comparison_in_the_condition_is_not_cut(self):
        """⚠ `[<if count > 5>]`: `>` внутри условия — не конец метки."""
        got = _format("[<if count > 5 and kind == 'chat'>]\ndeep\n[<endif>]\n")

        assert got == ("[<if count > 5 and kind == 'chat'>]\n"
                       '    deep\n'
                       '[<endif>]\n')


class TestOpeningTheWindowTwiceChangesNothing:
    """⚠⚠ Иначе промпт уезжал бы вправо на каждый просмотр — молча."""

    def test_the_second_pass_is_a_no_op(self):
        once = _format(PROMPT)

        assert _format(once) == once


class TestTheLadderKeepsItsHandsOff:
    """⚠⚠ Чего лестница не трогает — важнее того, что она делает."""

    def test_a_text_without_blocks_is_untouched(self):
        plain = '  отступ автора\n    и глубже\nобычный текст\n'

        assert _format(plain) == plain

    def test_an_indent_wider_than_needed_is_kept(self):
        """⚠ Образец JSON внутри блока — это не пробелы, это смысл."""
        sample = '[<if a>]\n        {\n            "k": 1\n        }\n[<endif>]\n'

        assert _format(sample) == sample

    def test_a_set_tag_opens_no_block(self):
        """⚠ `[<set …>]` — действие внутри строки, а не блок."""
        got = _format('[<set n = 1>]\n%n%\n')

        assert got == '[<set n = 1>]\n%n%\n'

    def test_a_stray_closing_tag_does_not_dig_below_zero(self):
        """Непарный `[<endif>]` — повод не трогать текст, а не уехать влево."""
        assert _format('[<endif>]\n[<endif>]\nx\n') == '[<endif>]\n[<endif>]\nx\n'


def _format(text: str) -> str:
    """Гоняет лестницу на настоящем модуле окна.

    ⚠ Заглушек нет: `text-indent.js` берёт из статики только объявление
    разметки (`text-modal-syntax.js`) — ни `window`, ни `document` на старте
    не трогает ни один из двух.
    """
    if not shutil.which('node'):
        pytest.skip('node недоступен — лестницу отступов проверить нечем')

    done = js_static_run(f"""
        const m = await import('{INDENT}');
        console.log(JSON.stringify(m.textIndentFormat({json.dumps(text)})));
    """, JS_ROOTS)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)
