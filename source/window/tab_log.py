import customtkinter as ctk
import source.window

class TabLog:
    def __init__(self):
        self._initialized = False

    def tab_log_setup(self, parent_frame=None):
        if parent_frame is None:
            parent_frame = self.tabview.tab("Логи")

        if self._initialized:
            print("[TabLog] Уже инициализировано — пропуск")
            return

        print("[TabLog] Первичная инициализация логов")

        log_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        log_frame.pack(padx=10, pady=10, fill="both", expand=True)

        source.window.log_textbox = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Courier New", size=22),
            fg_color="#1e1e1e",
            text_color="#d4d4d4",
            border_color="#333333",
            border_width=1,
            activate_scrollbars=True
        )
        source.window.log_textbox.pack(padx=5, pady=(5, 50), fill="both", expand=True)
        source.window.log_textbox.configure(state="disabled")

        # Панель управления логами (внизу справа)
        log_controls = ctk.CTkFrame(log_frame, fg_color="transparent", height=40)
        log_controls.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

        def clear_logs():
            source.window.log_textbox.configure(state="normal")
            source.window.log_textbox.delete("1.0", "end")
            source.window.log_textbox.configure(state="disabled")

        def copy_logs():
            try:
                import pyperclip
                pyperclip.copy(source.window.log_textbox.get("1.0", "end"))
            except ImportError:
                print("[WARN] pyperclip не установлен — копирование не работает")

        btn_clear = ctk.CTkButton(
            log_controls,
            text="Очистить",
            width=100,
            fg_color="#7C2A2A",
            hover_color="#A93232",
            command=clear_logs
        )
        btn_clear.pack(side="right", padx=5)

        btn_copy = ctk.CTkButton(
            log_controls,
            text="Копировать",
            width=100,
            command=copy_logs
        )
        btn_copy.pack(side="right", padx=5)

        # Можно сразу вывести тестовое сообщение для проверки
        source.window.log_textbox.configure(state="normal")
        source.window.log_textbox.insert("end", "Логи инициализированы\n")
        source.window.log_textbox.configure(state="disabled")

        self._initialized = True