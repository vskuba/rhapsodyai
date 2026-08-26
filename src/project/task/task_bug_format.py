"""
Форматирование title / description для баг-задач из workflow trace.

Публичные функции:
    task_bug_format_run_title — заголовок для run-level ошибки
    task_bug_format_run_description — описание для run-level ошибки
    task_bug_format_step_title — заголовок для step-level ошибки
    task_bug_format_step_description — описание для step-level ошибки
"""


def task_bug_format_run_title(workflow_title: str, error: str, duration_ms: int | None) -> str:
    """
    Заголовок баг-задачи из run-level ошибки.

    Args:
        workflow_title: Заголовок workflow из таблицы agent_workflow.
        error: Полный текст ошибки из agent_workflow_trace.error.
        duration_ms: Продолжительность в миллисекундах или None.

    Returns:
        Заголовок вида: «[Bug] {title} failed after {duration} — {exception_short}»
    """
    duration = _human_duration_ms(duration_ms)
    exception_short = _exception_short(error)
    return f'[Bug] {workflow_title} failed after {duration} — {exception_short}'


def task_bug_format_run_description(workflow_title: str, agent_name: str | None,
                             error: str, duration_ms: int | None,
                             started_at: str, finished_at: str) -> str:
    """
    Описание баг-задачи из run-level ошибки.

    Args:
        workflow_title: Заголовок workflow.
        agent_name: Имя агента или None.
        error: Полный текст ошибки.
        duration_ms: Длительность в миллисекундах или None.
        started_at: Время начала запуска.
        finished_at: Время окончания запуска.

    Returns:
        Описание в структурированном виде.
    """
    duration = _human_duration_ms(duration_ms)
    desc_lines = [
        f'Workflow: {workflow_title}',
    ]
    if agent_name:
        desc_lines.append(f'Agent: {agent_name}')
    desc_lines.extend([
        f'Duration: {duration}',
        f'Started: {started_at}',
        f'Finished: {finished_at}',
        '',
        'Error:',
        error.strip(),
    ])
    return '\n'.join(desc_lines)


def task_bug_format_step_title(workflow_title: str, step_title: str, step_type: str,
                               error: str) -> str:
    """
    Заголовок баг-задачи из step-level ошибки.

    Args:
        workflow_title: Заголовок workflow.
        step_title: Название шага из agent_workflow_trace_step.step_title.
        step_type: Тип шага (tool, llm, rule и т.д.).
        error: Текст ошибки шага.

    Returns:
        Заголовок вида: «[Bug] {title} step \"{step}\" failed — {exception_short}»
    """
    exception_short = _exception_short(error)
    return f'[Bug] {workflow_title} step "{step_title}" ({step_type}) failed — {exception_short}'


def task_bug_format_step_description(workflow_title: str, step_title: str, step_type: str,
                                     step_id: int, error: str,
                                     variables_changed: str | None) -> str:
    """
    Описание баг-задачи из step-level ошибки.

    Args:
        workflow_title: Заголовок workflow.
        step_title: Название шага.
        step_type: Тип шага.
        step_id: ID шага для trace_meta.
        error: Текст ошибки.
        variables_changed: JSON изменений переменных или None.

    Returns:
        Описание в структурированном виде.
    """
    desc_lines = [
        f'Workflow: {workflow_title}',
        f'Step: {step_title} ({step_type})',
        f'Step ID: {step_id}',
        '',
        'Error:',
        error.strip(),
    ]
    if variables_changed:
        desc_lines.extend([
            '',
            'Variables changed:',
            variables_changed.strip(),
        ])
    return '\n'.join(desc_lines)


# ── Детали реализации ──────────────────────────────────────────────────────────


def _human_duration_ms(duration_ms: int | None) -> str:
    """Миллисекунды → человекочитаемая строка."""
    if duration_ms is None or duration_ms < 0:
        return 'unknown'
    total = duration_ms / 1000.0
    if total < 60:
        return f'{total:.0f}s'
    minutes = int(total // 60)
    seconds = total % 60
    if minutes < 60:
        return f'{minutes}m {seconds:.0f}s'
    hours = minutes // 60
    minutes = minutes % 60
    return f'{hours}h {minutes}m'


def _exception_short(error: str, max_len: int = 60) -> str:
    """Первая значимая часть ошибки — до первой пустой строки или max_len символов."""
    if not error:
        return ''
    # Первая строка traceback — обычно это класс исключения
    first_line = error.strip().split('\n')[0].strip()
    if len(first_line) <= max_len:
        return first_line
    return first_line[:max_len - 3] + '...'
