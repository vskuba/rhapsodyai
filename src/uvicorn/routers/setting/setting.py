"""Настройки установки: то, чего нет в общем скелете панели.

Список, правка, удаление и личные настройки человека уехали в слой
(`py_modules/panel_/panel_setting_api.py`, страница
`.claude/docs-common/panel.md`): они одинаковы у всех панелей, вместе с областью
узла — столбец `node_id` стоит в таблице у всех трёх проектов.

Здесь остаётся одна точка, аналога которой в слое нет и быть не должно:
конфигурационные переменные **для фронтенда этой установки**. Что именно
показывать браузеру — предметное знание, и собирает его `setting_config.py`.

⚠ Mini App ходит не сюда, а в `/telegram-app/config`: у него своя авторизация, и
`AuthChecker` его не пропускает.
"""

from fastapi import APIRouter, Depends

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.setting.setting_config import setting_config_public

router = APIRouter()


@router.get("/api/setting/config")
async def setting_config_route(user=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    """Конфигурационные переменные для фронтенда админки."""
    return {"result": setting_config_public()}
