# Auth — аутентификация и права доступа

> Session-based authentication with role-based access control (RBAC) and optional
> field-level policies. Сессия хранится в cookie, права проверяются зависимостью
> `AuthChecker`, публичные пути перечислены в middleware `main_uvicorn.py`.

## File Structure

```
src/
├── auth/
│   ├── auth.py              # AuthChecker dependency, get_current_user()
│   ├── auth_session.py      # AuthSession Pydantic model
│   ├── auth_role.py         # AuthRole enum + AUTH_ROLE_PERMISSIONS mapping
│   ├── auth_permission.py   # AuthPermission enum
│   └── auth_field_policy.py # Field-level read/write policy per role
└── uvicorn/routers/auth/
    └── auth.py              # /auth/login, /auth/logout, /auth/me endpoints
data/uvicorn/template/login.html  # Standalone login page
```

## Session Middleware (`main_uvicorn.py`)

```python
Middleware(
    SessionMiddleware,
    secret_key=config_get('SESSION_SECRET_KEY'),
    session_cookie="uvicorn_session",
    max_age=3600,
    same_site="lax",
    https_only=False
),
Middleware(BaseHTTPMiddleware, dispatch=auth_middleware),
```

`auth_middleware` protects `/admin/*` routes, redirects unauthenticated users to `/login`.

## AuthSession Model

```python
class AuthSession(BaseModel):
    user_id: int
    username: str
    role: str   # "admin" | "user"
```

## get_current_user()

```python
async def get_current_user(request: Request) -> AuthSession:
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    role = request.session.get("role")
    if not user_id or not username or not role:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return AuthSession(user_id=user_id, username=username, role=role)
```

## AuthChecker Dependency

```python
class AuthChecker:
    def __init__(self, required_permissions: list[AuthPermission]):
        self.required_permissions = required_permissions

    async def __call__(self, request: Request) -> AuthSession:
        current_user = await get_current_user(request)
        user_permissions = auth_role_permissions(current_user.role)   # admin -> все права
        for perm in self.required_permissions:
            if perm not in user_permissions:
                raise HTTPException(status_code=403, detail="Недостаточно прав")
        return current_user
```

**Usage:**
```python
@router.get("/protected")
async def endpoint(user: AuthSession = Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    ...
```

## Login/Logout/Me Endpoints

```python
@router.post("/auth/login")
async def login(request: Request, data: dict):
    # Queries user by username, verifies bcrypt hash, sets session
    if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["user_id"] = user['id']
    request.session["username"] = user['username']
    request.session["role"] = user['role']

@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()

@router.get("/auth/me")
async def me(request: Request):
    # Returns current user from DB, validates session is still valid
```

## Roles & Permissions

Роли динамические (таблица `role`); в коде захардкожен только `admin` (`AuthRole.ROLE_ADMIN`).

`auth_role.py`:
- `AUTH_PERMISSIONS_DEFAULT` — view-набор, достаётся любой роли без переопределения
- `AUTH_ROLE_PERMISSIONS` — переопределения по имени роли
- `auth_role_permissions(role)` → набор прав роли (`admin` → все права)
- `auth_role_is_full(role)` → роль с полным набором прав

**`qa`** (`vova.tkachenko`, логин/пароль в `.env.local`: `QA_USERNAME` / `QA_PASSWORD`) — учётка автотестов
и ручных проверок, права полные: сюита создаёт и удаляет пользователей, роли, агентов, workflow.
Отделена от `admin`, чтобы её сессии и действия были видны в логах отдельно от владельца.

⚠️ Не проверять роль по имени (`if user.role == 'admin'`) — такие проверки отсекают `qa` и любую
другую полноправную роль. Использовать `auth_role_is_full(role)`; так сделано в `agent.py`,
`session.py`, `fact.py`, `workflow_variable.py`, `auth_field_policy.py`, `event_handlers.py`
(последний ещё и глушит Telegram-уведомление о логине — иначе каждый тест слал бы пуш владельцу).

Adding a permission:
1. Add to `AuthPermission` enum in `auth_permission.py`
2. Add to the role's set in `AUTH_ROLE_PERMISSIONS` in `auth_role.py`
3. Use `Depends(AuthChecker([AuthPermission.NEW_PERM]))` in the router

## Field-Level Access Policy (`src/auth/auth_field_policy.py`)

Sits on top of endpoint-level RBAC. Controls which DB columns a role can read/write.

```python
ALL_FIELDS = '*'

AUTH_FIELD_POLICY = {
    'agent_workflow_variable': {
        'fields': {'name', 'description', 'default', 'workflow_id', 'node_id', 'pattern'},
        'write': {
            '*': {'default'},  # any non-admin role writes only `default`
        },
        'read': {
            '*': ALL_FIELDS,
        },
    },
}
```

Key: `'*'` is the fallback for any restricted role; a specific role name overrides it. Полноправные роли (`auth_role_is_full` — `admin`, `qa`) в политике не описываются — всегда `ALL_FIELDS`.

**Functions:**
- `auth_fields_allowed(entity, action, role)` → `ALL_FIELDS` or `set` of allowed fields
- `auth_fields_filter_for_update(entity, action, role, data)` → `(fields, data)` filtered to allowed columns

**Usage in PUT router:**
```python
fields, data = auth_fields_filter_for_update('agent_workflow_variable', 'write', user.role, data)
if fields:
    set_clause = ', '.join(f"`{f}`=%s" for f in fields)
    await db.execute(f"UPDATE agent_workflow_variable SET {set_clause} WHERE id=%s", ...)
```

**Usage in GET/list router:**
```python
allowed = auth_fields_allowed('agent_workflow_variable', 'read', user.role)
if allowed != ALL_FIELDS:
    results = [{k: v for k, v in row.items() if k in allowed} for row in results]
```

Adding field policy for a new entity:
1. Add entity key to `AUTH_FIELD_POLICY` with `fields`, `write`, `read`
2. Replace static UPDATE with `auth_fields_filter_for_update()` + dynamic SET clause
3. Filter list/get response with `auth_fields_allowed(entity, 'read', user.role)`

**Note:** `workflow_variable` uses separate permissions `WORKFLOW_VARIABLE_VIEW` / `WORKFLOW_VARIABLE_UPDATE` so regular users can save `default` without needing `WORKFLOW_UPDATE`.
