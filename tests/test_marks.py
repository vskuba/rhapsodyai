"""
Каждый файл тестов принадлежит группе.

Зачем. Группы нужны, чтобы роль конвейера прогоняла задетое правкой, а не всю сюиту:
полный набор идёт три с половиной минуты, и платится это время на каждом круге.
Работает деление только при одном условии — размечено всё.

Файл без маркера не попадает ни в одну группу и **молча не запускается**: `pytest -m
pipeline` его не возьмёт, `-m team` тоже, и никакой жалобы не будет. Тест написан,
покрытие есть, а проверки нет — заметить это можно лишь специально ища.

Проверка идёт по собранным тестам, а не по тексту файлов: маркер можно поставить
файлу (`pytestmark`), классу или функции, и текстовый поиск все три случая не
покроет. Спрашиваем у самого pytest, что он видит.
"""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.core

# Группы по подсистемам — те же, что в `pyproject.toml`. Признаки стоимости
# (`integration`, `slow`) сюда не входят: они ставятся поперёк групп и группой не
# являются.
GROUPS = ('pipeline', 'team', 'browser', 'ai', 'auth', 'core', 'telegram')


def test_every_test_belongs_to_a_group():
    """
    Тестов вне групп быть не должно.

    Собираем всё, что не помечено ни одной группой. Пусто — разметка полная.
    """
    expression = ' and '.join(f'not {name}' for name in GROUPS)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:warnings',
         '-m', expression],
        capture_output=True, text=True, timeout=180)

    orphans = [line.split('::')[0] for line in result.stdout.splitlines() if '::' in line]

    assert not orphans, (
        'эти тесты не попадут ни в одну группу и не запустятся при прогоне по '
        f'маркеру: {sorted(set(orphans))}')


def test_groups_are_declared():
    """
    Каждая группа объявлена в конфиге.

    Незаявленный маркер pytest принимает молча (`-m выдумка` просто ничего не
    находит), и опечатка в `pytestmark` дала бы файл-невидимку с тем же исходом,
    что и полное отсутствие маркера.
    """
    config = open('pyproject.toml', encoding='utf-8').read()
    missing = [name for name in GROUPS if f'"{name}:' not in config]

    assert not missing, f'группы нет в markers пайпроджекта: {missing}'
