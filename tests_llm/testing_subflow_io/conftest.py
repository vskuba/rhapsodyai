"""Приметы шагов `testing_subflow_io` — карт входа и выхода подпотока."""

AGENT = 'testing_subflow_io'

STEP_CALL = 'Зов подпотока'
STEP_FINAL = 'Финал'

# Шаги подпотока: они приходят в маршрут подпрогонов, а не в главный.
STEP_CHILD_MOVE = 'Переложить'
STEP_CHILD_FINAL = 'Финал подпотока'
