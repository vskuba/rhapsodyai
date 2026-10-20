"""Жребий выпадает теми долями, что заданы, и не прощает кривого описания.

## ⚠⚠ Что здесь стережётся

Инструмент `dice` — единственное место, где решается, чем письма будут
отличаться друг от друга. Сломайся он **тихо** — все варианты сойдутся к одному,
и заметить это можно будет только по десятку писем подряд, то есть через сутки
работы прода.

Тихая поломка тут не выдумка, а самый вероятный исход правки: если перебирать
варианты с отдельным броском на каждый вместо одного броска на переменную,
первый вариант получит свою долю, а последний — заметно меньше заданной. Ответ
при этом останется правдоподобным: одно из значений, просто не с той частотой.

## ⚠ Почему доли проверяются статистикой, а не одним вызовом

Другого способа нет: у одного броска нет «правильного» исхода. Поэтому бросаем
много раз и смотрим на частоты. Допуск взят с запасом (±3 пункта на десяти
тысячах бросков) — так проверка ловит сдвиг распределения и не краснеет от
обычного разброса.

⚠ Зерно **не закрепляем**. Прибитый `random.seed` превратил бы это в проверку
одной последовательности: перестановка вариантов местами такой тест не
потревожит, а частоты изменит.
"""

import collections

import pytest

from tool.dice.dice import dice, dice_batch

pytestmark = pytest.mark.core

# Сколько бросков на замер частот и какой разброс считаем обычным.
ROLLS = 10_000
TOLERANCE = 3.0


class TestTheSharesAreWhatWasAsked:

    async def test_two_options_come_out_as_set(self):
        got = await _shares({'x': {'а': 25, 'б': 75}}, 'x')

        assert got['а'] == pytest.approx(25, abs=TOLERANCE), got
        assert got['б'] == pytest.approx(75, abs=TOLERANCE), got

    async def test_many_options_keep_their_own_shares(self):
        """⚠ Восемь равных долей — то, чем заданы темы рассказа о себе.

        Здесь и краснел бы бросок «по варианту за раз»: у последнего в списке
        доля просела бы втрое, оставаясь ненулевой.
        """
        spec = {'x': {str(i): 10 for i in range(8)}}
        got = await _shares(spec, 'x')

        for i in range(8):
            assert got[str(i)] == pytest.approx(10, abs=TOLERANCE), got

    async def test_every_variable_is_rolled_on_its_own(self):
        """Две переменные в одном заходе не делят один бросок.

        ⚠ Будь бросок общим, значения ходили бы парами: «первое с первым»
        всегда, — и разнообразие оказалось бы вдвое беднее заявленного.
        """
        spec = {'a': {'a1': 50, 'a2': 50}, 'b': {'b1': 50, 'b2': 50}}
        pairs = collections.Counter()

        for _ in range(ROLLS):
            got = await dice(spec)
            pairs[(got['a'], got['b'])] += 1

        assert len(pairs) == 4, f'сочетаний должно быть четыре: {dict(pairs)}'


class TestTheUndershootMeansNothing:
    """⚠⚠ Недобор до ста — законное описание, а не недоделка.

    Так задаётся «в 40% случаев добавь рассказ»: в остальных 60% переменная
    приходит пустой, и `%if%` читает это как «не надо». Вариант-пустышку «не
    рассказывай о себе» иначе пришлось бы придумывать, а запрет в промпте модель
    исполняет хуже, чем отсутствие просьбы.
    """

    async def test_the_rest_comes_out_empty(self):
        got = await _shares({'x': {'а': 20, 'б': 20}}, 'x')

        assert got.get('', 0) == pytest.approx(60, abs=TOLERANCE), got

    async def test_a_full_hundred_never_comes_out_empty(self):
        got = await _shares({'x': {'а': 50, 'б': 50}}, 'x')

        assert '' not in got, f'при сумме 100 пустого быть не может: {got}'


class TestTheShareMayComeFromAVariable:
    """⚠⚠ Долю вправе задавать настройка сайта, а не только описание шага.

    Подставляет её движок — метаданные шага рендерятся до вызова инструмента, —
    поэтому сюда доезжает уже значение, и зачастую **строкой**.
    """

    async def test_a_number_in_a_string_is_a_share(self):
        got = await _shares({'x': {'а': '25', 'б': 75}}, 'x')

        assert got['а'] == pytest.approx(25, abs=TOLERANCE), got

    async def test_a_percent_sign_is_tolerated(self):
        """⚠ Человек, задающий проценты, пишет «40%» чаще, чем «40»."""
        got = await _shares({'x': {'а': '40%', 'б': 60}}, 'x')

        assert got['а'] == pytest.approx(40, abs=TOLERANCE), got

    async def test_an_empty_setting_is_zero_not_a_refusal(self):
        """⚠⚠ Незаполненная настройка значит «этот вариант не выпадает».

        Ронять из-за неё весь заход нельзя: письмо не ушло бы вовсе из-за
        необязательной настройки. Молчаливого искажения тут нет — доли
        независимы, и обнулённый вариант не меняет шансов остальных.
        """
        got = await _shares({'x': {'а': '', 'б': 70}}, 'x')

        assert 'а' not in got, got
        assert got['б'] == pytest.approx(70, abs=TOLERANCE), got


