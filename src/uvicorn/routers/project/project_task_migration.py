"""
Ручные миграции подзадачи — API вкладки «Миграции» на странице слияния.

Зачем здесь, а не отдельной страницей. Правка кода и правка данных приезжают
одной работой: переименовали функцию инструмента — надо обновить `tool_name` в
шагах workflow, иначе после слияния сломается то, что звало её по имени. Разнеси
эти две вещи по разным экранам — и вторую забудут. Поэтому миграции живут
вкладкой рядом с diff, на том же экране, где жмут merge.

Файлы берутся **из каталога подзадачи**, а не из master: миграция лежит в ветке
рядом с кодом, который её требует, и до слияния в master её нет.

Целевая база — параметр применения (`migration_manual`). Пока она всегда рабочая,
но когда появится тестовая, та же кнопка будет прогонять туда проверку, а сюда —
уже проверенное. Двух путей для этого заводить не придётся.

Механика — `src/mysql_/migration/migration_file.py`, песочница — `migration_sandbox.py`.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.migration.migration_file import (migration_file_apply,
                                                   migration_file_database,
                                                   migration_file_list)
from src.project.task.task_role import task_role_project_work_dir
from src.project.task.task_worktree import task_worktree_path

router = APIRouter()


class TaskMigrationApply(BaseModel):
    """Что применяем и как: сухим прогоном или по-настоящему."""
    name: str
    dry: bool = False


@router.get('/api/task/{task_id}/migration')
async def project_task_migration_list(task_id: int, all: int = 0,
                                      user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Миграции, **написанные этой задачей**, с их состоянием.

    Каталог подзадачи — полный чекаут репозитория, и без фильтра список отдавал все
    два десятка файлов проекта: свои одна-две тонули среди чужих, а рядом с каждой
    строкой стоит кнопка «Применить» — то есть чужую старую миграцию можно было
    прокатить по рабочей базе одним нажатием. Поэтому по умолчанию показываем только
    то, что ветка добавила поверх главной.

    `all=1` — показать все файлы каталога: изредка нужно посмотреть, что вообще
    лежит в ветке, и прятать это совсем было бы перегибом.

    Состояние — последняя запись журнала по каждому файлу: применяли ли, чем
    кончилось, сколько строк затронуло. Плюс признак `ddl`: у такого файла сухой
    прогон недоступен, и кнопку проверки страница прячет заранее, а не показывает
    отказ после нажатия.

    `own_unknown` — сравнить не с чем (каталог не ветка, git недоступен): список
    тогда полный, и страница об этом говорит, а не выдаёт чужие файлы за свои.
    """
    directory = await _task_dir(task_id)
    migrations = await migration_file_list(directory, own_only=not all)

    return {
        'migrations': migrations,
        'database': await migration_file_database(),
        'dir': directory,
        'own_unknown': any(m.get('own') is None for m in migrations),
        'all': bool(all),
    }


@router.post('/api/task/{task_id}/migration/apply')
async def project_task_migration_apply(task_id: int, body: TaskMigrationApply,
                                       user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Сухой прогон одной миграции: выполнить в транзакции и откатить.

    Настоящее применение отсюда убрано. Миграции применяет yoyo при старте uvicorn
    (`mysql_migration_up`), и после слияния ветки файл уезжает в master, где его
    прокатит ближайший деплой. Эта же точка гнала SQL мимо yoyo и писала результат в
    свой журнал — тот, про который в `_yoyo_applied` сказано «помнит проверки, а не
    применения». База менялась, yoyo об этом не знал и применял файл повторно при
    следующем старте: идемпотентная миграция это переживала, обычная падала или
    задваивала данные.

    `dry: false` теперь отвергается, а не игнорируется молча: запрос осмысленный, но
    делать этого больше нельзя, и человек (или чужой скрипт) должен об этом узнать.

    Ошибку выполнения возвращаем ответом, а не исключением: упавший запрос — это
    результат операции, о котором надо прочитать, а не сбой приложения. Отказ
    (404, 400) остаётся исключением — там читать нечего.
    """
    if not body.dry:
        raise HTTPException(
            status_code=400,
            detail='Применение убрано: миграции прокатывает yoyo при старте uvicorn '
                   'после слияния ветки. Здесь доступен только сухой прогон')

    directory = await _task_dir(task_id)
    result = await migration_file_apply(directory, body.name, dry=True, by=user.username)

    return {**result, 'migrations': await migration_file_list(directory, own_only=True)}


async def _task_dir(task_id: int) -> str:
    """
    Каталог подзадачи, где лежит её ветка вместе с миграциями.

    Каталога может не быть — строку ещё не брали в работу или уже влили и сняли
    выкладку. Тогда отдаём каталог проекта: в нём миграции из master, и это
    честный ответ «в ветке своих нет, вот общие».
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, project_id FROM project_task WHERE id = %s', (task_id,))
        row = await db.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='task not found')

    work_dir = await task_role_project_work_dir(row.get('project_id'))

    return task_worktree_path(work_dir, task_id) or work_dir
