"""
Точка `GET /workflow/export` — HTTP-слой над `src/ai/ai_workflow_export.py`.

Здесь только разбор пути, права и превращение доменной ошибки в HTTP-статус;
формат файла, что в него едет и почему — в доменном модуле, там и правят.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.ai.ai_workflow_export import (
    AiWorkflowExportNodeMissingError,
    ai_workflow_export_payload,
)
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/workflow/export")
async def workflow_export(
        node_id: str,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    """
    Все workflow выбранной ноды одним файлом: строки, шаги, переменные, связи.

    `node_id` — число или `none` (псевдонода «Вне нод», `node_id IS NULL`).
    Ответ пригоден для `POST /workflow/import` как есть.
    """
    try:
        payload = await ai_workflow_export_payload(_workflow_export_node_pk(node_id))
    except AiWorkflowExportNodeMissingError as error:
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
