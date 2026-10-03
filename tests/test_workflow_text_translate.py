"""Перевод выделенного куска промпта: метки до модели не доходят.

## ⚠⚠⚠ Что здесь главное

Не перевод — его делает модель, и проверять его бессмысленно. Главное, что
**метки движка переживают дорогу туда и обратно**. В промпте живут `%имя%` и
`[<if …>]`, их читает `ai_workflow.py`; переведи модель `%girl_name%` как
`%имя_девушки%` или потеряй `[<endif>]` — workflow сломается без единой ошибки.
Ровно эта порода беды стоила трёх минут точности при поиске поломки инвайтов
(`workflow_history.md`).

⚠⚠ И второе по важности: **потеря заслонки не чинится догадкой**. Если модель
вернула текст без `⟦2⟧`, подставлять метку наугад нельзя — функция отдаёт
`null`, и кнопка оставляет текст как был. Промпт непереведённый — просто
непереведённый; промпт с потерянной меткой — тихо сломанный.

## ⚠ Почему через node, а не браузером

Функции чистые: текст на входе, текст на выходе. Тот же приём, что у
`test_workflow_undefined_index.py` и соседей: **настоящий** модуль импортом,
заглушки только на то, чего в node нет (`fetch`, DOM). Своя копия правила в
тесте разошлась бы с модулем на первой же правке.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

TRANSLATE = './data/uvicorn/public/js/workflow/text-translate.js'

# Промпт как он есть: метка в тексте, условный блок, метка внутри блока.
PROMPT = (
    'Ты пишешь письмо для %girl_name%.\n'
    '[<if mail_kind == \'invite\'>]\n'
    'Это первое письмо, поздоровайся.\n'
    '[<else>]\n'
    'Вы уже знакомы: %talk_history_chat%\n'
    '[<endif>]\n'
    'Пиши коротко.'
)


class TestTheMarkersNeverReachTheModel:
    """⚠⚠⚠ Что уходит в модель — текст без единой метки движка."""

    def test_no_marker_is_left_in_the_masked_text(self):
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            const out = m.textTranslateMask({json.dumps(PROMPT)});
            console.log(JSON.stringify(out));
        """)

        assert '%girl_name%' not in got['text'], got['text']
        assert '%talk_history_chat%' not in got['text'], got['text']
        assert '[<' not in got['text'], got['text']

    def test_every_marker_is_remembered(self):
        """⚠ Пять меток: две переменные и три части условного блока."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(m.textTranslateMask({json.dumps(PROMPT)})));
        """)

        assert got['marks'] == [
            '%girl_name%',
            "[<if mail_kind == 'invite'>]",
            '[<else>]',
            '%talk_history_chat%',
            '[<endif>]',
        ], got['marks']

    def test_a_mail_variable_in_double_brackets_is_masked(self):
        """⚠⚠ `[[girl_name]]` наш движок не читает, а DatingAi — читает.

        Промпт инвайта прямо просит модель поставить такую метку. Переведи её
        переводчик в `[[имя_девушки]]` — подстановка молча перестанет её
        находить, и человек получит письмо со скобками в тексте.
        """
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(m.textTranslateMask(
                'Поставь метку [[girl_name]] ровно один раз.')));
        """)

        assert '[[girl_name]]' not in got['text'], got['text']
        assert got['marks'] == ['[[girl_name]]']

    def test_a_chip_label_is_left_to_the_translator(self):
        """⚠ `[[Создать проект]]` — подпись кнопки чата, её перевод осмыслен.

        Отличается от метки ровно видом: имя — идентификатор, подпись — фраза.
        Списка исключений тут нет и быть не должно.
        """
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(m.textTranslateMask(
                'Предложи [[Создать проект]] в конце.')));
        """)

        assert got['marks'] == [], got['marks']

    def test_plain_text_is_left_alone(self):
        """⚠ Текста без меток заслонка не касается: лишняя правка — тоже правка."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(m.textTranslateMask('Пиши коротко и по делу.')));
        """)

        assert got['text'] == 'Пиши коротко и по делу.'
        assert got['marks'] == []


class TestTheMarkersComeBackWhole:
    """⚠⚠ Дорога туда и обратно не меняет ни одной метки."""

    def test_a_round_trip_restores_the_prompt(self):
        """Модель вернула заслонки нетронутыми — текст совпадает побайтно."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            const out = m.textTranslateMask({json.dumps(PROMPT)});
            console.log(JSON.stringify(
                {{back: m.textTranslateUnmask(out.text, out.marks)}}));
        """)

        assert got['back'] == PROMPT

    def test_spaces_inside_a_holder_are_forgiven(self):
        """⚠ Модель иногда расставляет пробелы внутри скобок (`⟦ 0 ⟧`). Номер
        цел — значит цела и метка, ругаться тут не на что."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(
                {{back: m.textTranslateUnmask('Write to ⟦ 0 ⟧ now', ['%girl_name%'])}}));
        """)

        assert got['back'] == 'Write to %girl_name% now'

    def test_the_translated_words_around_a_marker_survive(self):
        """⚠ Текст вокруг метки — это и есть перевод; его трогать нельзя."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(
                {{back: m.textTranslateUnmask('You write a letter for ⟦0⟧.',
                                              ['%girl_name%'])}}));
        """)

        assert got['back'] == 'You write a letter for %girl_name%.'


