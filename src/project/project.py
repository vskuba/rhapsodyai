from fastapi import HTTPException


async def project_context_generate(path: str, title: str = '', user_id: int = 0) -> str:
    """Сгенерировать контекст проекта через claude_shell: краткий обзор, основной функционал, страницы.

    Передаёт путь к проекту в Claude Code — он сам просканирует файлы.
    Возвращает готовый текст для поля ``context``.
    """
    prompt = (
        f"Проанализируй проект '{title}' по пути '{path}'.\n\n"
        f"На основе содержимого файлов сформируй краткий обзор проекта в формате:\n"
        f"1. Обзор проекта — что делает, основная цель\n"
        f"2. Основной функционал — ключевые возможности (списком)\n"
        f"3. Страницы / маршруты — основные страницы и endpoints\n"
        f"Пиши на русском языке."
    )

    from src.tool.claude_shell.claude_shell import claude_shell_call_async
    try:
        result_text = await claude_shell_call_async(prompt, use_gx10=True)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f'claude_shell недоступен: {e}')

    text = str(result_text).strip()
    if not text or text.startswith('claude_shell error'):
        raise HTTPException(status_code=502, detail='claude_shell вернул пустой/ошибочный ответ')

    return text
