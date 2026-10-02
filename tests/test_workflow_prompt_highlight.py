"""Подсветка промпта в большом окне: цвета есть, а текст не меняется ни на знак.

Окно правки промпта (`text-modal.js`) рисует цвета **слоем под настоящей `textarea`**:
`<pre>` с раскрашенным HTML позади прозрачного поля. Значение при этом остаётся в поле —
и обязано остаться байт в байт.

## ⚠⚠⚠ Что здесь главное

Не цвета, а **неизменность текста**. Промпт читает движок (`ai_workflow.py`): `%var%`
подставляется, `[<if x>]` разворачивается в блок. Покорёженная метка не подставится, а
сломанный блок уедет в модель как есть — и то и другое молча.

Поэтому каждая проверка снимает разметку с раскрашенного HTML и сличает результат с
исходной строкой. Именно этим отличается «подсветка» от «редактора»: второй правит
текст, первая — нет.

## ⚠ Правила подсветки — те же, что у движка

    WORKFLOW_MARK_RE      %([a-zA-Z_][a-zA-Z0-9_]*)%
    WORKFLOW_IF_BLOCK_RE  [<if условие>] … [<else>] … [<endif>]

Подсветка, знающая другой синтаксис, врала бы: показывала бы меткой то, что движок
меткой не считает. Отсюда проверка «проценты в тексте не метка» — `100%` и `0%` в
живых промптах встречаются, и движок их не трогает (у него на это своя оговорка).

## ⚠ Почему через node, а не браузером

Функция чистая: строка на входе, строка на выходе, DOM не нужен. Браузерный тест стоил
бы живого Chromium и вкладки из общего пула, а проверял бы то же самое. Тот же приём и
тот же пропуск без node, что у `test_task_qa_mode.py`.
"""

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

MODULE = './data/uvicorn/public/js/workflow/text-modal.js'

# Живые куски промптов ноды Dating: на них подсветка и должна работать.
#
# ⚠⚠ Числа — «сколько цветных кусков», а не «сколько меток». Открывающая метка
# условия даёт **три** куска: разметку слева, имя переменной, разметку справа, — и имя
# считается синим, потому что это та же переменная, что и в тексте.
CASES = [
    ('метка переменной', '=== %companion_title% пишет ===', 1, 0),
    ('метка с номером шага', '%datetime_current_get_45_result_str%', 1, 0),
    ('блок с иначе', '[<if talk_history_chat>]было[<else>]нет[<endif>]', 1, 4),
    ('блок с отрицанием', '[<if !answer_anyway>]молчи[<endif>]', 1, 3),
    ('метка внутри блока', '[<if girl_bio>]о себе: %girl_bio%[<endif>]', 2, 3),
    # ⚠ Проценты в тексте меткой не считаются: между ними пробелы, и движок их тоже
    # не считает. Живой случай — «выполнено на 100% людьми».
    ('проценты в тексте', 'на 100% людьми и на 0% роботами', 0, 0),
    # ⚠⚠ Разметка HTML в промпте: экранирование обязано быть обратимым. Промпты
    # писем содержат `<br/>`, и съеденный тег — испорченный промпт.
    ('разметка в тексте', 'а < б, <b>жирный</b> и & амперсанд', 0, 0),
    ('пустая строка', '', 0, 0),
    ('перевод строки в конце', 'первая строка\n\n', 0, 0),
    # ⚠⚠ Условие стало выражением: связки и сравнения. Имена в нём по-прежнему
    # синие, а операторы, связки и литерал справа — разметка.
    #
    #     [<if ⟨разметка⟩ count ⟨имя⟩  > 5 and ⟨разметка⟩ kind ⟨имя⟩  == chat >] ⟨разметка⟩
    ('связка and', '[<if a and b>]да[<endif>]', 2, 4),
    ('сравнение', '[<if count > 5>]много[<endif>]', 1, 3),
    # ⚠ «chat» справа от `==` — литерал, а не переменная: красится разметкой.
    ('сравнение со словом', '[<if kind == chat>]чат[<endif>]', 1, 3),
    ('связка и сравнение', '[<if count > 5 and kind == chat>]оба[<endif>]', 2, 4),
]


class TestTheTextSurvives:
    """⚠⚠⚠ Сняли цвета — получили исходную строку. Ни знаком больше, ни меньше."""

    def test_every_case_comes_back_unchanged(self):
        for name, text, _, _ in CASES:
            back = _plain(_highlight(text))

            assert back == text, (f'«{name}»: текст изменился\n'
                                  f'   было:  {text!r}\n'
                                  f'   стало: {back!r}')

    def test_a_long_prompt_survives(self):
        """⚠ На длинном тексте со всем сразу: короткие случаи не поймают ошибку
        склейки соседних меток."""
        text = ('=== Текущее время ===\n%datetime_current_get_45_result_str%\n\n'
                '[<if talk_history_chat>]=== Разговор ===\n%talk_history_chat%\n\n'
                '[<endif>][<if !answer_anyway>]Молчи.[<else>]Отвечай.[<endif>]\n'
                'Готово на 100% — %girl_name% и %companion_title%.')

        assert _plain(_highlight(text)) == text


