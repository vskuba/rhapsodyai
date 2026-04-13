import customtkinter as ctk

from config.config import config_get, config_update_and_save


class TabSettings:
    def __init__(self):
        self._initialized = False

    def tab_settings_setup(self, parent_frame=None):
        if parent_frame is None:
            parent_frame = self.tabview.tab("Настройки")

        if self._initialized:
            print("[TabSettings] Уже инициализировано — пропуск")
            return

        print("[TabSettings] Первичная инициализация настроек")

        setting_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        setting_frame.pack(padx=40, pady=40, fill="both", expand=True)

        setting_frame.grid_columnconfigure(0, weight=0)
        setting_frame.grid_columnconfigure(1, weight=1)

        # Выбор модели
        ctk.CTkLabel(setting_frame, text="Текущая модель:", font=("Arial", 32)).grid(
            row=0, column=0, pady=15, sticky="w"
        )
        setting_name_combobox = ctk.CTkComboBox(
            setting_frame,
            values=[i.strip() for i in config_get('LLM_ALLOWED').split(",")],
            font=("Arial", 28),
            dropdown_font=("Arial", 28),
            width=600
        )
        setting_name_combobox.grid(row=0, column=1, padx=20, pady=15, sticky="w")
        setting_name_combobox.set(config_get('llm', 'claude-sonnet-4-5-20250929'))

        # Anthropic Key
        ctk.CTkLabel(setting_frame, text="ANTHROPIC_API_KEY:", font=("Arial", 32)).grid(
            row=1, column=0, pady=15, sticky="w"
        )
        setting_anthropic_api_key_entry = ctk.CTkEntry(
            setting_frame, width=600, height=45, font=("Arial", 28), show="*"
        )
        setting_anthropic_api_key_entry.grid(row=1, column=1, padx=20, pady=15, sticky="w")
        setting_anthropic_api_key_entry.insert(0, config_get('anthropic_api_key', ''))

        # OpenAI Key
        ctk.CTkLabel(setting_frame, text="OPENAI_API_KEY:", font=("Arial", 32)).grid(
            row=2, column=0, pady=15, sticky="w"
        )
        setting_openai_api_key_entry = ctk.CTkEntry(
            setting_frame, width=600, height=45, font=("Arial", 28), show="*"
        )
        setting_openai_api_key_entry.grid(row=2, column=1, padx=20, pady=15, sticky="w")
        setting_openai_api_key_entry.insert(0, config_get('openai_api_key', ''))

        # Gemini Key
        ctk.CTkLabel(setting_frame, text="GEMINI_API_KEY:", font=("Arial", 32)).grid(
            row=3, column=0, pady=15, sticky="w"
        )
        setting_gemini_api_key_entry = ctk.CTkEntry(
            setting_frame, width=600, height=45, font=("Arial", 28), show="*"
        )
        setting_gemini_api_key_entry.grid(row=3, column=1, padx=20, pady=15, sticky="w")
        setting_gemini_api_key_entry.insert(0, config_get('gemini_api_key', ''))

        # Кнопка Сохранить
        setting_button_save = ctk.CTkButton(
            setting_frame,
            text='Сохранить конфигурацию',
            font=("Arial", 26, "bold"),
            fg_color="#2D5A27",
            hover_color="#3E7B35",
            height=50,
            command=lambda: (
                config_update_and_save("llm", setting_name_combobox.get()),
                config_update_and_save("anthropic_api_key", setting_anthropic_api_key_entry.get()),
                config_update_and_save("openai_api_key", setting_openai_api_key_entry.get()),
                config_update_and_save("gemini_api_key", setting_gemini_api_key_entry.get())
            )
        )
        setting_button_save.grid(row=4, column=1, pady=40, sticky="e")

        self._initialized = True