"""Удаление шага: отказ, пока на него ведут переходы других шагов.

## ⚠⚠ Что здесь стережётся и какой ценой узнано

14.10.2026 в `dating_talk_intention` (#76) выход «Вернуть LLM ответ» (#819)
заменили правильным «Вернуть текстовый ответ» (#6586): новый шаг завели в
11:34:56, старый удалили в 11:35:01. Через UI, одной кнопкой, без единого
предупреждения. А переходы на #819 остались у двух шагов — «Вопросы намерений»
(`transitions_before`) и «Намерения найдены?» (`transitions_after`), — и живой
чат встал:

    KeyError: 819
      ai_framework_manager.py:634  step_index = workflow_steps_mapping[target_step_id]

⚠⚠ Падал **каждый** прогон, дошедший до шага с висячим переходом, а не только
тот, где условие истинно: движок достаёт индекс цели ДО проверки условия. За
восемнадцать минут — десять прогонов в `error`, из них пять верхнего уровня
`dating_talk`, то есть столько же неотвеченных собеседников.

⚠ Внешним ключом это не ловится никогда: цель перехода лежит **строкой внутри
JSON `metadata` чужого шага**, и база про такую ссылку не знает. Значит ловить
её — ручке удаления, другого места нет.

⚠ Граф в редакторе про висячий переход говорил и раньше (`graph.js`, «переход
на несуществующий шаг»), но только тому, кто откроет граф. Удаляют — не открыв.

⚠ Клиент заводится прямо здесь, как у соседних сюит: общий пул слоя
(`http_pool_transport`) — про живые выходы в бою, а тесту нужна своя сессия с
логином и коротким сроком ожидания.
"""
import json
import os
import time

import httpx
import pytest

from src.ai.ai_workflow import ai_workflow_step_refs_find
from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

RUN = int(time.time())
WF_NAME = f"twsd_refs_{RUN}"


class TestStepRefsFind:
    """Форма ссылки: что считается переходом на шаг, а что — нет."""

    def test_both_forms_of_step_id_are_found(self):
        """⚠ Редактор кладёт число, перенос между базами — строку. Обе — ссылка."""
        metadata = json.dumps({
            "transitions_before": [{"variable": "x", "operator": "empty",
                                    "value": "", "step_id": "819"}],
            "transitions_after": [{"variable": "y", "operator": "==",
                                   "value": "1", "step_id": 744}],
        })
        assert ai_workflow_step_refs_find(metadata) == {819, 744}

    def test_result_variable_name_is_not_a_jump(self):
        """⚠⚠ `%..._819_result_str%` — имя переменной, а не цель перехода.

        Считай мы его ссылкой, удаление шага запрещал бы любой прочитанный
        результат — а он прогон не роняет: имя просто становится
        неопределённым, и об этом есть свой указатель в редакторе.
        """
        metadata = json.dumps({"prompt_user": "%companion_session_history_819_result_str%"})
        assert ai_workflow_step_refs_find(metadata) == set()

    def test_nothing_in_nothing(self):
        """⚠ Пустые метаданные законны: у шага без переходов их и нет."""
        assert ai_workflow_step_refs_find('') == set()
        assert ai_workflow_step_refs_find('{}') == set()