class TestWhatGetsColoured:
    """⚠ Правила те же, что у движка: иначе подсветка обещает не то, что будет."""

    def test_counts_match(self):
        for name, text, marks, blocks in CASES:
            out = _highlight(text)

            assert out.count(_MARK) == marks, \
                f'«{name}»: меток подсвечено {out.count(_MARK)}, ждали {marks}'
            assert out.count(_BLOCK) == blocks, \
                f'«{name}»: блоков подсвечено {out.count(_BLOCK)}, ждали {blocks}'

    def test_marks_and_blocks_differ_in_colour(self):
        """⚠ Два разных цвета: метка и разметка блока — разные вещи, и человек должен
        различать их до чтения."""
        assert _MARK != _BLOCK

    def test_the_name_in_the_condition_keeps_its_colour(self):
        """⚠⚠ Имя внутри `[<if …>]` — того же цвета, что и в тексте.

        Сперва открывающая метка красилась целиком: имя условия выходило зелёным, а то
        же имя абзацем ниже — синим. Глаз терял связь между условием и переменной, о
        которой оно, — и это заметил человек, а не тест.

        ⚠ Отрицание `!` остаётся с разметкой: это синтаксис, а не часть имени.
        """
        out = _highlight('[<if !talk_history_chat>]%talk_history_chat%[<endif>]')
        painted = _spans(out)

        assert painted == [(_BLOCK, '[<if !'),
                           (_MARK, 'talk_history_chat'),
                           (_BLOCK, '>]'),
                           (_MARK, '%talk_history_chat%'),
                           (_BLOCK, '[<endif>]')], painted

    def test_the_same_name_is_one_colour_everywhere(self):
        """⚠ Проверка того же с другой стороны: цвет имени не зависит от места."""
        inside = [text for colour, text in _spans(_highlight('[<if girl_bio>]'))
                  if colour == _MARK]
        outside = [text.strip('%') for colour, text
                   in _spans(_highlight('%girl_bio%')) if colour == _MARK]

        assert inside == outside == ['girl_bio']

    def test_a_broken_mark_is_not_coloured(self):
        """⚠ Одинокий процент меткой не считается — как и у движка."""
        out = _highlight('50% и %не закрыт')

        assert out.count(_MARK) == 0


class TestTheLayersCanAlign:
    """⚠⚠ Слои совпадают до пикселя только при одинаковом оформлении.

    Проверяется **одна** константа шрифта на оба слоя: разойдись они — цвет уполз бы
    от буквы, и это хуже, чем без подсветки вовсе. Своей копии стиля у слоёв быть не
    должно.
    """

    def test_one_font_for_both_layers(self):
        text = _source()

        assert text.count('HL_FONT') >= 3, \
            'оформление слоёв задано не одной константой'
        assert 'white-space: pre-wrap' in text, \
            'без общего переноса строк слои разъедутся на длинной строке'

    def test_the_trailing_newline_is_kept(self):
        """⚠ `<pre>` съедает хвостовой перевод строки, `textarea` — нет: без добавки
        последняя пустая строка сдвигала бы слои."""
        assert _highlight('одна строка').endswith('\n')

    def test_the_paint_layer_does_not_take_clicks(self):
        """⚠ `pointer-events: none` у нижнего слоя: иначе выделение мышью попадало бы
        в него, а не в поле."""
        assert 'pointer-events: none' in _source()


def _source() -> str:
    with open(MODULE, encoding='utf-8') as file:
        return file.read()


def _highlight(text: str) -> str:
    """Раскрашенный HTML — настоящей функцией страницы, а не её копией здесь.

    ⚠ Копия разошлась бы с оригиналом на первой правке, и тест стерёг бы себя.
    """
    if not shutil.which('node'):
        pytest.skip('node недоступен — подсветку страницы проверить нечем')

    # ⚠ Текст уезжает **литералом в скрипт**, а не через stdin: в модуле ESM нет
    # `require`, а `readFileSync(0)` без него не прочитать. `json.dumps` даёт готовый
    # литерал JS — кавычки и переводы строк он экранирует сам.
    script = (f"import {{textModalHighlight}} from '{MODULE}';\n"
              f'process.stdout.write(textModalHighlight({json.dumps(text)}));')

    done = subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return done.stdout


def _spans(html: str) -> list:
    """Цветные куски: `[(цвет, текст), …]` в порядке появления.

    ⚠ Экранирование разворачиваем: сравнивать `[&lt;if !` с `[<if !` значило бы
    проверять, как работает `_escape`, а не какого цвета что.
    """
    import re

    out = []
    for found in re.finditer(r'<span style="color: (#[0-9a-fA-F]+)[^"]*">([^<]*)</span>',
                             html):
        text = (found.group(2).replace('&lt;', '<').replace('&gt;', '>')
                .replace('&amp;', '&'))
        out.append((found.group(1), text))

    return out


def _plain(html: str) -> str:
    """Текст без разметки: снимаем `span`-ы и разворачиваем экранирование.

    ⚠ Порядок обратный экранированию: `&amp;` разворачивается **последним**, иначе
    «&amp;lt;» превратилось бы в «<» — то есть проверка сама портила бы текст.
    """
    import re

    text = re.sub(r'<[^>]+>', '', html)
    text = (text.replace('&lt;', '<').replace('&gt;', '>')
                .replace('&amp;', '&'))

    # Хвостовой перевод строки добавлен для совпадения слоёв — это не часть текста.
    return text[:-1] if text.endswith('\n') else text


# Цвета из самого модуля: числа здесь не зашиты, иначе смена палитры валила бы тест,
# ничего не сломав.
def _colour(name: str) -> str:
    import re

    found = re.search(rf"const {name} = '([^']*)'", _source())
    assert found, f'в модуле нет константы {name}'

    return re.search(r'color: (#[0-9a-fA-F]+)', found.group(1)).group(1)


_MARK = _colour('HL_MARK')
_BLOCK = _colour('HL_BLOCK')
