import yaml
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
        path = request.app.state.agent_manager.filepath_get(name)

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        return {"raw_yaml": content}  # Возвращаем именно в таком ключе

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл не найден")


@router.put("/agent/{name}")
async def save_agent_yml(request: Request, name: str, data: dict):
    try:
        # 1. Извлекаем контент из JSON-тела запроса
        new_content: str = data.get("yaml_content", '')
        if not new_content:
            raise HTTPException(status_code=400, detail="Контент пуст")

        # 2. ПРОВЕРКА: Пытаемся распарсить YAML. Если там ошибка (например, лишний пробел),
        # yaml.safe_load выкинет исключение и мы НЕ запишем битый файл.
        try:
            yaml.safe_load(new_content)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=400, detail=f"Ошибка синтаксиса YAML: {str(exc)}")

        # 3. Записываем файл
        path = request.app.state.agent_manager.filepath_get(name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return {"status": "success", "message": f"Файл {name}.yml обновлен"}

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл для записи не найден")
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Системная ошибка: {str(e)}")
