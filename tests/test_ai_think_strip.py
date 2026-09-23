"""Хвост размышлений не доезжает до текста, который читает человек.

## ⚠⚠ Что здесь стережётся

llama.cpp гасит размышления `--reasoning-budget 0`, и ветка «бюджет вышел»
срабатывает **до первого токена**: фраза из `--reasoning-budget-message` и
закрывающий тег приезжают в каждом ответе. Открывающего тега при этом нет вовсе.

Замерено на проде: 5601 ответ из 5601, включая все удачные. То есть это не редкий
случай, а постоянный вид ответа.

## ⚠ Почему тест именно на непарный тег

Прежняя защита в разборе JSON стояла регуляркой `<think>.*?</think>` — она
требует **пары**, а пары здесь не бывает, и замена молча не делала ничего. В
разборе JSON это сходило с рук (мусор отбрасывал поиск скобки `{…}`), а текстовый
ответ шёл наружу как есть: в пул писем лёг черновик, начинающийся с «exceeded,
let's stop and write the final answer now.</think>».

Поэтому главная проверка здесь — **непарный** тег, и именно она краснела бы,
вернись регулярка.
"""

import ast
import pathlib

import pytest

from ai.ai_think import ai_think_strip

pytestmark = pytest.mark.core


# ⚠ Дословно то, что приезжает с прода: фраза из `--reasoning-budget-message`
# сервера и закрывающий тег без открывающего.
BROKEN = ("exceeded, let's stop and write the final answer now.</think>\n\n"
          'I was thinking about our last chat.')


class TestTheTailIsCut:
    """⚠ Главное: ответ начинается с ответа, а не с чужой служебной фразы."""

    def test_an_unpaired_tag_is_handled(self):
        """⚠⚠ Тот самый случай: закрывающий тег без открывающего.

        Регулярка на пару тегов здесь бессильна — вернут её, тест покраснеет.
        """
        assert ai_think_strip(BROKEN) == 'I was thinking about our last chat.'

    def test_a_paired_block_is_handled_too(self):
        """Обычные рассуждающие модели пишут пару — их тоже срезаем."""
        assert ai_think_strip('<think>hmm, maybe</think>\n\nPong') == 'Pong'

    def test_clean_text_survives(self):
        """⚠ Нет тега — текст не трогаем: большинство моделей его и не шлёт."""
        assert ai_think_strip('  Just a letter.  ') == 'Just a letter.'

    def test_the_last_tag_wins(self):
        """⚠⚠ Берём **последний** тег, а не первый.

        Модель, размышляя, способна написать `</think>` внутри рассуждения —
        пересказывая разметку или цитируя чужой ответ. По первому тегу мы
        отрезали бы ответ посреди этой цитаты и выдали хвост рассуждения за него.
        """
        text = 'thinking about </think> as a tag</think>\n\nThe answer.'

        assert ai_think_strip(text) == 'The answer.'


class TestNothingBreaks:
    """⚠ Сюда приезжает ответ модели, а он бывает и не строкой."""

    @pytest.mark.parametrize('given', [None, '', 0, [], {}])
    def test_not_a_string_is_empty(self, given):
        """⚠ Пустая строка, а не исключение: `None` при обрыве связи — обычный
        исход, и ронять на нём разбор ответа значило бы менять отказ связи на
        отказ разбора."""
        assert ai_think_strip(given) == ''


class TestTheRuleIsOne:
    """⚠⚠ Сторож приёма: правило одно на все ответы модели.

    Копий было три, и они разошлись: блог срезал верно, разбор JSON — регуляркой
    на пару, текстовый ответ не срезал вовсе. Разойдись они снова — мусор опять
    потечёт туда, где защиты нет.
    """

    def test_the_paired_regex_is_gone(self):
        """Регулярка на пару тегов не вернулась ни в один файл.

        ⚠ Смотрим на **код**, а не на текст файла: сама регулярка названа в
        комментарии, объясняющем, почему её убрали, — и поиск подстрокой находил
        это объяснение. Первая версия теста упала ровно на нём (и это уже третий
        такой случай в проекте: `_telegram_notify_login`, `initiative`).
        """
        found = [str(path) for path in pathlib.Path('src').rglob('*.py')
                 if '<think>.*?</think>' in _code_only(path)]

        assert not found, f'вернулась регулярка на пару тегов: {found}'

    def test_the_boundary_strips(self):
        """⚠ Срезание стоит **на границе** — там, где ответ становится нашим.

        Убери его оттуда, и починка снова расползётся по дорогам ниже.

        ⚠ Читаем файл, а не импортируем модуль: за ним тянется `pydantic_ai`, а
        сторож приёма не должен требовать половины зависимостей проекта, чтобы
        ответить на вопрос «стоит ли вызов на месте».
        """
        code = _code_only(pathlib.Path('src/ai/framework/agent/ai_framework.py'))
        body = code.split('def engine_result_handle', 1)

        assert len(body) == 2, 'граница ответа исчезла или переименована'
        assert 'ai_think_strip' in body[1].split('\n    async def')[0], \
            'граница ответа перестала срезать хвост размышлений'


def _code_only(path: pathlib.Path) -> str:
    """Файл без комментариев и docstring — один только код.

    ⚠ Нужен ровно затем, чтобы сторож приёма не ловил **объяснения**. Правило,
    которое убрали, называют по имени в комментарии рядом с заменой — иначе
    следующий читатель не поймёт, отчего так; и поиск подстрокой находит это
    объяснение вместо возврата правила.

    ⚠⚠ Строковые литералы при этом **остаются**, и иначе нельзя: искомая
    регулярка сама есть строка, и, срезав строки, сторож перестал бы видеть её
    даже вернувшуюся. Поэтому разбором, а не выбрасыванием всех строк подряд:
    `ast.unparse` уносит комментарии, а литералы не трогает.
    """
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError:
        # Нечитаемый файл — не повод краснеть сторожу: он про наши правила, а
        # синтаксис ловит сам разбор при запуске.
        return ''

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, 'body', [])
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body.pop(0)

    return ast.unparse(tree)
