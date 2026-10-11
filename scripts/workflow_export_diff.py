"""Чем два файла ноды отличаются друг от друга — сверка перед импортом и после.

Зачем скрипт, а не глазами: файл ноды — двести килобайт JSON, в котором правка
из трёх шагов не видна вовсе. А вопрос к нему всегда один и тот же: «изменились
только мои правки или заодно уехало чужое». Руками он решается дважды — до
импорта (что повезём) и после (что приехало), и оба раза одинаково.

Запуск (с хоста, файлы — обычные пути):
    python3 scripts/workflow_export_diff.py БЫЛО.json СТАЛО.json

Порядок работы с продом, ради которого скрипт и написан:

    1. снять ноду прода в файл          → backup_prod.json
    2. СВЕРИТЬ локальный с бэкапом      → что повезём
    3. импорт
    4. снять ноду прода снова           → after_prod.json
    5. СВЕРИТЬ бэкап с after            → что приехало
    6. СВЕРИТЬ локальный с after        → должно быть пусто везде

Шаг 6 — тот, который ловит потерю: диффа 2 и 5 совпали, а нода всё равно не
такая, как локальная, значит импорт что-то не донёс.

## ⚠⚠ Сверка идёт по ИМЕНАМ, а не по номерам

Номера записей на установках свои: при импорте занятый чужим `id` шага заставляет
перенумеровать все шаги файла (`ai_workflow_import.py`). Сверь по номерам — и
каждая такая перенумерация покажется правкой всей ноды.

Поэтому шаг адресуется парой «имя workflow / заголовок шага», тема — именем,
переменная — именем. Ровно так же адресует перенос (`workflow_topic.md` §6a).

⚠ Начинка шага (`metadata`) сравнивается строкой, байт в байт. Разбирать её
как JSON нельзя: часть шагов в живой базе не разбирается вовсе, и экспорт
везёт их дословно именно по этой причине.

⚠⚠ Своего знания о формате файла здесь нет: читаются те секции, которые кладёт
`ai_workflow_export.py`. Отсутствующая секция (файл старого формата, без тем) —
не ошибка, а пустой список: импорт считает темы необязательными, и сверка обязана
считать так же, иначе старый бэкап читался бы как «все темы снесли».
"""

import json
import sys

# Секции файла, сверяемые перечислением: что появилось, что исчезло. Пара —
# секция и поля, которыми запись зовут.
#
# ⚠⚠ У переменной адрес — имя И ТИП, а не одно имя. `girl_response` законно
# живёт двумя строками: `workflow` (её считает сам поток) и `input` (её подаёт
# родитель). По одному имени обе сливаются в одну, и появление второй — то
# есть ровно та правка, которой подпоток начинает видеть ответ агента, —
# сверке не видно вовсе.
WORKFLOW_EXPORT_DIFF_NAMED = (
    ('workflows', ('name',)),
    ('topic_groups', ('name',)),
    ('topics', ('name',)),
    ('variables', ('name', 'type')),
    ('node_variables', ('name', 'type')),
)

# Поля темы, правка которых меняет её поведение. Остальные (`id`, метки времени)
# на установках свои и о правке не говорят ничего.
WORKFLOW_EXPORT_DIFF_TOPIC_FIELDS = (
    'title', 'tags', 'tags_qty_accept', 'questions_qty_yes_accept',
    'instructions', 'is_enabled',
)


