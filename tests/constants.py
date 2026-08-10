import os
from dotenv import dotenv_values, load_dotenv

load_dotenv()

# QA_USERNAME/QA_PASSWORD лежат в `.env.local`, а не в `.env`: `.env` пересобирается
# из секрета ENV_FILE при деплое, и креды автотестов оттуда пропадают — вся сюита
# начинает падать на 400 при логине. Поэтому берём их как fallback из `.env.local`,
# ничего не перетирая: MYSQL_HOST и порты тестам нужны именно из `.env`.
_ENV_LOCAL = dotenv_values(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env.local'))


def constants_env_get(name: str, default: str = '') -> str:
    return os.environ.get(name) or _ENV_LOCAL.get(name) or default

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
    "username": constants_env_get("QA_USERNAME", "vova.tkachenko"),
    "password": constants_env_get("QA_PASSWORD"),
}

# Роль этой учётки — тесты сверяют её в ответах /auth/login и /auth/me.
TEST_AUTH_ROLE = "qa"
