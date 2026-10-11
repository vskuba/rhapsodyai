"""Приметы шагов `testing_tool_invoke` — вызова инструмента из workflow."""

AGENT = 'testing_tool_invoke'

STEP_TOOL = 'Счётчик'
STEP_FINAL = 'Финал'

# Шаг зовёт `counter_increment` с шагом `_const_5`: литерал карты, а не
# переменная. Проверяется и он.
TOOL_STEP = 5
