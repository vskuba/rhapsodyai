import pytest
from httpx import AsyncClient

# Замените URL на ваш адрес сервера для тестирования
BASE_URL = "http://localhost:8011"

@pytest.mark.asyncio
async def test_variable_crud():
    async with AsyncClient(base_url=BASE_URL) as client:
        await client.post(
            "/auth/login",
            json={"username": "user1", "password": "admin123"},
        )

        # 1. Создание
        payload = {
            "name": "test_var",
            "description": "desc",
            "default": "val",
            "node_id": 1,  # Убедитесь, что нода с ID=1 существует
            "role_ids": [1], # Убедитесь, что роль с ID=1 существует
            "pattern": "{}"
        }
        response = await client.post("/agent_workflow_variable", json=payload)
        assert response.status_code == 200
        variable_id = response.json()["result"]["id"]

        # 2. Чтение
        response = await client.get("/agent_workflow_variable/list")
        assert response.status_code == 200
        variables = response.json()["result"]
        assert any(v["id"] == variable_id for v in variables)

        # 3. Обновление
        update_payload = payload.copy()
        update_payload["name"] = "updated_var"
        response = await client.put(f"/agent_workflow_variable/{variable_id}", json=update_payload)
        assert response.status_code == 200

        # 4. Удаление
        response = await client.delete(f"/agent_workflow_variable/{variable_id}")
        assert response.status_code == 200

        # Проверка удаления
        response = await client.get("/agent_workflow_variable/list")
        variables = response.json()["result"]
        assert not any(v["id"] == variable_id for v in variables)
