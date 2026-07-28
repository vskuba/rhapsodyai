import os
from dotenv import load_dotenv

load_dotenv()

TEST_SESSION_UUID = "097824c7-c3d3-4925-a63f-bd685292a408"
# Agent id=9 ('dating_bot') exists in seeded data
TEST_SESSION_AGENT_ID = 9

# Shared auth credentials for all tests — loaded from .env (TEST_USERNAME / TEST_PASSWORD)
TEST_AUTH = {
    "username": os.environ.get("TEST_USERNAME", "test_runner"),
    "password": os.environ.get("TEST_PASSWORD", ""),
}
