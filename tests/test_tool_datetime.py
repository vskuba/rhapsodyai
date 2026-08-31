import pytest
from src.tool.datetime_.datetime_ import datetime_current_get

pytestmark = pytest.mark.ai


@pytest.mark.asyncio
async def test_datetime_current_get():
    # Test default timezone (0)
    result = await datetime_current_get()
    assert "Сегодня" in result
    assert "года" in result
    assert "UTC" in result

    # Test positive timezone (+3)
    result_plus = await datetime_current_get("+3")
    assert "UTC+3" in result_plus

    # Test negative timezone (-5)
    result_minus = await datetime_current_get("-5")
    assert "UTC-5" in result_minus