def workflow_export_diff(before: dict, after: dict) -> dict:
    """Что отличает два файла ноды. Пустые списки во всех ключах — файлы равны.

    Args:
        before: файл-«было» (разобранный JSON секции `result` экспорта).
        after: файл-«стало».

    Returns:
        dict: ключ на вид расхождения, значение — список строк для человека.
        `appeared`/`vanished` на каждую именную секцию, плюс `steps_moved`
        (шаг переехал позицией), `steps_changed` (правлена начинка),
        `topics_changed` (правлена тема).
    """
    out = {}

    for section, fields in WORKFLOW_EXPORT_DIFF_NAMED:
        was = _workflow_export_diff_keys(before.get(section), fields)
        now = _workflow_export_diff_keys(after.get(section), fields)
        out[f'{section}_appeared'] = sorted(now - was)
        out[f'{section}_vanished'] = sorted(was - now)

    steps_was = _workflow_export_diff_steps(before)
    steps_now = _workflow_export_diff_steps(after)

    out['steps_appeared'] = [_workflow_export_diff_step_name(key)
                             for key in sorted(steps_now.keys() - steps_was.keys())]
    out['steps_vanished'] = [_workflow_export_diff_step_name(key)
                             for key in sorted(steps_was.keys() - steps_now.keys())]

    moved, changed = [], []
    for key in sorted(steps_was.keys() & steps_now.keys()):
        one, two = steps_was[key], steps_now[key]
        if one.get('position') != two.get('position'):
            moved.append(f'{_workflow_export_diff_step_name(key)}: '
                         f'{one.get("position")} → {two.get("position")}')
        if (one.get('metadata') or '') != (two.get('metadata') or ''):
            changed.append(_workflow_export_diff_step_name(key))
    out['steps_moved'] = moved
    out['steps_changed'] = changed

    topics_was = {str(t.get('name')): t for t in before.get('topics') or []}
    topics_now = {str(t.get('name')): t for t in after.get('topics') or []}
    out['topics_changed'] = [
        name for name in sorted(topics_was.keys() & topics_now.keys())
        if any(topics_was[name].get(field) != topics_now[name].get(field)
               for field in WORKFLOW_EXPORT_DIFF_TOPIC_FIELDS)]

    asked_was = _workflow_export_diff_questions(before)
    asked_now = _workflow_export_diff_questions(after)
    out['topic_questions_appeared'] = sorted(asked_now - asked_was)
    out['topic_questions_vanished'] = sorted(asked_was - asked_now)

    return out


def workflow_export_diff_report(diff: dict) -> str:
    """Расхождения словами. Равные файлы дают одну строку, а не двенадцать пустых."""
    lines = []
    for kind, rows in diff.items():
        if not rows:
            continue
        lines.append(f'=== {kind} ({len(rows)}) ===')
        lines.extend(f'  {row}' for row in rows)
        lines.append('')

    return '\n'.join(lines) if lines else 'файлы равны: ни одного расхождения'


def _workflow_export_diff_keys(rows, fields: tuple) -> set:
    """Адреса записей секции. Нет секции (файл старого формата) — пустое множество."""
    return {' / '.join(str(row.get(field)) for field in fields)
            for row in rows or []}


def _workflow_export_diff_questions(payload: dict) -> set:
    """Вопросы тем, адресованные парой «имя темы / текст вопроса».

    ⚠ Именно текстом: номер вопроса на установках свой, а правка текста — это и
    есть правка вопроса. Переписанный вопрос показывается парой «исчез/появился»,
    и так честнее: сверке неоткуда знать, что это он же.
    """
    topics = {row.get('id'): str(row.get('name'))
              for row in payload.get('topics') or []}

    return {f'{topics.get(row.get("topic_id"), "?")} / {row.get("question")}'
            for row in payload.get('topic_questions') or []}


def _workflow_export_diff_steps(payload: dict) -> dict:
    """Шаги файла, адресованные парой «имя workflow / заголовок шага».

    ⚠ Номер workflow переводится в имя здесь, а не в вызывающем: пара — это и
    есть адрес шага, и собирать его по месту значило бы повторить перевод в
    каждой сверке.
    """
    names = {row.get('id'): str(row.get('name'))
             for row in payload.get('workflows') or []}

    return {(names.get(row.get('workflow_id'), '?'), str(row.get('title'))): row
            for row in payload.get('steps') or []}


def _workflow_export_diff_step_name(key: tuple) -> str:
    """Адрес шага одной строкой."""
    return f'{key[0]} / {key[1]}'


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('python3 scripts/workflow_export_diff.py БЫЛО.json СТАЛО.json')
        sys.exit(2)

    def _read(path: str) -> dict:
        """Файл экспорта: и голый `result`, и целый ответ точки читаются равно."""
        with open(path, encoding='utf-8') as handle:
            got = json.load(handle)
        return got.get('result', got) if isinstance(got, dict) else got

    print(workflow_export_diff_report(
        workflow_export_diff(_read(sys.argv[1]), _read(sys.argv[2]))))
