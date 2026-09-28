"""
Точка `POST /workflow/import` — HTTP-слой над `src/ai/ai_workflow_import.py`.

Здесь только права, упаковка ответа и превращение доменной ошибки в
HTTP-статус; проверка файла, транзакция и порядок записи — в доменном модуле,
там и правят.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.ai.ai_workflow_import import (
    AiWorkflowImportConflictError,
    AiWorkflowImportFailedError,
    AiWorkflowImportRejectedError,
    ai_workflow_import_apply,
)
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.post("/workflow/import")
async def workflow_import(
        data: dict,
        user=Depends(AuthChecker([
            AuthPermission.WORKFLOW_CREATE,
            AuthPermission.WORKFLOW_DELETE,
            AuthPermission.WORKFLOW_VARIABLE_CREATE,
            AuthPermission.WORKFLOW_VARIABLE_UPDATE,
        ]))
):
    """
    Замена workflow ноды, чей это файл. Остальные ноды не трогаются.

    Одна транзакция: любая ошибка — откат, база как была. Совпадения на чужих
    записях: id или имя workflow занято чужим → 409; id шага занят чужим
    workflow → все шаги файла получают новые id, ссылки переписывает
    `ai_workflow_step_refs_remap`.
    """
    actor = getattr(user, 'username', None) or getattr(user, 'id', None)
    try:
        result = await ai_workflow_import_apply(data, actor)
    except AiWorkflowImportRejectedError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AiWorkflowImportConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except AiWorkflowImportFailedError as error:
        raise HTTPException(status_code=500, detail=str(error))
    return {"status": "success", "result": result}