class TestTheRestTakesWhatIsLeft:
    """⚠⚠ Ради «остатка» всё и затевалось: без него доля из настройки не пишется.

    Пара «да/нет» требует, чтобы сумма укладывалась в сотню, а второй половины мы
    не знаем. `{да: "%percent%", нет: 75}` при настройке 40 даёт 115 — отказ
    прямо на заходе, то есть письмо не ушло из-за того, что кто-то подвинул
    ползунок. С «остатком» сумма сходится при любой настройке.
    """

    @pytest.mark.parametrize('percent', [0, 10, 40, 90, 100])
    async def test_it_holds_for_any_setting(self, percent):
        got = await _shares({'x': {'да': percent, 'нет': 'rest'}}, 'x')

        assert got.get('да', 0) == pytest.approx(percent, abs=TOLERANCE), got
        assert got.get('нет', 0) == pytest.approx(100 - percent, abs=TOLERANCE), got

    async def test_nothing_is_ever_empty_with_a_rest(self):
        """⚠ «Остаток» и недобор — разные вещи, и вместе их не бывает.

        Пустая строка значит «ни один вариант не выпал»; при «остатке» такого
        случая нет вовсе — он и есть все оставшиеся проценты.
        """
        got = await _shares({'x': {'да': 30, 'нет': 'rest'}}, 'x')

        assert '' not in got, f'при «остатке» пустого быть не может: {got}'

    async def test_an_empty_setting_gives_the_rest_everything(self):
        got = await _shares({'x': {'да': '', 'нет': 'rest'}}, 'x')

        assert got.get('нет', 0) == pytest.approx(100, abs=TOLERANCE), got

    async def test_it_keeps_its_place_in_the_order(self):
        """⚠ Доля считается после всех, но **стоит там, где записана**.

        Порядок решает, какому варианту достанется бросок; переставь «остаток» в
        конец — и доли соседей поедут.
        """
        got = await _shares({'x': {'прочее': 'rest', 'да': 30}}, 'x')

        assert got['да'] == pytest.approx(30, abs=TOLERANCE), got
        assert got['прочее'] == pytest.approx(70, abs=TOLERANCE), got

    async def test_a_capital_letter_is_tolerated(self):
        """⚠ Значение приходит из формы: «Rest» — обычная описка, а не другое
        слово. Отказ «доля не число» спрятал бы причину."""
        got = await _shares({'x': {'да': 25, 'нет': ' Rest '}}, 'x')

        assert got['да'] == pytest.approx(25, abs=TOLERANCE), got

    async def test_two_rests_are_refused(self):
        with pytest.raises(ValueError, match='rest'):
            await dice({'x': {'а': 'rest', 'б': 'rest'}})


class TestBadSpecIsRefusedLoudly:
    """⚠ Всё, что здесь пропущено молча, всплывёт как ровные письма.

    Отказ ловят на заходе и чинят; тихо принятое описание не чинит никто.
    """

    @pytest.mark.parametrize('spec, why', [
        ({}, 'ни одной переменной'),
        ({'x': {'один': 100}}, 'один вариант — это не жребий'),
        ({'x': {'а': 60, 'б': 70}}, 'сумма больше ста'),
        ({'x': {'а': -10, 'б': 50}}, 'отрицательная доля'),
        ({'x': {'а': 'много', 'б': 50}}, 'доля не число'),
        ({'x': {'а': True, 'б': 50}}, 'булево вместо доли'),
        ('{кривой', 'не разбирается как JSON'),
    ])
    async def test_it_raises(self, spec, why):
        with pytest.raises(ValueError):
            await dice(spec)

    async def test_an_unresolved_mark_is_an_error_with_its_name(self):
        """⚠⚠ Метка, дожившая до инструмента, значит «переменной нет в заходе».

        Это опечатка или забытое объявление, и оба чинятся, а не обходятся.
        Считать её нулём — молча выключить ось разнообразия.
        """
        with pytest.raises(ValueError, match='mail_story_percent'):
            await dice({'x': {'а': '%mail_story_percent%', 'б': 50}})


