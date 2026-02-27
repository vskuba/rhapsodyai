from dataclasses import dataclass
from typing import Any

# from crewai_tools import GithubSearchTool, ScrapeWebsiteTool, SerperDevTool, FileReadTool, DirectoryReadTool, \
#     FileWriterTool

from source.ai.ai_tools import ai_tools_get
from source.config import config_get


@dataclass
class AgentTool:
    tool: Any
    description: str = ""


def ai_crewia_tools_get() -> dict[str, AgentTool]:
    """
    Возращает список инструментов для crewai AI
    """
    embedder_config: Any = {
        "provider": "ollama",
        "config": {
            "model": "nomic-embed-text",
            "base_url": "http://localhost:11434"
        }
    }

    crewia_tools = [
        GithubSearchTool(
            gh_token=config_get('github_token'),
            content_types=['code', 'issue', 'markdown'],  # ищем в коде и документации
            repository='https://github.com/vskuba/agent',
            config=embedder_config
        ),
        ScrapeWebsiteTool(),
        SerperDevTool(),
        FileReadTool(),
        DirectoryReadTool(),
        FileWriterTool(),
    ]

    dict = {}
    for tool_obj in ai_tools_get() + crewia_tools:
        # Извлекаем имя инструмента (атрибут .name)
        # Если это обычная функция без декоратора, используем __name__
        name = getattr(tool_obj, 'name', getattr(tool_obj, '__name__', str(tool_obj)))
        description = getattr(tool_obj, 'description', "")

        dict[name] = AgentTool(
            tool=tool_obj,
            description=description
        )

    return dict
