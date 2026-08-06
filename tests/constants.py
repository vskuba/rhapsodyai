import os
from dotenv import load_dotenv

load_dotenv()

TEST_SESSION_UUID = "097824c7-c3d3-4925-a63f-bd685292a408"
# Agent id=9 ('dating_bot') exists in seeded data
TEST_SESSION_AGENT_ID = 9

# Единая учётка всех тестов — QA-пользователь из .env (QA_USERNAME / QA_PASSWORD).
#
# Не `test_runner`: `conftest._cleanup_test_users()` удаляет всех пользователей с
# префиксом `test_`, то есть сюита сносила собственную учётку и следующий прогон
# падал на 401. Имя `vova.tkachenko` под эту чистку не попадает.
#
# Права роли `qa` — полные (`auth_role.AUTH_ROLE_PERMISSIONS`); с view-набором
# тесты, создающие пользователей и роли, упирались бы в 403.
TEST_AUTH = {
    "username": os.environ.get("QA_USERNAME", "vova.tkachenko"),
    "password": os.environ.get("QA_PASSWORD", ""),
}

# Роль этой учётки — тесты сверяют её в ответах /auth/login и /auth/me.
TEST_AUTH_ROLE = "qa"
