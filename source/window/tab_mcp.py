import asyncio
import traceback
from typing import Any

import customtkinter as ctk
from mcp import StdioServerParameters

from source.logging_ import logger_info
from source.mcp import mcp_config_load, mcp_config_save
from source.queue import queue_get




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
            command=self.mcp_server_add
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
        self.mcp_server_list_render()

        self._initialized = True
        print("[TabMcp] Инициализация завершена")

    def mcp_server_list_render(self):
        mcp_data = mcp_config_load() or []

        for server_name in mcp_data:
            self.mcp_server_list_item_add(mcp_data[server_name] | {"name": server_name})

    def mcp_server_list_item_add(self, item: dict[str, Any]):
        card = ctk.CTkFrame(self.mcp_list_frame, corner_radius=8, border_width=1)
        card.pack(fill="x", padx=5, pady=5)
        self.mcp_servers_rendered[item.get('name')] = card

        status_color = "#2ecc71" if item.get("status") == "active" else "#e74c3c"
        ctk.CTkLabel(card, text="●", text_color=status_color, font=("Arial", 27)).pack(side="left", padx=10)

        info_text = f"{item.get('name')} ({item.get('cmd')} {item.get('args', '')})"
        ctk.CTkLabel(card, text=info_text, font=("Arial", 26, "bold")).pack(side="left", padx=10)

        btn_refresh = ctk.CTkButton(
            card,
            text="🔄 Обновить инструменты",
            width=320,
            height=50,
            font=("Arial", 24),
            fg_color="#3d65a1",
            command=lambda s=item['name']: self.mcp_server_tools_refresh(s)
        )
        btn_refresh.pack(side="right", padx=15, pady=10)

        btn_del = ctk.CTkButton(
            card,
            text="🗑",
            width=60,
            height=50,
            font=("Arial", 26),
            fg_color="#7C2A2A",
            command=lambda s=item['name']: self.mcp_server_delete(s)
        )
        btn_del.pack(side="right", padx=10)

    def mcp_server_add(self):
        name = self.mcp_name_entry.get().strip()
        cmd = self.mcp_command_entry.get().strip()
        args_raw = self.mcp_args_entry.get().strip()
        env_raw = self.mcp_env_entry.get().strip()

        if not name or not cmd:
            print("Ошибка: Имя сервера и Команда обязательны.")
            return

        current_mcp_dict = mcp_config_load() or []

        if any(server_name == name for server_name in current_mcp_dict):
            print(f"Ошибка: Сервер '{name}' уже существует.")
            return

        current_mcp_dict[name] = {
            "cmd": cmd,
            "args": args_raw,
            "env": env_raw.split(',') if env_raw else [],
            "status": "active",
            "tools_cache": []
        }

        mcp_config_save(current_mcp_dict)

        self.mcp_server_list_item_add(current_mcp_dict[name] | {"name": name})

    def mcp_server_delete(self, server_name):
        current_mcp_dict = mcp_config_load() or {}

        updated_dict = {s: current_mcp_dict[s] for s in current_mcp_dict if s != server_name}

        mcp_config_save(updated_dict)

        self.mcp_servers_rendered[server_name].destroy()
        print(f"[-] MCP Сервер '{server_name}' удалён.")

    def _show_loading_indicator(self, server_name):
        if not hasattr(self, 'loading_label') or not self.loading_label:
            self.loading_label = ctk.CTkLabel(
                self.mcp_list_frame,
                text="",
                font=("Arial", 18)
            )
            self.loading_label.pack(pady=10)

        self.loading_label.configure(text=f"Обновление {server_name}...")
        if self.master:
            self.master.update_idletasks()

    def mcp_server_tools_refresh(self, server_name):
        servers = mcp_config_load() or []
        server_cfg = next((s for s in servers if s.get('name') == server_name), None)

        if not server_cfg:
            print(f"[-] Конфигурация '{server_name}' не найдена.")
            return

        print(f"[*] Запрашиваю инструменты для {server_name}...")

        cmd = server_cfg.get('cmd')
        args = server_cfg.get('args', "").split()

        self._show_loading_indicator(server_name)

        self._run_async_mcp_fetch_to_logs(server_name, cmd, args)

    def _run_async_mcp_fetch_to_logs(self, server_name, command, args):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._fetch_tools_from_sdk(server_name, command, args))
        finally:
            loop.close()

    async def _fetch_tools_from_sdk(self, server_name, command, args):
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession

        server_params = StdioServerParameters(command=command, args=args)

        tools = []
        success = False

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.list_tools()

                    tools = [{"name": t.name, "description": t.description or ""} for t in response.tools]
                    print(f"[OK] Получено {len(tools)} инструментов")

                    # Обновляем конфиг
                    configs = mcp_config_load() or []
                    for config_server_name in configs:
                        if config_server_name == server_name:
                            configs[config_server_name]['tools_cache'] = tools
                            mcp_config_save(configs)
                            print(f"[OK] Конфиг обновлён для {server_name}")
                            success = True
                            break
                    else:
                        print(f"[!] Сервер {server_name} не найден — кэш не обновлён")

        except asyncio.TimeoutError:
            print("[!] Таймаут при общении с MCP SDK.")
        except Exception as e:
            err_str = str(e).lower()
            if "abort" in err_str or "aborted" in err_str:
                print("[!] Пойман AbortError — используем полученные данные")
                if 'response' in locals() and hasattr(response, 'tools'):
                    tools = [{"name": t.name, "description": t.description or ""} for t in response.tools]
                    success = True
            else:
                print(f"[!] Ошибка при опросе SDK: {e}")

        if success:
            try:
                queue_get()['tool'].put(True)
                print("[OK] Отправлено уведомление в очередь 'tool': True")
            except Exception as e:
                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Ошибка отправки в очередь 'tool': {e}."
                    f"Полный стек вызовов:\n{backtrace}"
                )

        if self.master:
            def hide_indicator():
                if hasattr(self, 'loading_label') and self.loading_label:
                    self.loading_label.configure(text="")
                    # self.loading_label.pack_forget()  # если нужно скрыть полностью

            self.master.after(0, hide_indicator)

        return tools
