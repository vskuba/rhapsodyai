"""Переменные `.env` для фронтенда: состав ключей и поведение при пустом значении.

Черновик тестов сгенерирован локальной моделью GX10, импорт и docstring поправлены
руками — она не видит репозитория и назвала модуль наугад.
"""
from src.setting.setting_config import SETTING_CONFIG_PUBLIC_KEYS, setting_config_public
import pytest

pytestmark = pytest.mark.core


def test_all_keys_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SITE_LOGIN_REMOTE_URL", "remote")
    monkeypatch.setenv("TELEGRAM_SITE_LOGIN_LOCAL_URL", "local")
    monkeypatch.setenv("DEEPSEEK_HARNESS_GX10", "gx10")

    result = setting_config_public()

    assert set(result.keys()) == set(SETTING_CONFIG_PUBLIC_KEYS.keys())
    assert result["SITE_LOGIN_REMOTE_URL"] == "remote"
    assert result["SITE_LOGIN_LOCAL_URL"] == "local"
    assert result["DEEPSEEK_HARNESS_GX10"] == "gx10"


def test_unset_variable_returns_empty_string(monkeypatch):
    monkeypatch.delenv("TELEGRAM_SITE_LOGIN_REMOTE_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_SITE_LOGIN_LOCAL_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_HARNESS_GX10", raising=False)

    result = setting_config_public()

    assert result["SITE_LOGIN_REMOTE_URL"] == ""
    assert result["SITE_LOGIN_LOCAL_URL"] == ""
    assert result["DEEPSEEK_HARNESS_GX10"] == ""


def test_telegram_prefix_stripped_in_key_name(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SITE_LOGIN_REMOTE_URL", "val1")
    monkeypatch.setenv("TELEGRAM_SITE_LOGIN_LOCAL_URL", "val2")
    monkeypatch.setenv("DEEPSEEK_HARNESS_GX10", "val3")

    result = setting_config_public()

    assert "SITE_LOGIN_REMOTE_URL" in result
    assert "SITE_LOGIN_LOCAL_URL" in result
    assert "DEEPSEEK_HARNESS_GX10" in result
    assert "TELEGRAM_SITE_LOGIN_REMOTE_URL" not in result
    assert "TELEGRAM_SITE_LOGIN_LOCAL_URL" not in result
