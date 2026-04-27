from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


@router.post("/agent/list")
async def agent_list(request: Request):
    try:
        agent_names = request.app.state.agent_manager.list()
        active_name = "my_assistant"

        sorted_agents = [active_name] + [name for name in agent_names if name != active_name]

        return {"result": sorted_agents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/{name}")
async def agent_yml(request: Request, name: str):
    try:
        agent_yaml_dict = request.app.state.agent_manager.load_yaml(name)
        return agent_yaml_dict
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))