class TestStepDeleteRefs:
    """Ручка удаления: отказ со списком ссылающихся, и шаг остаётся жив."""

    async def test_referenced_step_is_not_deleted(self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Главный случай: ровно та поломка, из-за которой встал прод."""
        response = await client.delete(
            f"/workflow/{probe['workflow_id']}/step/{probe['target']}")
        assert response.status_code == 409, response.text

        steps = (await client.get(f"/workflow/{probe['workflow_id']}/steps")).json()["result"]
        assert probe['target'] in {one['id'] for one in steps}, \
            'шаг удалён, хотя на него ведут переходы'

    async def test_refusal_names_every_referrer(self, client: httpx.AsyncClient, probe: dict):
        """⚠ Человеку нужен список, а не слово «нельзя»: чинить — в тех шагах.

        Названы оба рода ссылки: `transitions_before` одного шага и
        `transitions_after` другого.
        """
        response = await client.delete(
            f"/workflow/{probe['workflow_id']}/step/{probe['target']}")
        detail = response.json()["detail"]

        assert str(probe['referrer_before']) in detail, detail
        assert str(probe['referrer_after']) in detail, detail
        assert 'Ведёт сюда до' in detail and 'Ведёт сюда после' in detail, detail

    async def test_unreferenced_step_deletes_as_before(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠ Отказ — только при ссылке: обычное удаление не тронуто."""
        response = await client.delete(
            f"/workflow/{probe['workflow_id']}/step/{probe['referrer_after']}")
        assert response.status_code == 200, response.text

    async def test_delete_goes_through_once_references_are_gone(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠ Отказ снимаемый: убрали переходы — шаг удаляется.

        Иначе застава стала бы ловушкой: удалить было бы нельзя никогда.
        """
        for step_id in (probe['referrer_before'], probe['referrer_after']):
            fixed = await client.put(
                f"/workflow/{probe['workflow_id']}/step/{step_id}",
                json={"metadata": json.dumps({"transitions_before": [],
                                              "transitions_after": []})})
            assert fixed.status_code == 200, fixed.text

        response = await client.delete(
            f"/workflow/{probe['workflow_id']}/step/{probe['target']}")
        assert response.status_code == 200, response.text

    async def test_step_referencing_itself_is_deletable(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠ Петля на себя удалению не мешает: висячей ссылки после неё не остаётся."""
        looped = await client.put(
            f"/workflow/{probe['workflow_id']}/step/{probe['referrer_after']}",
            json={"metadata": json.dumps({"transitions_after": [
                {"variable": "y", "operator": "exists", "value": "",
                 "step_id": probe['referrer_after']}]})})
        assert looped.status_code == 200, looped.text

        response = await client.delete(
            f"/workflow/{probe['workflow_id']}/step/{probe['referrer_after']}")
        assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Приватное: одноразовый workflow из трёх шагов — цель и двое ссылающихся
# ---------------------------------------------------------------------------

@pytest.fixture
async def client():
    logged = httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0)
    response = await logged.post("/auth/login", json=TEST_AUTH)
    assert response.status_code == 200, response.text
    try:
        yield logged
    finally:
        await logged.aclose()


@pytest.fixture
async def probe(client: httpx.AsyncClient):
    built = await _build_probe(client)
    try:
        yield built
    finally:
        await client.delete(f"/workflow/{built['workflow_id']}")


async def _build_probe(client: httpx.AsyncClient) -> dict:
    """Workflow, шаг-цель и два шага, ведущих на него разными видами перехода."""
    created = await client.post("/workflow", json={
        "name": WF_NAME, "title": f"Проба {WF_NAME}"})
    assert created.status_code == 200, created.text
    workflow_id = created.json()["result"]["id"]

    type_ids = {one["name"]: one["id"] for one in
                (await client.get("/workflow_step/list")).json()["result"]}
    step_type = type_ids.get('return_response_text') or next(iter(type_ids.values()))

    # ⚠ Заголовок шагу даёт **правка**, а не заведение: POST ставит имя по типу
    # шага, и переданное ему `title` до базы не доезжает. Редактор делает так же
    # — заводит шаг кнопкой, имя доносит автосохранением.
    target, referrer_before, referrer_after = [
        (await client.post(f"/workflow/{workflow_id}/step",
                           json={"type_id": step_type, "position": at})).json()["result"]
        for at in (0, 1, 2)]

    await client.put(f"/workflow/{workflow_id}/step/{target}",
                     json={"title": "Цель перехода"})

    # ⚠ Номер цели кладём в обе формы разом — строкой у одного шага, числом у
    # другого: редактор пишет одну, перенос между базами приносит другую, и
    # ручка обязана знать обе.
    await client.put(f"/workflow/{workflow_id}/step/{referrer_before}", json={
        "title": "Ведёт сюда до",
        "metadata": json.dumps({"transitions_before": [
            {"variable": "x", "operator": "empty", "value": "",
             "step_id": str(target)}]})})

    await client.put(f"/workflow/{workflow_id}/step/{referrer_after}", json={
        "title": "Ведёт сюда после",
        "metadata": json.dumps({"transitions_after": [
            {"variable": "y", "operator": "==", "value": "1",
             "step_id": target}]})})

    return {"workflow_id": workflow_id, "target": target,
            "referrer_before": referrer_before, "referrer_after": referrer_after}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
