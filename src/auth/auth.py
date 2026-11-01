"""Вход и проверка прав: **дверь** к общему скелету `py_modules/panel_/`.

Своей копии механизма здесь больше нет. Модель прав при этом не менялась — её
**взяли отсюда**: у двух соседних проектов панель умела только `is_admin`, и
общим скелетом сделали богатый вариант, а не бедный.

Что уехало в слой: проверка права, разбор «кто пришёл» (сессия или токен),
правила про людей, точки `/api/users`. Что осталось здесь: каталог
(`auth_permission.py`, `auth_role.py`, `auth_field_policy.py` — не тронуты) и два
переходника, `auth_access.py` и `auth_store.py`.

## ⚠ Дверь, а не прямой импорт слоя по месту

`AuthChecker` стоит в 391 объявлении роутов, `AuthSession` — в 56. Переименовать
их в `panel_auth_need`/`PanelUser` значило бы тронуть почти полтысячи строк ради
того, чтобы имя стало другим, — и всё это в единственном месте, которое нельзя
сломать незаметно: право доступа.

⚠ `auth_token_of` остаётся видимым отсюда: его импортирует `main_uvicorn`.
Живёт он в общем слое (`auth_/auth_primitive.py`) и давно — здесь только
проходит насквозь.

## ⚠⚠ Два договора подключаются здесь, на импорте модуля

Не в `lifespan`: `AuthChecker` зовут и из тестов, которые приложение не
поднимают вовсе. Подключи мы договоры на старте — в таких прогонах права
остались бы незаведёнными, то есть полными у всех, и тест на отказ зеленел бы,
ничего не проверив.
"""

import hmac

from fastapi import HTTPException, Request, status

from auth_.auth_primitive import auth_token_of
from config.config import config_get
from dashboard.src.panel.panel_access import panel_access_use
from dashboard.src.panel.panel_auth import (PanelUser, panel_auth_need,
                               panel_auth_required as auth_get_current_user,
                               panel_auth_token_user)
from dashboard.src.panel.panel_store import panel_store_use

from src.auth.auth_access import AuthAccess
from src.auth.auth_permission import AuthPermission
from src.auth.auth_store import AuthStore

panel_access_use(AuthAccess())
panel_store_use(AuthStore())


class AuthChecker:
    """Зависимость роута: пускает того, у кого есть **все** названные права.

    ⚠ Класс, а не функция, потому что так её зовут 391 раз:
    `Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))`. Внутри — зависимость
    слоя, никакой своей проверки здесь не осталось.
    """

    def __init__(self, required_permissions: list):
        self.required_permissions = list(required_permissions or [])
        self._check = panel_auth_need(*self.required_permissions)

    async def __call__(self, request: Request) -> PanelUser:
        """⚠⚠ Аннотация `Request` **обязательна**. Без неё FastAPI считает
        довод с именем `request` обычным query-параметром и отвечает 422
        «Field required» на каждую точку, где стоит эта зависимость, — то есть
        на все 391. Поймано сюитой: `telegram` и `ai` покраснели разом.

        ⚠ Зависимость слоя просит `PanelUser` доводом, а FastAPI здесь даёт
        только запрос: разрешаем его сами и зовём проверку напрямую."""
        return await self._check(await auth_get_current_user(request))


async def auth_token_user(token: str) -> PanelUser:
    """Владелец токена. ⚠ Неизвестный — 401, а не безымянный гость."""
    user = await panel_auth_token_user(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail='Invalid API Key')

    return user


async def auth_token_valid(token: str) -> bool:
    """Настоящий ли это токен — без разговора о том, что владельцу можно.

    Нужна заставе `auth_middleware`: та решает «пускать ли дальше», а права
    спрашивает роутер. Раньше заставе хватало того, что заголовок **есть**, и
    `Authorization: Bearer deadbeef` открывал любую точку без `AuthChecker`.

    ⚠ Отдельно от `auth_token_user`, потому что ответы разные: та поднимает
    401, а заставе нужен ответ «да/нет» — 401 она сочиняет свой, с тем же
    телом, что и для запроса вовсе без ключа.
    """
    return await panel_auth_token_user(token) is not None


def auth_claude_secret_ok(request: Request) -> bool:
    """Пришёл ли верный общий секрет claude-shell (`X-Claude-Secret`).

    Один ключ на всё, чем оболочка ходит сюда без сессии: реестр сессий Mini
    App, `/event-log`, heartbeat команды.

    ⚠⚠ Падает закрыто: секрет не задан в `.env` — ответ «нет», а не «нечего
    сравнивать, проходи». Иначе установка без настройки открывалась бы всем.

    ⚠ Сравнение `compare_digest`, а не `==`: по времени ответа секрет иначе
    подбирается побайтово.
    """
    expected = str(config_get('TELEGRAM_TOKEN_RHAPSODY') or '')
    provided = str(request.headers.get('X-Claude-Secret') or '')

    if not expected or not provided:
        return False

    return hmac.compare_digest(provided, expected)


def auth_claude_secret_need(request: Request) -> None:
    """Зависимость точек, которыми ходит claude-shell: нет секрета — 403.

    ```python
    @router.post('/ping', dependencies=[Depends(auth_claude_secret_need)])
    ```

    ⚠ Зависимостью, а не вызовом в теле: у этих точек довод тела уже зовётся
    `request` (`project_team_ping`), и второй `request: Request` в сигнатуру не
    встанет. Заодно видно при чтении объявления, чем точка закрыта.
    """
    if not auth_claude_secret_ok(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Not authorized')


__all__ = ['AuthChecker', 'AuthPermission', 'auth_claude_secret_need',
           'auth_claude_secret_ok', 'auth_get_current_user', 'auth_token_of',
           'auth_token_user', 'auth_token_valid']
