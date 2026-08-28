from enum import Enum


class AuthPermission(str, Enum):
    # User permissions
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"

    # Agent permissions
    AGENT_VIEW = "agent:view"
    AGENT_CREATE = "agent:create"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"

    # Role permissions
    ROLE_VIEW = "role:view"
    ROLE_CREATE = "role:create"
    ROLE_UPDATE = "role:update"
    ROLE_DELETE = "role:delete"

    # Workflow permissions
    WORKFLOW_VIEW = "workflow:view"
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_UPDATE = "workflow:update"
    WORKFLOW_DELETE = "workflow:delete"

    # Workflow variable permissions
    WORKFLOW_VARIABLE_VIEW = "workflow_variable:view"
    WORKFLOW_VARIABLE_CREATE = "workflow_variable:create"
    WORKFLOW_VARIABLE_UPDATE = "workflow_variable:update"
    WORKFLOW_VARIABLE_DELETE = "workflow_variable:delete"

    # Workflow trace permissions
    WORKFLOW_TRACE_VIEW = "workflow_trace:view"
    WORKFLOW_TRACE_DELETE = "workflow_trace:delete"
    WORKFLOW_TRACE_REPLAY = "workflow_trace:replay"
    WORKFLOW_TRACE_STOP = "workflow_trace:stop"

    # Node permissions
    NODE_VIEW = "node:view"
    NODE_CREATE = "node:create"
    NODE_UPDATE = "node:update"
    NODE_DELETE = "node:delete"

    # Tool permissions
    TOOL_VIEW = "tool:view"
    TOOL_CREATE = "tool:create"
    TOOL_UPDATE = "tool:update"
    TOOL_DELETE = "tool:delete"
    TOOL_TEST = "tool:test"

    # LLM permissions
    LLM_VIEW = "llm:view"
    LLM_CREATE = "llm:create"
    LLM_UPDATE = "llm:update"
    LLM_DELETE = "llm:delete"

    # Fact permissions
    FACT_VIEW = "fact:view"
    FACT_CREATE = "fact:create"
    FACT_UPDATE = "fact:update"
    FACT_DELETE = "fact:delete"

    # Fact Collection permissions
    FACT_COLLECTION_VIEW = "fact_collection:view"
    FACT_COLLECTION_CREATE = "fact_collection:create"
    FACT_COLLECTION_UPDATE = "fact_collection:update"
    FACT_COLLECTION_DELETE = "fact_collection:delete"

    # Plan permissions
    PLAN_VIEW = "plan:view"
    PLAN_CREATE = "plan:create"
    PLAN_UPDATE = "plan:update"
    PLAN_DELETE = "plan:delete"

    # Session permissions
    SESSION_VIEW = "session:view"
    SESSION_DELETE = "session:delete"

    # Setting permissions
    SETTING_VIEW = "setting:view"
    SETTING_UPDATE = "setting:update"

    # Planning permissions
    PLANNING_VIEW = "planning:view"
    PLANNING_CREATE = "planning:create"
    PLANNING_UPDATE = "planning:update"
    PLANNING_DELETE = "planning:delete"

    # Browser permissions
    #
    # Контейнер-браузер — общий инструмент: закладки сайтов, сценарии, живые сессии
    # Chromium и запись действий. Права свои по той же причине, что и у знакомств:
    # `planning:*` смешивал в одно право планирование проектов, анкеты и чужие
    # браузерные сессии, и служебной учётке приходилось выдавать всё разом.
    BROWSER_VIEW = "browser:view"
    BROWSER_CREATE = "browser:create"
    # Показ секретных переменных сайта сырыми — право отдельное от `browser:view`
    # намеренно. `browser:view` есть у `dating_service`, а это автоматика соседнего
    # проекта: ей нужны закладки с `presence`, но не пароли от чужих кабинетов.
    # Отдай мы расшифровку по `browser:view` — учётка, которой правит не человек, а
    # код, получила бы доступ ко всем паролям установки разом.
    #
    # Список переменных с закрытыми значениями (`•••`) при этом отдаётся по
    # `browser:view`: знать, что у сайта есть пароль, и знать сам пароль — разные вещи.
    BROWSER_SECRET_VIEW = "browser:secret"

    # Расшифровка речи — общий инструмент, как и браузер: модель Whisper живёт
    # здесь, а голос присылают соседние проекты. Право своё, а не `agent:*`:
    # расшифровка агентов не трогает, и служебной учётке соседа незачем получать
    # доступ к агентам ради одного микрофона.
    STT_CREATE = "stt:create"

    # Queue permissions
    QUEUE_VIEW = "queue:view"

    # GX10 permissions
    #
    # Отдельная машина с локальными LLM (llama.cpp) и ComfyUI: вкладка LLM → GX10.
    # View — читать статус сервисов и память, control — start/stop/restart/enable/disable.
    # Роль admin и qa получают оба права автоматически (полный набор).
    GX10_VIEW = "gx10:view"
    GX10_CONTROL = "gx10:control"

    # Design permissions
    DESIGN_VIEW = "design:view"
    DESIGN_CREATE = "design:create"
    DESIGN_UPDATE = "design:update"
    DESIGN_DELETE = "design:delete"

    # Project permissions
    PROJECT_VIEW = "project:view"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"