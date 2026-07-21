from fastapi import APIRouter, Request, Depends

from src.mysql_.repository.plan_repository import PlanRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/plan/list")
async def plan_list(request: Request, user=Depends(AuthChecker([AuthPermission.PLAN_VIEW]))):
    repo = PlanRepository()
    return {"result": await repo.find_by({}, "title ASC")}


@router.get("/plan/{plan_id}")
async def plan_get(request: Request, plan_id: int, user=Depends(AuthChecker([AuthPermission.PLAN_VIEW]))):
    repo = PlanRepository()
    return {"result": await repo.find(plan_id)}


@router.post("/plan")
async def plan_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLAN_CREATE]))):
    repo = PlanRepository()
    new_id = await repo.add({
        "node_id": data.get("node_id") or None,
        "user_id": data.get("user_id") or None,
        "title": data.get("title"),
        "content": data.get("content", ""),
        "status": data.get("status") or "active",
        "position": data.get("position", 0),
    })
    return {"result": new_id}


@router.put("/plan/{plan_id}")
async def plan_update(request: Request, plan_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLAN_UPDATE]))):
    repo = PlanRepository()
    return {"result": await repo.update(plan_id, {
        "node_id": data.get("node_id") or None,
        "user_id": data.get("user_id") or None,
        "title": data.get("title"),
        "content": data.get("content"),
        "status": data.get("status"),
        "position": data.get("position"),
    })}


@router.delete("/plan/{plan_id}")
async def plan_delete(request: Request, plan_id: int, user=Depends(AuthChecker([AuthPermission.PLAN_DELETE]))):
    repo = PlanRepository()
    return {"result": await repo.delete(plan_id)}
