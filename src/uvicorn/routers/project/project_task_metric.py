"""
Статистика работы ролей — API вкладки «Статистика» на `/admin/task`.

Что показывает. Три величины на каждый шаг агента: сколько строк ему дали
прочесть (оценка менеджера при разбиении), сколько он работал и сколько токенов
при этом сгенерировала модель. Плюс сколько кода круг изменил.

Зачем. Порог разбиения по объёму и таймауты ролей сейчас — числа из головы.
Накопленные средние отвечают на три вопроса разом: каким ставить таймаут (по
хвосту, а не по среднему — срываются длинные круги), какой объём считать крупным
и сколько займёт план целиком.

Статистика задачу переживает: план сбрасывают, подзадачи удаляют пачками, а
замеры остаются (`project_task_metric` без FK). Иначе средние обнулялись бы ровно
тогда, когда по ним впервые захотели что-то посчитать. Убирают их отдельной
кнопкой, и средние тогда пересчитываются сами — они считаются запросом.

Механика замеров — `src/project/task/task_metric.py`.
"""
from fastapi import APIRouter, Depends, HTTPException

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.task.task_metric import (task_metric_by_llm, task_metric_by_llm_role,
                                          task_metric_task_summary,
                                          task_metric_delete, task_metric_parents,
                                          task_metric_rows, task_metric_summary,
                                          task_metric_totals)

router = APIRouter()


@router.get('/api/task/metric')
async def project_task_metric_list(parent_id: int = 0,
                                   user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Сводка, итоги и последние замеры одним ответом.

    Одним, а не тремя запросами: вкладка показывает их вместе, и раздельная
    загрузка дала бы моменты, когда сводка уже новая, а список ещё старый.

    `parent_id` — сузить до одной задачи. Ноль означает «по всем»: именно
    накопленное за всё время и говорит, каким ставить таймаут, — по одной задаче
    выборка слишком мала.
    """
    parent = int(parent_id) or None

    return {
        'summary': await task_metric_summary(parent),
        # Разрез по моделям: с пулом проекта круги идут на разных, и вопрос
        # «чем работать выгоднее» отвечается только этими двумя сводками.
        'by_llm': await task_metric_by_llm(parent),
        'by_llm_role': await task_metric_by_llm_role(parent),
        'totals':  await task_metric_totals(parent),
        'rows':    await task_metric_rows(parent),
        # Список разрезов строим по самим замерам: дерево задач на странице
        # зависит от выбранного проекта и бывает пустым, а удалённая задача
        # обязана остаться в выборе — её статистика жива.
        'parents': await task_metric_parents(),
        'parent_id': parent or 0,
    }


@router.get('/api/task/{task_id}/metric')
async def project_task_metric_task(task_id: int,
                                   user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Что стоила одна задача: вкладка «Статистика» на странице разбора.

    Дерево целиком — сама строка и её подзадачи: на странице разбора человек смотрит
    на задачу как на одно целое, и «сколько это стоило» для него включает работу всех
    исполнителей, а не только менеджера.

    Пустой ответ — не ошибка: замеров может не быть вовсе (задача старше таблицы либо
    круг ещё не кончился), и страница про это так и пишет.
    """
    return {'result': await task_metric_task_summary(task_id)}


@router.delete('/api/task/metric')
async def project_task_metric_remove(task_id: int = 0, parent_id: int = 0, reset: int = 0,
                                     user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Убрать замеры одной строки, дерева задачи или всей таблицы.

    Пересчитывать после удаления нечего: средние нигде не хранятся, их считает
    запрос по оставшимся строкам. Поэтому в ответ сразу отдаём новые итоги — по
    ним видно, что именно изменилось.

    `reset=1` — сброс всего накопленного: сравнение моделей идёт по средним, а те
    тянут за собой прошлое, и после смены пула или починки канала старые замеры
    показывают погоду позавчерашнего дня. Отдельным параметром, а не «вызовом без
    номеров»: обнулить всё случайно нельзя — накопленное не восстановить.

    Без номера и без флага — 400: пустой запрос молчаливо ничего не делал бы, и
    человек решил бы, что удаление не работает.
    """
    if not task_id and not parent_id and not reset:
        raise HTTPException(status_code=400,
                            detail='Укажите строку, задачу или reset=1 для полного сброса')

    removed = await task_metric_delete(task_id=int(task_id) or None,
                                       parent_id=int(parent_id) or None,
                                       reset_all=bool(reset))

    return {'ok': True, 'removed': removed, 'totals': await task_metric_totals()}
