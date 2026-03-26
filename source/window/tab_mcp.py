import asyncio
import traceback
from typing import Any

import customtkinter as ctk
from mcp import StdioServerParameters

from source.logging_ import logger_info
from source.mcp import mcp_config_save, mcp_config_list_get, mcp_config_get, McpConfig, McpTool, mcp_config_delete
from source.queue_ import queue_get


class TabMcp:
    def __init__(self, master=None):
        self.master = master
        self._initialized = False  # флаг ленивой инициализации

        # Ссылки на виджеты, которые создаются один раз
        self.add_frame = None
        self.mcp_name_entry = None
        self.mcp_command_entry = None
        self.mcp_args_entry = None
        self.mcp_env_entry = None
        self.mcp_list_frame = None
        self.loading_label = None
        self.mcp_servers_rendered: dict[str, Any] = {}

    def tab_mcp_setup(self, parent_frame=None):
        """
        Ленивая инициализация вкладки MCP серверы.
        Создаёт структуру один раз, при повторных вызовах — ничего не делает.
        """
        print("[TabMcp] tab_mcp_setup вызван")

        if parent_frame is None:
            print("[ERROR] parent_frame не передан")
            return

        if self._initialized:
            print("[TabMcp] Вкладка уже инициализирована — пропуск")
            return

        print("[TabMcp] Первичная инициализация MCP вкладки")

        tab_mcp = parent_frame

        tab_mcp.grid_columnconfigure(0, weight=1)
        tab_mcp.grid_rowconfigure(1, weight=1)

        # Форма добавления сервера — создаётся один раз
        self.add_frame = ctk.CTkFrame(tab_mcp, corner_radius=10)
        self.add_frame.grid(row=0, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(
            self.add_frame,
            text="Добавить MCP сервер:",
            font=("Arial", 28, "bold")
        ).grid(row=0, column=0, columnspan=3, pady=10)

        mcp_input_font = ("Arial", 26)

        self.mcp_name_entry = ctk.CTkEntry(
            self.add_frame,
            placeholder_text="Имя (напр. Jira)",
            width=250,
            height=50,
            font=mcp_input_font
        )
        self.mcp_name_entry.grid(row=1, column=0, padx=10, pady=10)

        self.mcp_command_entry = ctk.CTkEntry(
            self.add_frame,
            placeholder_text="Команда",
            width=200,
            height=50,
            font=mcp_input_font
        )
        self.mcp_command_entry.grid(row=1, column=1, padx=10, pady=10)

        self.mcp_args_entry = ctk.CTkEntry(
            self.add_frame,
            placeholder_text="Аргументы (через запятую)",
            width=500,
            height=50,
            font=mcp_input_font
        )
        self.mcp_args_entry.grid(row=1, column=2, padx=10, pady=10, sticky="ew")

        self.mcp_env_entry = ctk.CTkEntry(
            self.add_frame,
            placeholder_text="Env (через запятую)",
            width=500,
            height=50,
            font=mcp_input_font
        )
        self.mcp_env_entry.grid(row=1, column=3, padx=10, pady=10, sticky="ew")

        btn_add = ctk.CTkButton(
            self.add_frame,
            text="+ Добавить",
            fg_color="#2D5A27",
            height=50,
            font=("Arial", 24, "bold"),
            command=self._mcp_server_add
        )
        btn_add.grid(row=1, column=4, padx=10, pady=10)

        # Список серверов — создаётся один раз
        self.mcp_list_frame = ctk.CTkScrollableFrame(
            tab_mcp,
            label_text="Подключенные серверы",
            label_font=("Arial", 28, "bold")
        )
        self.mcp_list_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

        # Первичная отрисовка списка
        self._mcp_server_list_render()

        self._initialized = True
        print("[TabMcp] Инициализация завершена")

    def _mcp_server_list_render(self):
        mcp_config_list = mcp_config_list_get()
        if mcp_config_list is None:
            return

        for mcp_server_name in mcp_config_list:
            self._mcp_server_list_item_render(mcp_server_name, mcp_config_get(mcp_server_name))

    def _mcp_server_list_item_render(self, mcp_server_name: str, mcp_config: McpConfig):
        card = ctk.CTkFrame(self.mcp_list_frame, corner_radius=8, border_width=1)
        card.pack(fill="x", padx=5, pady=5)
        self.mcp_servers_rendered[mcp_server_name] = card

        status_color = "#2ecc71" if mcp_config.status == "active" else "#e74c3c"
        ctk.CTkLabel(card, text="●", text_color=status_color, font=("Arial", 27)).pack(side="left", padx=10)

        info_text = f"{mcp_config.title} ({mcp_config.cmd} {' '.join(mcp_config.args)})"
        ctk.CTkLabel(card, text=info_text, font=("Arial", 26, "bold")).pack(side="left", padx=10)

        btn_refresh = ctk.CTkButton(
            card,
            text="🔄 Обновить инструменты",
            width=320,
            height=50,
            font=("Arial", 24),
            fg_color="#3d65a1",
            command=lambda s=mcp_server_name: self._mcp_server_tools_refresh(s)
        )
        btn_refresh.pack(side="right", padx=15, pady=10)

        btn_del = ctk.CTkButton(
            card,
            text="🗑",
            width=60,
            height=50,
            font=("Arial", 26),
            fg_color="#7C2A2A",
            command=lambda s=mcp_server_name: self._mcp_server_delete(s)
        )
        btn_del.pack(side="right", padx=10)

    def _mcp_server_add(self):
        title = self.mcp_name_entry.get().strip()
        mcp_server_name = title.lower().replace(' ', '_')
        try:
            mcp_config = McpConfig(**{
                'title': title,
                'cmd': self.mcp_command_entry.get().strip(),
                'args': [a.strip() for a in self.mcp_args_entry.get().split(' ')],
                'env': [a.strip() for a in self.mcp_env_entry.get().split(' ')],
                'status': 'active',
                'tools': []
            })
            mcp_config_save(mcp_server_name, mcp_config)
            self._mcp_server_list_item_render(mcp_server_name, mcp_config)
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при добавлении MCP: '{mcp_server_name}': {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

    def _mcp_server_delete(self, mcp_server_name):
        mcp_config_delete(mcp_server_name)

        self.mcp_servers_rendered[mcp_server_name].destroy()
        logger_info(f"🗑️ MCP Сервер '{mcp_server_name}' удалён.")

    def _show_loading_indicator(self, mcp_server_name):
        if not hasattr(self, 'loading_label') or not self.loading_label:
            self.loading_label = ctk.CTkLabel(
                self.mcp_list_frame,
                text="",
                font=("Arial", 18)
            )
            self.loading_label.pack(pady=10)

        mcp_config = mcp_config_get(mcp_server_name)
        self.loading_label.configure(text=f"Обновление {mcp_config.title}...")
        if self.master:
            self.master.update_idletasks()

    def _mcp_server_tools_refresh(self, mcp_server_name):
        mcp_config = mcp_config_get(mcp_server_name)

        logger_info(f"🛠 Запрашиваю инструменты для {mcp_config.title}...")

        self._show_loading_indicator(mcp_server_name)
        self._run_async_mcp_fetch_to_logs(mcp_server_name, mcp_config.cmd, mcp_config.args)

    def _run_async_mcp_fetch_to_logs(self, mcp_server_name, command, args):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._fetch_tools_from_sdk(mcp_server_name, command, args))
        finally:
            loop.close()

    async def _fetch_tools_from_sdk(self, mcp_server_name, command, args):
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession

        server_params = StdioServerParameters(command=command, args=args)
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.list_tools()

                    tools = [{
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema
                    } for t in response.tools]
                    logger_info(f"🛠 Получено {len(tools)} инструментов")

                    # Обновляем конфиг
                    mcp_config = mcp_config_get(mcp_server_name)
                    mcp_config.tools = [McpTool(**t) for t in tools]
                    mcp_config_save(mcp_server_name, mcp_config)
                    logger_info(f"🔄 Конфиг обновлён для {mcp_config.title}")

                    try:
                        queue_get()['tool'].put(True)
                        logger_info("⛓️ Отправлено в очередь 'tool': True")
                    except Exception as e:
                        backtrace = traceback.format_exc()
                        logger_info(
                            f"❌ Ошибка отправки в очередь 'tool': {e}."
                            f"Полный стек вызовов:\n{backtrace}"
                        )

        except asyncio.TimeoutError:
            print("[!] Таймаут при общении с MCP SDK.")
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка получение инструментов MCP: '{mcp_server_name}': {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

        if self.master:
            def hide_indicator():
                if hasattr(self, 'loading_label') and self.loading_label:
                    self.loading_label.configure(text="")
                    # self.loading_label.pack_forget()  # если нужно скрыть полностью

            self.master.after(0, hide_indicator)
