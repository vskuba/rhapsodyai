import inspect
import traceback

import customtkinter as ctk

from ai.tool.ai_tool import ai_tools_permanent_get, ai_tools_get
from logging_.logging_ import logger_info
from mcp_.mcp_ import mcp_config_list_get, mcp_config_get, mcp_config_tools_json_get


class TabTool:
    def __init__(self, master=None):
        self.master = master
        self.textbox = None

    def tab_tool_setup(self, parent_frame=None):
        if parent_frame is None: return

        if self.textbox is None:
            # Очистка контейнера перед созданием
            for widget in parent_frame.winfo_children():
                widget.destroy()

            # Настройка табов: первая колонка 400px, вторая следом
            self.textbox = ctk.CTkTextbox(
                parent_frame,
                font=("Consolas", 25),
                fg_color="#1e1e1e",
                text_color="#dddddd",
                wrap="none"
            )
            self.textbox.pack(padx=10, pady=10, fill="both", expand=True)

            self.textbox._textbox.configure(
                selectbackground="#4D4D4D",
                selectforeground="black"
            )

            # Новые стили для документации
            self.textbox.tag_config("group", background="#333131", foreground="#5DADE2", justify="center")
            self.textbox.tag_config("func", foreground="#F39C12")
            self.textbox.tag_config("signature", foreground="#85C1E9")  # Сигнатура другим цветом
            self.textbox.tag_config("doc_body", foreground="#ABB2B9", lmargin1=50, lmargin2=50)  # Отступ слева
            self.textbox.tag_config("border", foreground="#2C3E50")

        self._update_table_content()

    def _add_group_header(self, text):
        width = 120
        self.textbox.insert("end", f"\n{text.center(width)}\n", "group")
        self.textbox.insert("end", "—" * width + "\n", "border")

    def _add_row(self, name, signature, doc):
        self.textbox.insert("end", f"🔹 {name}", "func")
        self.textbox.insert("end", f"{signature}\n", "signature")

        if doc:
            lines = [line.strip() for line in doc.strip().split('\n') if line.strip()]
            clean_doc = " ".join(lines)  # Собираем в один поток для компактности

            self.textbox.insert("end", f"   📜 {clean_doc}\n", "doc_body")
        else:
            self.textbox.insert("end", "   📜 Нет описания\n", "doc_body")

        self.textbox.insert("end", "—" * 80 + "\n", "border")

    def _update_table_content(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")

        # 1. Базовые функции
        self._add_group_header("🖥️ БАЗОВЫЕ ФУНКЦИИ (ВСЕГДА ДОСТУПНЫ)")
        for t in ai_tools_permanent_get():
            self._add_row(t.__name__, str(inspect.signature(t)), t.__doc__ or "")


        # 2. Подгруженные инструменты
        self._add_group_header("📂 ИНСТРУМЕНТЫ ИЗ DATA")
        for t in ai_tools_get():
            self._add_row(t.__name__, str(inspect.signature(t)), t.__doc__ or "")

        # 3. MCP Инструменты
        try:
            from ai.ai_mcp import AiMcpManager
            mcp_manager = AiMcpManager()
            for server in mcp_config_list_get():
                config = mcp_config_get(server)
                tools_json = mcp_config_tools_json_get(server)
                self._add_group_header(f"📡 MCP: {config.title.upper()} ({len(tools_json)} TOOLS)")
                for t in tools_json:
                    # Создаем "быстрый" объект для получения сигнатуры
                    t_func = mcp_manager.mcp_tool_func_from_json(t)
                    self._add_row(t_func.__name__, str(inspect.signature(t_func)), t_func.__doc__ or "")
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"⚠️ Ошибка вывода MCP: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            self.textbox.insert("end", f"\nОшибка MCP: {e}\n")

        self.textbox.configure(state="disabled")