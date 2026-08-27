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
from src.project.task.task_metric import (task_metric_delete, task_metric_parents,
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
        'totals':  await task_metric_totals(parent),
        'rows':    await task_metric_rows(parent),
        # Список разрезов строим по самим замерам: дерево задач на странице
        # зависит от выбранного проекта и бывает пустым, а удалённая задача
        # обязана остаться в выборе — её статистика жива.
        'parents': await task_metric_parents(),
        'parent_id': parent or 0,
    }


@router.delete('/api/task/metric')
async def project_task_metric_remove(task_id: int = 0, parent_id: int = 0,
                                     user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Убрать замеры одной строки или всего дерева задачи.

    Пересчитывать после удаления нечего: средние нигде не хранятся, их считает
    запрос по оставшимся строкам. Поэтому в ответ сразу отдаём новые итоги — по
    ним видно, что именно изменилось.

    Без номера не делаем ничего, и это осознанно: «удалить всё» здесь неуместно.
    Накопленное не восстановить — оно копится кругами по сорок минут.
    """
    if not task_id and not parent_id:
        raise HTTPException(status_code=400,
                            detail='Укажите строку или задачу: удаление всей статистики не предусмотрено')

    removed = await task_metric_delete(task_id=int(task_id) or None,
                                       parent_id=int(parent_id) or None)

    return {'ok': True, 'removed': removed, 'totals': await task_metric_totals()}
