import customtkinter as ctk


class StdoutRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, s):
        # Добавляем текст в конец и прокручиваем
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", s)
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")

    def flush(self):
        pass  # Нужно для совместимости с sys.stdout


class CustomTextbox(ctk.CTkTextbox):
    def __init__(self, *args, on_enter_press=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_enter_press = on_enter_press
        self.bind("<Control-a>", self._select_all)
        self.bind("<Command-a>", self._select_all)
        self.bind("<Return>", self._on_enter)

    def _select_all(self, event=None):
        self.tag_add("sel", "1.0", "end")
        return "break"

    def _on_enter(self, event):
        # Если Shift не зажат — отправляем
        if not (event.state & 0x1):
            if self.on_enter_press:
                self.on_enter_press()
            return "break"  # Не даем перенести строку
        # Если Shift зажат — штатный переход на новую строку
        return None


class AiPopupWindow(ctk.CTkToplevel):
    def __init__(self, master, text: str, yes_no: bool = False):
        super().__init__(master)

        self.result = None  # Сюда запишем результат (True/False/None)

        # Базовые настройки
        self.withdraw()  # Скрываем до окончания верстки и центрирования
        self.title("Внимание")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(padx=20, pady=20)

        # Кнопка с заголовком задачи
        self.title_button = ctk.CTkButton(
            self,
            text='Агент спрашивает',
            font=("Arial", 28),
            fg_color="#3d65a1"
        )
        self.title_button.pack(side="top", pady=5, padx=5, fill="x")

        # Текстовое поле (используем твой CustomTextbox)
        self.textbox = CustomTextbox(
            self,
            font=("Arial", 26),
            fg_color="transparent",
            width=400,
            height=200,
            on_enter_press=self._on_ok
        )
        self.textbox.insert("0.0", text)
        self.textbox.tag_config("center", justify="center")
        self.textbox.tag_add("center", "1.0", "end")
        self.textbox.configure(state="disabled")
        self.textbox.pack(padx=10, pady=10, fill="both", expand=True)

        # Контейнер для кнопок управления
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.pack(pady=(10, 0))

        if yes_no:
            self.btn_yes = ctk.CTkButton(
                self.button_frame,
                text="Да",
                font=("Arial", 26),
                command=self._on_yes
            )
            self.btn_yes.pack(side="left", padx=10)

            self.btn_no = ctk.CTkButton(
                self.button_frame,
                text="Нет",
                font=("Arial", 26),
                command=self._on_no
            )
            self.btn_no.pack(side="left", padx=10)
        else:
            self.btn_ok = ctk.CTkButton(
                self.button_frame,
                text="Ок",
                font=("Arial", 26),
                command=self._on_ok
            )
            self.btn_ok.pack(pady=(10, 0))

        # Настройка поведения
        self.bind("<Return>", lambda e: self._on_ok())
        self._center_window()

    def _center_window(self):
        """Рассчитывает размеры и центрирует окно перед показом"""
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()

        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)

        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.focus_set()

    def _on_ok(self):
        self.result = True
        self.destroy()

    def _on_yes(self):
        self.result = True
        self.destroy()

    def _on_no(self):
        self.result = False
        self.destroy()