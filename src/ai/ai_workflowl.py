def ai_workflow_variables_default_get() -> list[str]:
    variables = [
        "prompt_user",
        "user_id",
        "agent_id",
        "session_uuid",
        "agent_greeting",
        "workflow_id",
        "node_id",
    ]
    return sorted(variables)
