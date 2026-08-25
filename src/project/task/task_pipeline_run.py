"""
Исполнители шагов конвейера: что делает воркер с захваченной строкой.

Тик (`task_pipeline_tick`) только выбирает работу и ставит её в очередь; этот
модуль — вторая половина. `task_pipeline_action_run` разбирает сообщение очереди
по `_RUNNERS` и зовёт нужный исполнитель. Здесь lives карта `_RUNNERS`, которая
перенаправляет по файлам: `task_run_plan_split` — разбивка плана,
`task_run_developer` — разработка, `task_run_qa` — проверка,
`task_run_bugfix` — исправление багов, `task_run_finalize` — финализация.

Шаги менеджера живут в `task_pipeline_manager`, повторы сорвавшихся прогонов —
в `task_pipeline_retry` (там же общие хвосты: `_subtask_dir`, `_log_run` и др.).

Соседние модули: `task_pipeline` — триггер и карта, `task_pipeline_claim` — отбор.
"""
from src.project.task.task_run_plan_split import _run_plan_split
from src.project.task.task_run_developer import _run_developer
from src.project.task.task_run_qa import _run_qa
from src.project.task.task_run_bugfix import _run_bugfix
from src.project.task.task_run_finalize import _run_finalize
from src.project.task.task_pipeline_manager import (
    _run_bug_scan,
    _run_manager_plan,
    _run_manager_review,
)


# Карта строится после определения шагов: имена должны быть уже объявлены.
_RUNNERS = {
    'bug_scan':       _run_bug_scan,
    'manager_review': _run_manager_review,
    'manager_plan':   _run_manager_plan,
    'plan_split':     _run_plan_split,
    'developer':      _run_developer,
    'qa':             _run_qa,
    'bugfix':         _run_bugfix,
    'finalize':       _run_finalize,
}
