from tests.constants import TEST_AUTH
import pytest
import requests
from tests.conftest import BASE_URL

pytestmark = pytest.mark.auth

@pytest.fixture
def session():
    """Create an authenticated session for tests."""
    s = requests.Session()
    # Log in as admin to have sufficient permissions
    login_res = s.post(f"{BASE_URL}/auth/login", json=TEST_AUTH)
    if login_res.status_code != 200:
        raise Exception("Login failed")
    return s

def test_role_crud(session):
    # 1. Create a role
    create_res = session.post(f"{BASE_URL}/role", json={"name": "test_role", "node_ids": []})
    assert create_res.status_code == 200
    role_id = create_res.json()["result"]["id"]
    
    # 2. Get list
    list_res = session.get(f"{BASE_URL}/role/list")
    assert list_res.status_code == 200
    assert any(r["id"] == role_id for r in list_res.json()["result"])
    
    # 3. Get details
    get_res = session.get(f"{BASE_URL}/role/{role_id}")
    assert get_res.status_code == 200
    assert get_res.json()["result"]["name"] == "test_role"
    
    # 4. Update
    update_res = session.put(f"{BASE_URL}/role/{role_id}", json={"name": "updated_role", "node_ids": []})
    assert update_res.status_code == 200
    
    get_updated = session.get(f"{BASE_URL}/role/{role_id}")
    assert get_updated.json()["result"]["name"] == "updated_role"
    
    # 5. Delete
    del_res = session.delete(f"{BASE_URL}/role/{role_id}")
    assert del_res.status_code == 200
    
    list_after_del = session.get(f"{BASE_URL}/role/list")
    assert not any(r["id"] == role_id for r in list_after_del.json()["result"])
