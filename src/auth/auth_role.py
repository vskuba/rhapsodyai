from enum import Enum

from src.auth.auth_permission import AuthPermission


class AuthRole(str, Enum):
    ROLE_ADMIN = "admin"


# Базовый набор прав для любой не-админской роли.
# Роли создаются динамически в таблице `role` (manager_dating, manager_cashier, ...),
# поэтому права не хардкодятся по имени роли — все не-админы получают view-набор.
AUTH_PERMISSIONS_DEFAULT = {
    AuthPermission.USER_VIEW,
    AuthPermission.ROLE_VIEW,
    AuthPermission.AGENT_VIEW,
    AuthPermission.WORKFLOW_VIEW,
    AuthPermission.WORKFLOW_VARIABLE_VIEW,
    AuthPermission.WORKFLOW_TRACE_VIEW,
    AuthPermission.WORKFLOW_VARIABLE_UPDATE,
    AuthPermission.NODE_VIEW,
    AuthPermission.TOOL_VIEW,
    AuthPermission.LLM_VIEW,
    AuthPermission.FACT_VIEW,
    AuthPermission.FACT_COLLECTION_VIEW,
    AuthPermission.PLAN_VIEW,
    AuthPermission.PLANNING_VIEW,
    AuthPermission.PLANNING_UPDATE,
    AuthPermission.BROWSER_VIEW,
    AuthPermission.SESSION_VIEW,
    AuthPermission.SETTING_VIEW,
    AuthPermission.QUEUE_VIEW,
    AuthPermission.DESIGN_VIEW,
    AuthPermission.PROJECT_VIEW,
}

# Переопределения прав для конкретных ролей (админ получает все права в AuthChecker)
#
# `qa` — учётная запись автотестов и ручных проверок (`vova.tkachenko`). Права
# полные, потому что сюита создаёт и удаляет пользователей, роли, агентов и
# workflow: с view-набором почти каждый тест падал бы на 403. Роль отделена от
# `admin` не по объёму прав, а чтобы прогоны и ручные операции QA было видно
# в логах и сессиях отдельно от настоящего администратора.
#
# `blog_service` — учётка соседнего проекта **BlogAi** (Блокнот): присылает
# записанный голос и получает текст. Ровно одно право, `stt:create`.
#
# `dating_service` — учётка соседнего проекта **DatingAi**. Анкеты, переписка и
# страница живут там; сюда он ходит за двумя вещами: водить браузер и заводить
# агента анкеты. Набор узкий намеренно: этой учёткой правит не человек, а
# автоматика, и лишнее право здесь — не удобство, а возможность снести чужое по
# ошибке в коде.
#
# Почему именно эти четыре: `browser:view` — читать закладки сайтов вместе с их
# `presence`, `browser:create` — гонять сценарии в живой сессии и снимать адрес
# чат-сокета, `agent:create` — заводить агента анкеты через `POST /agent/create`,
# `agent:view` — находить его потом по имени. `/chat/ask`, которым workflow создаёт
# девушку и сочиняет ответы, своего права не требует — ему достаточно сессии.
#
# Прав `dating:*` больше нет: они уехали вместе со страницей. `planning:*` здесь
# тоже не место, хотя браузер раньше был прикрыт именно им — это право открывает
# ещё и планирование проектов.
AUTH_ROLE_PERMISSIONS = {
    'qa': set(AuthPermission),
    'blog_service': {
        # Учётка соседнего проекта **BlogAi**. Черновики, их теги и страница
        # живут там; сюда он ходит ровно за одним — расшифровать голос. Одно
        # право и есть весь набор: у автоматики нет причин трогать что-то ещё,
        # а лишнее право здесь — не удобство, а возможность снести чужое по
        # ошибке в коде (та же логика, что у `dating_service` выше).
        AuthPermission.STT_CREATE,
    },
    'dating_service': {
        # Учётка соседнего проекта DatingAi: анкеты и переписка живут там, а сюда
        # он ходит за браузером (закладки с `presence`, прогон сценариев в живой
        # сессии) и за агентом анкеты. Ручек знакомств здесь больше нет, поэтому
        # и прав `dating:*` нет — они уехали вместе со страницей.
        AuthPermission.BROWSER_VIEW,
        AuthPermission.BROWSER_CREATE,
        AuthPermission.AGENT_VIEW,
        AuthPermission.AGENT_CREATE,
        # `llm:view` — пятое право, и оно **только чтение**.
        #
        # Зачем: на «Профилях» у DatingAi появилась вкладка «Статистика», и в ней
        # среди прочего — сколько запросов к LLM ушло и сколько токенов потрачено.
        # Числа эти считает только здесь (`llm_request`), и своей копии у соседа
        # быть не должно: вторая копия расходится с первой в первый же день.
        #
        # Почему это не противоречит правилу «набор узкий намеренно». Оговорка там
        # про **возможность снести чужое по ошибке в коде** — то есть про права,
        # которые пишут. `llm:view` не пишет ничего: он открывает `GET /llm/list`,
        # `GET /llm/status` и `GET /llm/usage/stats`. Очистка журнала живёт за
        # отдельным `llm:delete`, и его здесь нет.
        AuthPermission.LLM_VIEW,
    },
}


def auth_role_permissions(role: str) -> set:
    """Права роли. У `admin` — полный набор, он в таблице переопределений не значится."""
    if role == AuthRole.ROLE_ADMIN:
        return set(AuthPermission)
    return AUTH_ROLE_PERMISSIONS.get(role, AUTH_PERMISSIONS_DEFAULT)


def auth_role_is_full(role: str) -> bool:
    """
    Роль с полным набором прав — `admin` и служебные роли вроде `qa`.

    Нужна там, где раньше стояло сравнение `role == 'admin'`: такие проверки
    отсекали любую другую полноправную роль, и QA-учётка получала 403 или урезанный
    ответ, имея на бумаге все права. Сверяем набор прав, а не имя роли.
    """
    return auth_role_permissions(role) == set(AuthPermission)
