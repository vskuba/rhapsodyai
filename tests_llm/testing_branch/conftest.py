"""Приметы шагов workflow `testing_branch` — развилки.

⚠ Заголовки сверяются с базой до прогона (`step_names_match` в общем
`conftest.py`): переименуют шаг на странице — тест упадёт за полсекунды с
готовым SQL, а не через минуту сообщением «ветка не сработала».
"""

# Имя агента ноды Testing, который гоняет этот workflow.
AGENT = 'testing_branch'

STEP_RED = 'Ветка: красная'
STEP_GREEN = 'Ветка: зелёная'
STEP_BLUE = 'Ветка: синяя'
STEP_FINAL = 'Финал'

# Все ветки разом — для проверки «сработала ровно одна».
STEP_BRANCHES = (STEP_RED, STEP_GREEN, STEP_BLUE)

# Какая ветка какой краской выбирается.
BRANCH_OF = {'red': STEP_RED, 'green': STEP_GREEN, 'blue': STEP_BLUE}
