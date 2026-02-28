import traceback

import customtkinter as ctk

from source.ai.ai_tool import ai_tools_get, ai_tools_permanent_get
from source.logging_ import logger_info
from source.mcp import mcp_config_list_get, mcp_config_get

class TabTool:
    def __init__(self, master=None):
        self.master = master
        self.textbox = None

    def tab_tool_setup(self, parent_frame=None):
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

        # Обновляем содержимое (без destroy, без новой структуры)
        self._update_text_content()

    def _update_text_content(self):
        if not self.textbox:
            return

        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")

        # Локальные инструменты
        self.textbox.insert("end", "🖥️ Базовые функции (их не нужно прописывать в yml, доступны всегда)\n\n")

        local_permanent_tools = list(ai_tools_permanent_get())
        for tool in local_permanent_tools:
            name = getattr(tool, '__name__', str(tool))
            doc = getattr(tool, '__doc__', "Нет описания").strip().split('\n')[0]
            self.textbox.insert("end", f"• {name} — {doc}\n")

        self.textbox.insert("end", "\n📂 Подгруженные из Data\n\n")
        local_tools = list(ai_tools_get())
        for tool in local_tools:
            name = getattr(tool, '__name__', str(tool))
            doc = getattr(tool, '__doc__', "Нет описания").strip().split('\n')[0]
            self.textbox.insert("end", f"• {name} — {doc}\n")

        # MCP инструменты
        try:
            mcp_config_list = mcp_config_list_get()
            if not mcp_config_list:
                return

            for mcp_server_name in mcp_config_list:
                mcp_config = mcp_config_get(mcp_server_name)
                tools = [t for t in mcp_config.tools]
                self.textbox.insert("end", f"\n📡 MCP: {mcp_config.title} ({len(tools)} инструментов)\n\n")
                for t in tools:
                    self.textbox.insert("end", f"• {t.name} — {t.description}\n")
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка вывода MCP: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            self.textbox.insert("end", f"\nОшибка MCP: {e}\n")

        self.textbox.configure(state="disabled")
        self.textbox.see("end")