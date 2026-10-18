"""
Точка `GET /workflow/export` — HTTP-слой над `src/ai/ai_workflow_export.py`.

Здесь только разбор пути, права и превращение доменной ошибки в HTTP-статус;
формат файла, что в него едет и почему — в доменном модуле, там и правят.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.ai.ai_workflow_export import (
    AiWorkflowExportNodeMissingError,
    AiWorkflowExportWorkflowMissingError,
    ai_workflow_export_payload,
)
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/workflow/export")
async def workflow_export(
        node_id: str = None,
        workflow_id: str = None,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    """
    Файл переноса: нода целиком или один открытый workflow — ровно одно из двух.

    `node_id` — число или `none` (псевдонода «Вне нод», `node_id IS NULL`).
    `workflow_id` — число: тогда в файле только этот workflow (`scope`
    подскажет импорту скоуп), а секций тем в файле не будет вовсе.
    Ответ пригоден для `POST /workflow/import` как есть.
    """
    if (node_id is None) == (workflow_id is None):
        raise HTTPException(status_code=400,
                            detail='Ровно одно из двух: node_id или workflow_id')
    try:
        if workflow_id is not None:
            payload = await ai_workflow_export_payload(
                None, workflow_pk=_workflow_export_workflow_pk(workflow_id))
        else:
            payload = await ai_workflow_export_payload(_workflow_export_node_pk(node_id))
    except (AiWorkflowExportNodeMissingError,
            AiWorkflowExportWorkflowMissingError) as error:
        raise HTTPException(status_code=404, detail=str(error))
    return {"result": payload}


def _workflow_export_node_pk(raw):
    """`none` → псевдонода «Вне нод», число → id ноды."""
    raw = (raw or '').strip()
    if raw.lower() == 'none':
        return None
    if not raw.isdigit():
        raise HTTPException(status_code=400, detail='node_id — число или «none»')
    return int(raw)


def _workflow_export_workflow_pk(raw):
    """Только число: у workflow псевдоноды нет, нечисловой id — ошибка пути."""
    raw = (raw or '').strip()
    if not raw.isdigit():
        raise HTTPException(status_code=400, detail='workflow_id — число')
    return int(raw)
