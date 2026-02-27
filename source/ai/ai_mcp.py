import contextlib
import os

from mcp import ClientSession, StdioServerParameters, stdio_client

from source.logging_ import logger_info
from source.mcp import mcp_config_load
from source.queue import queue_get


class AiMcpManager:
    def __init__(self):
        self.exit_stack = contextlib.AsyncExitStack()  # Для авто-закрытия всех серверов
        self.sessions: dict[str, ClientSession] = {}

    async def mcp_server_add_tools(self, agent, mcp_server_name: str, session):
        mcp_tools = await session.list_tools()

        for tool in mcp_tools.tools:
            # logger_info(f"Добавляем инструмент {tool.name} от mcp сервера: {tool.description}")

            def create_tool(t_tool):
                async def mcp_proxy(**kwargs) -> str:
                    kwargs = self.mcp_server_kwargs(mcp_server_name, kwargs)

                    logger_info(f"🛠 Инструмент '{t_tool.name}' → ({kwargs}), description: {t_tool.description}")
                    result = await session.call_tool(t_tool.name, kwargs)
                    logger_info(f"🛠 Инструмент '{t_tool.name}' резудьтат  → {repr(result)}")

                    return result

                mcp_proxy.__name__ = t_tool.name
                mcp_proxy.__doc__ = t_tool.description
                return mcp_proxy

            # Регистрируем инструмент.
            # Если схема сложная, агент может потребовать явный docstring с параметрами.
            agent.tool_plain(create_tool(tool))

    async def mcp_server_session(self, mcp_servers: list[str]):
        logger_info(f"Создание сессий для mcp серверов")
        mcp_servers_config = {k.lower(): v for k, v in mcp_config_load().items()}
        for mcp_server_name in mcp_servers:
            mcp_server_name = mcp_server_name.lower()
            logger_info(f"Создаем сессию для mcp сервера {mcp_server_name}")

            if not mcp_servers_config.get(mcp_server_name):
                continue

            envs: dict[str, str] = {}
            for i in mcp_servers_config[mcp_server_name].get('env', []):
                value = os.getenv(i.upper())
                if not value:
                    raise ValueError(f"For mcp server {mcp_server_name} require env: {i.upper()}")
                envs[i] = value

            server_params = StdioServerParameters(
                command=mcp_servers_config[mcp_server_name].get('cmd', ''),
                args=mcp_servers_config[mcp_server_name].get('args', '').split(' '),
                env=envs if envs else None
            )
            # Открываем stdio и сессию, добавляем в стек для очистки в конце
            read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            logger_info(f"Cессия для mcp сервера {mcp_server_name} создана и инициализирована")
            self.sessions[mcp_server_name] = session
        return self.sessions

    async def mcp_server_close_all(self):
        await self.exit_stack.aclose()
        self.sessions.clear()

    def mcp_server_kwargs(self, mcp_server_name, kwargs):
        if mcp_server_name == 'jira':
            if 'cloudId' not in kwargs:
                kwargs['cloudId'] = os.getenv("JIRA_CLOUD_ID")

        return kwargs