#!/usr/bin/env python3
"""
Manual test script for Team and Task pages.
Запускается напрямую без pytest.
"""

import os

import requests
from dotenv import load_dotenv

from tests.constants import TEST_AUTH

load_dotenv()

# Учётка — та же, что у pytest-сюиты: QA-пользователь из TEST_AUTH.
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


def create_auth_session():
    """Создание авторизованной сессии."""
    if not TEST_AUTH['password']:
        raise Exception("QA_PASSWORD не задан ни в окружении, ни в .env.local — авторизоваться нечем")
    session = requests.Session()
    response = session.post(f'{BASE_URL}/auth/login', json=TEST_AUTH)
    if response.status_code != 200:
        raise Exception(f"Login failed: {response.text}")
    return session


def test_api_team_endpoint():
    """Проверка API endpoint для получения списка команды."""
    print("\n=== Testing /api/team endpoint ===")

    session = create_auth_session()

    # Test /api/team
    response = session.get(f'{BASE_URL}/api/team')
    print(f"GET /api/team - Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"  Found {len(data)} team members:")
        for member in data:
            print(f"    - {member['name']} ({member['role']}) - Status: {member['status']}")
    else:
        print(f"  ERROR: {response.text}")

    # Test /api/team/types
    response = session.get(f'{BASE_URL}/api/team/types')
    print(f"\nGET /api/team/types - Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"  Found {len(data)} task types:")
        for t in data:
            print(f"    - {t['name']}: {t['title']}")
    else:
        print(f"  ERROR: {response.text}")

    print("\n=== API Tests Complete ===")


def test_team_ping():
    """Проверка пинга члена команды."""
    print("\n=== Test: Team Ping ===")

    session = create_auth_session()

    # Получаем список команды
    response = session.get(f'{BASE_URL}/api/team')
    members = response.json()
    manager = next((m for m in members if m['name'] == 'Manager'), None)

    if manager:
        print(f"Manager ID: {manager['id']}")
        print(f"Initial status: {manager['status']}")
        print(f"Initial last_ping_at: {manager['last_ping_at']}")

        # Отправляем пинг
        ping_response = session.post(
            f'{BASE_URL}/api/team/ping',
            json={'member_id': manager['id']}
        )
        print(f"POST /api/team/ping - Status: {ping_response.status_code}")

        # Проверяем обновленный статус
        response = session.get(f'{BASE_URL}/api/team')
        members = response.json()
        manager = next((m for m in members if m['name'] == 'Manager'), None)

        print(f"Updated status: {manager['status']}")
        print(f"Updated last_ping_at: {manager['last_ping_at']}")

        if manager['status'] == 'active' and manager['last_ping_at'] is not None:
            print("\n✓ Team ping test PASSED")
        else:
            print("\n✗ Team ping test FAILED")
    else:
        print("Manager not found in team")


def test_html_pages():
    """Проверка HTML страниц."""
    print("\n=== Test: HTML Pages ===")

    session = create_auth_session()

    # Test /admin/team
    response = session.get(f'{BASE_URL}/admin/team')
    print(f"GET /admin/team - Status: {response.status_code}")

    if response.status_code == 200:
        # Проверяем наличие ключевых элементов
        if 'team-card' in response.text:
            print("  ✓ Found .team-card elements")
        else:
            print("  ✗ Missing .team-card elements")

        if 'Команда' in response.text:
            print("  ✓ Page title 'Команда' found")
        else:
            print("  ✗ Missing page title")
    else:
        print(f"  ERROR: {response.text}")

    # Test /admin/task
    response = session.get(f'{BASE_URL}/admin/task')
    print(f"\nGET /admin/task - Status: {response.status_code}")

    if response.status_code == 200:
        # Названия типов в разметке не ищем: селект `#newTaskType` наполняет JS
        # из `/api/team/types` (его отдельно проверяет test_api_team_endpoint).
        if 'newTaskType' in response.text:
            print("  ✓ Found #newTaskType select")
        else:
            print("  ✗ Missing #newTaskType select")

        if 'phaseTabs' in response.text:
            print("  ✓ Found #phaseTabs (фазы задач)")
        else:
            print("  ✗ Missing #phaseTabs")

        if 'Задачи' in response.text:
            print("  ✓ Page title 'Задачи' found")
        else:
            print("  ✗ Missing page title")
    else:
        print(f"  ERROR: {response.text}")


def main():
    """Запуск всех тестов."""
    print("=" * 50)
    print("RhapsodyAi - Manual Tests for Team and Task Pages")
    print("=" * 50)

    try:
        test_api_team_endpoint()
        test_team_ping()
        test_html_pages()

        print("\n" + "=" * 50)
        print("All tests completed!")
        print("=" * 50)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
