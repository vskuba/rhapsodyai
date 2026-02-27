import traceback

import customtkinter as ctk

from source.ai.framework.pydanticai.ai_pydantic_tool import ai_pydantic_tools_get
from source.logging_ import logger_info


class TabTool:
    def __init__(self, master=None):
        self.master = master
        self.textbox = None

    def tab_tool_setup(self, parent_frame=None):
        print("[TabTool] tab_tool_setup вызван")

        if parent_frame is None:
            return

        tab_tools = parent_frame

        # Создаём textbox только ОДИН РАЗ
        if self.textbox is None:
            for widget in tab_tools.winfo_children():
                widget.destroy()

            self.textbox = ctk.CTkTextbox(
                tab_tools,
                font=("Arial", 30),
                fg_color="#1e1e1e",
                text_color="#dddddd",
                wrap="word"
            )
            self.textbox.pack(padx=20, pady=20, fill="both", expand=True)
            print("[TabTool] Textbox создан один раз")

        # Обновляем содержимое (без destroy, без новой структуры)
        self._update_text_content()

    def _update_text_content(self):
        print("[TabTool] _update_text_content запущен")

        if not self.textbox:
            print("[TabTool] textbox ещё не создан — пропуск")
            return

        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")

        # Локальные инструменты
        self.textbox.insert("end", "💻 Локальные функции\n\n")

        local_tools = list(ai_pydantic_tools_get())
        for tool in local_tools:
            name = getattr(tool, '__name__', str(tool))
            doc = getattr(tool, '__doc__', "Нет описания").strip().split('\n')[0]
            self.textbox.insert("end", f"• {name} — {doc}\n")

        # MCP инструменты
        try:
            from source.mcp import mcp_config_load
            servers = mcp_config_load() or []
            print(f"[DEBUG] MCP серверов: {len(servers)}")
            for server in servers:
                name = server.get('name', 'Без имени')
                tools = server.get('tools_cache', [])
                self.textbox.insert("end", f"\n🌐 MCP: {name} ({len(tools)} инструментов)\n\n")
                for t in tools:
                    desc = t.get('description', 'Нет описания')
                    self.textbox.insert("end", f"• {t['name']} — {desc}\n")
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка вывода MCP: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            self.textbox.insert("end", f"Ошибка MCP: {e}\n")

        self.textbox.configure(state="disabled")
        self.textbox.see("end")
        print("[TabTool] Текст обновлён")