class TestTheSpecMayArriveAsText:
    """⚠ Описание приезжает литералом `_const_…`, то есть строкой.

    Приводить его к `dict` умеет и движок (по аннотации довода), но инструмент
    обязан пережить оба вида сам: `_const_` правит человек в редакторе, и
    полагаться на одну-единственную дорогу разбора здесь не на что.
    """

    async def test_a_json_string_works_the_same(self):
        got = await dice('{"x": {"а": 50, "б": 50}}')

        assert got['x'] in ('а', 'б'), got


class TestASeriesOfRolls:
    """`dice_batch` — серия бросков: пачке нужен приём на каждую строку.

    ⚠⚠ Один приём на всю пачку сделал бы её однообразной, а выбор приёмов
    самой моделью — ровно то, от чего жребий заведён.

    ⚠ Отдельной функцией, а не доводом `dice`: ответ у них разного типа —
    значение против списка, — и функция, меняющая тип ответа по значению
    аргумента, это две функции под одним именем.
    """

    SPEC = {'angle': {'игра': 50, 'вызов': 30, 'вопрос': 20}}

    async def test_dice_itself_stays_a_single_value(self):
        """⚠ `dice` не тронут: прежние шаги зовут его и получают значение."""
        got = await dice(self.SPEC)

        assert got['angle'] in ('игра', 'вызов', 'вопрос')
        assert '\n' not in got['angle']

    async def test_a_series_comes_as_a_list(self):
        """⚠⚠ Список, а НЕ нумерованная строка: нумерует промпт циклом.

        Нумерация уехала в `[<for k,v in …>][<set k = k + 1>]` — туда, где
        список и читают. Здесь стережётся сама форма: вернись отсюда строка,
        цикл в промпте прошёлся бы по её строкам и номера задвоились бы.
        """
        got = await dice_batch(self.SPEC, times=5)

        assert isinstance(got['angle'], list), f'ответ не список: {got["angle"]!r}'
        assert len(got['angle']) == 5

    async def test_nothing_is_numbered_by_the_tool(self):
        """⚠ Ни одного номера от инструмента — иначе промпт пронумерует дважды."""
        got = await dice_batch(self.SPEC, times=5)

        for one in got['angle']:
            assert not one[:3].strip().rstrip('.').isdigit(), \
                f'инструмент пронумеровал сам: {one!r}'

    async def test_every_item_is_a_real_option(self):
        got = await dice_batch(self.SPEC, times=12)

        for one in got['angle']:
            assert one in self.SPEC['angle'], one

    async def test_an_empty_roll_keeps_its_place(self):
        """⚠⚠⚠ Пустое выпадение остаётся ЭЛЕМЕНТОМ — ради этого и список.

        Доли задаёт человек, и при недоборе до ста бросок честно пуст: «в этой
        реплике приёма нет». Отдавай инструмент строки, пустая потерялась бы в
        цикле промпта, и вся нумерация ниже съехала бы на единицу — «приём 2»
        достался бы третьей реплике, без единой ошибки.
        """
        got = await dice_batch({'angle': {'а': 0, 'б': 0}}, times=4)

        assert got['angle'] == ['', '', '', ''], \
            f'пустые выпадения не держат места: {got["angle"]!r}'

    async def test_the_count_arrives_as_text(self):
        """⚠ Число приходит workflow-переменной, то есть строкой; мусор — один."""
        assert len((await dice_batch(self.SPEC, times='3'))['angle']) == 3

        for given in ('', None, 0, 'мусор', -5):
            got = await dice_batch(self.SPEC, times=given)

            assert len(got['angle']) == 1, f'{given!r} дало серию из {len(got["angle"])}'

    async def test_the_series_has_a_ceiling(self):
        """⚠ Потолок: опечатка в настройке иначе уехала бы списком на тысячу."""
        got = await dice_batch(self.SPEC, times=10_000)

        assert len(got['angle']) == 50

    async def test_repeats_inside_a_series_are_allowed(self):
        """⚠⚠ Доли заданы человеком, и «без повторов» исказило бы их молча.

        При 50 бросках трёх вариантов повторы неизбежны — проверяем, что
        инструмент их не прячет и серию не укорачивает.
        """
        got = await dice_batch(self.SPEC, times=50)

        assert len(got['angle']) == 50


async def _shares(spec: dict, name: str) -> dict:
    """Частоты значений одной переменной в процентах."""
    got = collections.Counter()

    for _ in range(ROLLS):
        got[(await dice(spec))[name]] += 1

    return {value: qty * 100 / ROLLS for value, qty in got.items()}
