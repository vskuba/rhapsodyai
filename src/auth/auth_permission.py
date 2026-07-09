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

    # Session permissions
    SESSION_VIEW = "session:view"

    # Setting permissions
    SETTING_VIEW = "setting:view"
    SETTING_UPDATE = "setting:update"

    # Queue permissions
    QUEUE_VIEW = "queue:view"