class TestALostMarkerStopsEverything:
    """⚠⚠⚠ Потерянная заслонка — отказ, а не догадка.

    Промпт с пропавшей меткой тих и сломан. Промпт непереведённый — просто
    непереведённый. Из двух зол кнопка обязана выбирать второе.
    """

    def test_a_dropped_holder_returns_nothing(self):
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(
                {{back: m.textTranslateUnmask('You write a letter.',
                                              ['%girl_name%'])}}));
        """)

        assert got['back'] is None, 'потерянная метка прошла молча'

    def test_one_lost_out_of_many_is_enough_to_refuse(self):
        """⚠ Хватает одной: половина меток на месте — это не «почти хорошо»."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(
                {{back: m.textTranslateUnmask('⟦0⟧ and ⟦1⟧ but not the third',
                                              ['%a%', '%b%', '%c%'])}}));
        """)

        assert got['back'] is None, 'пропажа третьей метки прошла молча'

    def test_a_translated_holder_is_a_loss(self):
        """⚠⚠ Модель переписала скобки под язык ответа — метки нет.

        Поймать это можно только сверкой: текст выглядит целым и читается
        гладко, а движок потом не найдёт в нём ничего.
        """
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(
                {{back: m.textTranslateUnmask('Write to [[0]] now', ['%girl_name%'])}}));
        """)

        assert got['back'] is None, 'переписанная заслонка принята за метку'


class TestAnEmptyAnswerNeverReplacesAnything:
    """⚠⚠⚠ Пустой ответ стёр бы выделенное. Куплено живым прогоном.

    Кусок промпта с `[[girl_name]]` и `[<if …>]`, отданный модели **без**
    заслонки, вернулся пустой строкой — не ошибкой, не отказом, пустотой. На
    тексте с метками отказ даёт сверка заслонок, а на тексте **без** меток не
    спасало ничто: `unmask('', [])` — законная пустая строка, и абзац заменился
    бы ничем.
    """

    def test_an_empty_answer_on_plain_text_is_refused(self):
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(m.textTranslateAccept('', [])));
        """)

        assert 'error' in got, f'пустота принята за перевод: {got}'
        assert 'text' not in got

    def test_whitespace_only_is_refused_too(self):
        """⚠ Пробелы и переносы — та же пустота: заменить ими абзац значит
        стереть его, оставив отступ."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(m.textTranslateAccept('   \\n  ', [])));
        """)

        assert 'error' in got, got

    def test_a_good_answer_passes(self):
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(
                m.textTranslateAccept('Write to ⟦0⟧', ['%girl_name%'])));
        """)

        assert got.get('text') == 'Write to %girl_name%', got

    def test_a_lost_marker_is_refused_by_the_same_door(self):
        """⚠ Оба правила живут в одной функции: двум местам «писать или нет»
        разойтись нечего стоит, и заметно это стало бы потерянным промптом."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify(
                m.textTranslateAccept('Write to her', ['%girl_name%'])));
        """)

        assert 'error' in got and 'метк' in got['error'], got


class TestTheSourceLanguageIsGuessed:
    """⚠ Язык источника ручке нужен, а человеку его называть незачем."""

    @pytest.mark.parametrize('text,want', [
        ('Пиши коротко и по делу', 'ru'),
        ('Write short and to the point', 'en'),
        ('Пиши коротко і по суті', 'uk'),
        ('%girl_name%', 'en'),
    ])
    def test_it_reads_the_letters(self, text, want):
        """⚠ Последний случай — голая метка: букв нет вовсе, и честнее
        считать такое латиницей, чем гадать."""
        got = _run(f"""
            const m = await import('{TRANSLATE}');
            console.log(JSON.stringify({{lang: m.textTranslateGuess({json.dumps(text)})}}));
        """)

        assert got['lang'] == want


def _run(script: str):
    """Гоняет скрипт на настоящем модуле перевода.

    ⚠ Заглушек нет вовсе, и это проверено, а не предположено: модуль тянет
    `api.js` и `notification.js`, но те на старте `window`/`document` не
    трогают — сеть и разметку они спрашивают только внутри своих функций.
    Понадобится заглушка — об этом скажет `node`, а не догадка здесь.
    """
    if not shutil.which('node'):
        pytest.skip('node недоступен — заслонку меток проверить нечем')

    done = subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)
