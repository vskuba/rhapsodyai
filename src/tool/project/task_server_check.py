"""
Пригодна ли среда подзадачи для работы: поднимется ли сервер на её коде.

Ветка подзадачи выкатывается от локального `master`, и если в нём лежит чужая
незаконченная работа (файл импортируется, а самого файла в коммите нет), сервер
над таким каталогом не стартует вовсе. Разработчик правил код, который негде
запустить, QA пытался проверять то, что не поднимается, и каждый такой круг жёг
попытку из `timeout_attempt_max` — при исправной работе и сломанном окружении.

Проверка детерминированная, поэтому её делает инструмент, а не ход агента: агент
за те же деньги потратил бы два обращения к оболочке и мог бы забыть про формат
ответа, а здесь — один импорт в подпроцессе за секунды и без токенов.

Проверяется именно импорт точки входа: это первое, что делает старт сервера, и
ровно там ломается недокоммиченный код. Поднимать контейнер отсюда нечем —
`docker` из `uvicorn` недоступен, да и не нужен: не импортируется — не поднимется.
"""
import asyncio
import os

# Каталоги подзадач заводит `task_worktree_ensure`; путь тот же, что у него.
TASK_SERVER_CHECK_WORKTREE_DIR = '.claude/worktrees/feature_task_'

# Точка входа сервера: её импорт тянет за собой все роутеры проекта.
TASK_SERVER_CHECK_ENTRY = 'main_uvicorn'

# Импорт исправного дерева укладывается в секунды; предел — на случай, когда чужой
# код на импорте лезет в сеть или в базу и там подвисает.
TASK_SERVER_CHECK_TIMEOUT_SEC = 120

# В отчёт и в промпт уходит причина, а не весь traceback: строка ошибки говорит
# всё, а сотня строк стека вытесняет из контекста саму подзадачу.
TASK_SERVER_CHECK_ERROR_MAX_CHARS = 400


async def task_server_check(subtask_id: int, work_dir: str = '') -> dict:
    """
    Проверяет, поднимется ли сервер на коде подзадачи.
     - subtask_id: ID подзадачи (project_task.id) — по нему находится её каталог
     - work_dir: корень репозитория; пусто — каталог, из которого работает приложение
    Returns:
        dict: Готовность среды, содержащая:
            env_ok (str): yes — код импортируется, сервер поднимется; no — нет.
            env_error (str): при no — причина одной строкой; при yes пустая строка.
            env_dir (str): каталог подзадачи, который проверяли.
    """
    directory = _worktree_dir(int(subtask_id or 0), str(work_dir or ''))
    if not os.path.isdir(directory):
        return _fail(directory, f'нет каталога подзадачи {directory}')

    code, output = await _import_run(directory)
    if code == 0:
        return {'env_ok': 'yes', 'env_error': '', 'env_dir': directory}

    return _fail(directory, output or f'импорт {TASK_SERVER_CHECK_ENTRY} завершился с кодом {code}')


def _worktree_dir(subtask_id: int, work_dir: str) -> str:
    """Каталог подзадачи. Пустой `work_dir` — рабочий каталог самого приложения."""
    root = work_dir.strip().rstrip('/') or os.getcwd()

    return f'{root}/{TASK_SERVER_CHECK_WORKTREE_DIR}{subtask_id}'


async def _import_run(directory: str) -> tuple[int, str]:
    """Импорт точки входа в подпроцессе: свой процесс не должен пострадать.

    Чужой модуль на импорте может занять порт, открыть пул или упасть так, что
    останется мусор в интерпретаторе, — поэтому отдельный процесс, а не `import`
    здесь же. Таймаут — не ошибка проверки, а её результат: импорт, который не
    кончается за две минуты, сервер тоже не поднимет.
    """
    process = await asyncio.create_subprocess_exec(
        'python3', '-c', f'import {TASK_SERVER_CHECK_ENTRY}',
        cwd=directory,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        output, _ = await asyncio.wait_for(process.communicate(), TASK_SERVER_CHECK_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 1, f'импорт не завершился за {TASK_SERVER_CHECK_TIMEOUT_SEC}с'

    return int(process.returncode or 0), _error_line(output.decode('utf-8', 'replace'))


def _error_line(text: str) -> str:
    """Причина из вывода: последняя содержательная строка, а не весь стек."""
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    if not lines:
        return ''

    # Последняя строка traceback — сам тип ошибки с сообщением; предпоследняя
    # часто указывает место, поэтому берём хвост, а не одну строку.
    tail = ' | '.join(lines[-2:])

    return tail[:TASK_SERVER_CHECK_ERROR_MAX_CHARS]


def _fail(directory: str, error: str) -> dict:
    return {'env_ok': 'no', 'env_error': error, 'env_dir': directory}
