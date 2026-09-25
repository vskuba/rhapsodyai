"""Чем «отвечает» модель на шагах `dating_mail_write`. Только данные.

Массивы пар `[ключ ответа, значение]`; как они превращаются в сценарий подмены —
`tests_llm/plan.py`.

## ⚠⚠ Что здесь проверяется и чего живым прогоном не проверить

У workflow три круга правок (`write_try < 3`) и два судьи: язык и повтор.
Заставить живую модель ответить «язык неверный» именно на втором круге нельзя —
она решает сама. Здесь это строка массива.
"""

# Годное письмо: метки реестра и вопрос отдельным абзацем.
#
# ⚠⚠ Метки обязаны быть **настоящими**: шаг «Все ли метки?» сверяет их с
# реестром сайта инструментом, а не моделью. Выдумай имя — заход уйдёт на круг
# правок, и тест проверит не то, ради чего написан.
#
# ⚠ Живая переменная (`question_to_companion`) стоит **отдельным абзацем**:
# внутри фразы вышло бы «What are What do you enjoy??» — та самая беда, ради
# которой заведён шаг «Вопрос отдельно?».
LETTER_GOOD = ('Hi [[companion_name]], I am [[girl_name]] and I live by the sea.'
               '\n\n[[question_to_companion]]')

# ⚠⚠ Письмо без меток вовсе отсеивается **раньше**, чем кажется: шаг
# «Переменные» уводит на круг по `found_qty == 0` — «меток не нашлось ни одной»,
# — и до ворот «Все ли метки?» заход не доходит.
#
# То есть у первых ворот **два** условия, и это разные изъяны: выдуманная метка и
# отсутствие меток. Проверять их надо порознь.
# Письмо без меток вовсе: шаг «Все ли метки?» отправит его на круг правок.
LETTER_NO_MARKS = 'Hi there, I live by the sea and love old barometers.'

# Письмо с **выдуманной** меткой: в реестре сайта `favourite_song` нет, и шаг
# «Переменные» найдёт её как неизвестную.
#
# ⚠ Настоящие метки тоже на месте: иначе заход упёрся бы сперва в «Все ли
# метки?», и тест проверил бы не те ворота. Каждая проверка ловится **своим**
# изъяном, а не общим негодным письмом.
LETTER_UNKNOWN_MARK = ('Hi [[companion_name]], I am [[girl_name]] and my song is '
                       '[[favourite_song]].\n\n[[question_to_companion]]')

# Письмо с вопросом **внутри** абзаца — то, что ловит «Вопрос отдельно?».
LETTER_INLINE = ('Hi [[companion_name]], I am [[girl_name]]. '
                 '[[question_to_companion]] And how was your week?')

# Письмо, где метки есть, все известны и вопрос отдельным абзацем — но одной
# обязательной не хватает (`girl_name`). Только так заход доходит до ворот «Все
# ли метки?»: письмо без меток вовсе отсеется первыми воротами.
LETTER_SOME_MARKS = ('Hi [[companion_name]], I live by the sea and love old '
                     'barometers.\n\n[[question_to_companion]]')

LETTER_TITLE = 'A letter from the lighthouse'


# ── Заготовка: обычный заход, всё с первого раза ────────────────────────────

PLAN_OK = [
    ['letter', {'letter': LETTER_GOOD, 'letter_title': LETTER_TITLE}],
    ['letter_lang_ok', {'letter_lang_ok': '1'}],
    ['letter_same', {'letter_same': 'no', 'letter_same_why': ''}],
]


# ── Отличия: кладутся **перед** заготовкой ──────────────────────────────────

# Судья языка забраковал письмо — заход уходит на круг правок.
PLAN_LANG_BAD = [
    ['letter_lang_ok', {'letter_lang_ok': '0'}],
]

# Судья повтора узнал письмо: «так уже писали».
PLAN_SAME = [
    ['letter_same', {'letter_same': 'yes',
                     'letter_same_why': 'то же про маяк и барометры'}],
]

# Модель вернула письмо без меток реестра.
PLAN_NO_MARKS = [
    ['letter', {'letter': LETTER_NO_MARKS, 'letter_title': LETTER_TITLE}],
]

# Вопрос внутри абзаца, а не отдельным.
PLAN_INLINE = [
    ['letter', {'letter': LETTER_INLINE, 'letter_title': LETTER_TITLE}],
]

# Метки есть, но обязательной `girl_name` среди них нет.
PLAN_SOME_MARKS = [
    ['letter', {'letter': LETTER_SOME_MARKS, 'letter_title': LETTER_TITLE}],
]

# Выдуманная метка, которой нет в реестре сайта.
PLAN_UNKNOWN_MARK = [
    ['letter', {'letter': LETTER_UNKNOWN_MARK, 'letter_title': LETTER_TITLE}],
]
