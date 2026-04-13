import os
import threading
import webbrowser
import CTkToolTip
import customtkinter as ctk
import source.window

from source.ai_pydantic.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from config.config import config_get, config_update_and_save
from source.ai_pydantic.ai_framework_task_manager_pydantic import AiFrameworkTaskManagerPydantic
from source.parser.data_parser import data_parser_path_list, data_parser_load
from state.state import state_set
from source.window.component import CustomTextbox
from source.window.ui import window_chat_input_send, window_chat_voice_toggle, container_clear
from source.window.ui_agent import agent_item_draw
from source.window.ui_parser import parser_item_draw
from source.window.ui_task import task_item_draw

ai_task_manager = AiFrameworkTaskManagerPydantic()
ai_agent_manager = AiFrameworkAgentManagerPydantic()


class TabChat:
    def __init__(self):
        self._initialized = False
        self.chat_frame = None  # можно хранить ссылки, если нужно

    def tab_chat_setup(self, parent_frame=None):
        if self._initialized:
            return

        if parent_frame is None:
            return

        self.chat_frame = ctk.CTkFrame(parent_frame, corner_radius=10, fg_color="transparent")
        self.chat_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.chat_frame.grid_columnconfigure(0, weight=2)
        self.chat_frame.grid_columnconfigure(1, weight=0)
        self.chat_frame.grid_columnconfigure(2, weight=3)
        self.chat_frame.grid_rowconfigure(0, weight=1)

        # Диалог (левая колонка)
        chat_dialog_frame = ctk.CTkFrame(self.chat_frame, border_width=1)
        chat_dialog_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        header_frame = ctk.CTkFrame(chat_dialog_frame, fg_color="transparent")
        header_frame.pack(side="top", fill="x", padx=15, pady=(10, 5))

        label_left = ctk.CTkLabel(header_frame, text="Чаты с агентами:", font=("Arial", 23, "bold"), anchor="w")
        label_left.pack(side="left")

        self.chat_model_select = ctk.CTkComboBox(
            header_frame,
            values=[i.strip() for i in config_get('LLM_ALLOWED').split(",")],
            font=("Arial", 26),
            dropdown_font=("Arial", 26),
            width=450,
            state="readonly",
            command=lambda m: config_update_and_save("llm", m)
        )
        self.chat_model_select.set(config_get('llm'))
        self.chat_model_select.pack(side="right")

        source.window.chat_dialog_textbox = CustomTextbox(
            chat_dialog_frame,
            font=ctk.CTkFont(family="Arial", size=24),
            fg_color="#1e1e1e",
            text_color="#ffffff",
            wrap="word"
        )
        source.window.chat_dialog_textbox.pack(fill="both", expand=True, padx=10, pady=5)

        source.window.chat_dialog_textbox.tag_config("iam_tag", foreground="#A8E6CF")
        source.window.chat_dialog_textbox.tag_config("agent_tag", foreground="#669EFA")
        source.window.chat_dialog_textbox.tag_config("highlight", foreground="#A8E6CF")
        source.window.chat_dialog_textbox._textbox.tag_config("bold_tag", font=("Arial", 24, "bold"))

        source.window.chat_agent_status_label = ctk.CTkLabel(
            chat_dialog_frame,
            text="",
            font=("Arial", 25, "italic"),
            text_color="#A8E6CF",
            anchor="w"
        )
        source.window.chat_agent_status_label.pack(fill="x", padx=20, pady=(0, 5))

        source.window.chat_dialog_task_active_label = ctk.CTkLabel(
            chat_dialog_frame,
            text="Нет активной задачи",
            font=("Arial", 23, "bold"),
            height=45,
            fg_color="#3d424b",
            corner_radius=6
        )
        source.window.chat_dialog_task_active_label.pack(fill="x", padx=10, pady=(5, 10))

        source.window.chat_progress_bar = ctk.CTkProgressBar(
            chat_dialog_frame,
            orientation="horizontal",
            mode="indeterminate",
            height=4,
            progress_color="#2ecc71"
        )
        source.window.chat_progress_bar.pack(fill="x", padx=15, pady=2)
        source.window.chat_progress_bar.set(0)
        source.window.chat_progress_bar.stop()
        source.window.chat_progress_bar.pack_forget()

        # Нижняя часть: ввод текста
        chat_input_container = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        chat_input_container.grid_columnconfigure(0, weight=1)
        chat_input_container.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        chat_dialog_input_textbox = CustomTextbox(
            chat_input_container,
            height=120,
            font=ctk.CTkFont(family="Arial", size=26),
            fg_color="#213830",
            text_color="white",
            on_enter_press=lambda: (
                window_chat_input_send(chat_dialog_input_textbox.get("1.0", "end")),
                chat_dialog_input_textbox.delete("1.0", "end")
            )
        )
        chat_dialog_input_textbox.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        chat_dialog_input_textbox.focus_set()

        send_btn = ctk.CTkButton(
            chat_input_container,
            text='>',
            width=80,
            font=("Arial", 40),
            fg_color="#2D5A27",
            command=lambda: (
                window_chat_input_send(chat_dialog_input_textbox.get("1.0", "end")),
                chat_dialog_input_textbox.delete("1.0", "end")
            )
        )
        send_btn.grid(row=0, column=1, sticky="ns")

        # Быстрые кнопки
        fast_btn_frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        fast_btn_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        ctk.CTkButton(
            fast_btn_frame,
            text="Yes",
            fg_color="#2D5A27",
            hover_color="#3E7B35",
            font=("Arial", 20, "bold"),
            height=45,
            command=lambda: window_chat_input_send('Yes')
        ).pack(side="left", expand=True, padx=5, fill="x")

        def mic_on(event):
            mic_btn.configure(
                text_color="#ff4444",  # Микрофон становится красным
                fg_color="#6B0F0F",  # Кнопка визуально "вдавливается" (темнеет)
                border_color="#753F3F"
            )
            window_chat_voice_toggle(True)

        def mic_off(event):
            mic_btn.configure(
                text_color="black",  # Микрофон снова черный
                fg_color="#3d424b",  # Кнопка возвращается в обычный вид
                border_color="#2b2b2b"
            )
            window_chat_voice_toggle(False)

        # 2. Создаем саму кнопку
        mic_btn = ctk.CTkButton(
            fast_btn_frame,
            text="🎤",
            font=("Arial", 35),
            width=60,
            height=60,
            corner_radius=30,
            fg_color="#3d424b",
            text_color="black",
            border_width=2,
            border_color="#858282",
            hover=False
        )
        mic_btn.pack(side="left", padx=20)

        mic_btn.bind("<Button-1>", mic_on)
        mic_btn.bind("<ButtonRelease-1>", mic_off)

        ctk.CTkButton(
            fast_btn_frame,
            text="No",
            fg_color="#7C2A2A",
            hover_color="#A93232",
            font=("Arial", 20, "bold"),
            height=45,
            command=lambda: window_chat_input_send('No')
        ).pack(side="left", expand=True, padx=5, fill="x")

        # 1. Навигационная панель (кнопки-иконки)
        nav_frame = ctk.CTkFrame(self.chat_frame, width=70, fg_color="transparent")
        nav_frame.grid(row=0, column=1, rowspan=3, sticky="ns", padx=5, pady=10)

        # 2. Общий контейнер для контента справа
        self.right_content_container = ctk.CTkFrame(self.chat_frame, fg_color="transparent")

        self.right_content_container.grid_columnconfigure(0, weight=1)
        self.right_content_container.grid_rowconfigure(0, weight=1)

        self.right_content_container.grid(row=0, column=2, rowspan=3, sticky="nsew", padx=(0, 10), pady=10)
        self.right_content_container.grid_propagate(False)

        self.frame_agents = ctk.CTkScrollableFrame(
            self.right_content_container, label_text="Агенты", label_font=("Arial", 23, "bold"), border_width=1
        )
        self.frame_tasks = ctk.CTkScrollableFrame(
            self.right_content_container, label_text="Задачи", label_font=("Arial", 23, "bold"), border_width=1
        )
        self.frame_db = ctk.CTkScrollableFrame(
            self.right_content_container, label_text="Данные и память", label_font=("Arial", 23, "bold"), border_width=1
        )
        self.frame_parser = ctk.CTkScrollableFrame(
            self.right_content_container, label_text="Парсеры и конверторы", label_font=("Arial", 23, "bold"),
            border_width=1
        )

        # 4. Функция переключения между панелями
        def show_pane(pane_name):
            # 1. Сброс стилей ВСЕХ кнопок
            # (Проверьте, что переменные кнопок называются именно так)
            for btn in [btn_agents, btn_tasks, btn_db, btn_parser]:
                btn.configure(fg_color="#3d424b", border_width=1, border_color="#858282")

            # 2. Прячем ВСЕ контентные фреймы через grid_forget
            self.frame_agents.grid_forget()
            self.frame_tasks.grid_forget()
            self.frame_db.grid_forget()
            self.frame_parser.grid_forget()

            # 3. Активируем нужную вкладку в row=0 column=0 контейнера right_content_container
            if pane_name == "agents":
                self.frame_agents.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
                btn_agents.configure(fg_color="#1f538d", border_color="#5a9ed9")
            elif pane_name == "tasks":
                self.frame_tasks.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
                btn_tasks.configure(fg_color="#1f538d", border_color="#5a9ed9")
            elif pane_name == "parsers":
                self.frame_parser.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
                btn_parser.configure(fg_color="#1f538d", border_color="#5a9ed9")
            elif pane_name == "db":
                self.frame_db.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
                btn_db.configure(fg_color="#1f538d", border_color="#5a9ed9")

        # 5. Кнопки навигации в nav_frame
        btn_agents = ctk.CTkButton(
            nav_frame, text="🤖", width=65, height=65, corner_radius=15,
            font=("Arial", 36), fg_color="#3d424b", border_width=2, border_color="#858282",
            command=lambda: show_pane("agents")
        )
        btn_agents.pack(pady=(20, 10), padx=(10, 5))
        CTkToolTip.CTkToolTip(btn_agents, message="Список Агентов", font=("Arial", 20))

        btn_tasks = ctk.CTkButton(
            nav_frame, text="📋", width=65, height=65, corner_radius=15,
            font=("Arial", 36), fg_color="#3d424b", border_width=2, border_color="#858282",
            command=lambda: show_pane("tasks")
        )
        btn_tasks.pack(pady=10, padx=(10, 5))
        CTkToolTip.CTkToolTip(btn_tasks, message="Доступные Задачи", font=("Arial", 20))

        btn_db = ctk.CTkButton(
            nav_frame, text="🗳️", width=65, height=65, corner_radius=15,
            font=("Arial", 36), fg_color="#3d424b", border_width=2, border_color="#858282",
            command=lambda: show_pane("db")
        )
        btn_db.pack(pady=10, padx=(10, 5))
        CTkToolTip.CTkToolTip(btn_db, message="Данныи и память", font=("Arial", 20))

        btn_parser = ctk.CTkButton(
            nav_frame, text="🧩", width=65, height=65, corner_radius=15,
            font=("Arial", 36), fg_color="#3d424b", border_width=2, border_color="#858282",
            command=lambda: show_pane("parsers")
        )
        btn_parser.pack(pady=10, padx=(10, 5))
        CTkToolTip.CTkToolTip(btn_parser, message="Парсеры и конверторы", font=("Arial", 20))

        threading.Thread(target=self._async_load_data, daemon=True).start()
        show_pane("agents")

        self._initialized = True

    def _async_load_data(self):
        try:
            # --- 1. АГЕНТЫ (загрузка моделей) ---
            agent_names = ai_agent_manager.list()
            active_name = "my_assistant"
            if active_name not in agent_names and agent_names:
                active_name = agent_names[0]

            loaded_agents = []
            for name in agent_names:
                model = ai_agent_manager.load(name)
                loaded_agents.append((model, name == active_name))

            # --- 2. ЗАДАЧИ (просто список имен) ---
            tasks = ai_task_manager.list()

            # --- 3. ПАРСЕРЫ (загрузка моделей с сохранением структуры групп) ---
            parsers_raw = data_parser_path_list()
            loaded_parsers = []

            for item in parsers_raw:
                if isinstance(item, list):
                    # Если это группа (папка), загружаем каждую модель в этой группе
                    group_models = []
                    for p_path in item:
                        try:
                            group_models.append(data_parser_load(p_path))
                        except Exception as e:
                            print(f"[ERROR] Ошибка загрузки парсера {p_path}: {e}")
                    loaded_parsers.append(group_models)
                else:
                    # Одиночный парсер в корне
                    try:
                        loaded_parsers.append(data_parser_load(item))
                    except Exception as e:
                        print(f"[ERROR] Ошибка загрузки парсера {item}: {e}")

            # Отправляем всё на отрисовку разом
            self.chat_frame.after(0, lambda: self._ui_render_finish(loaded_agents, tasks, loaded_parsers))

        except Exception as e:
            print(f"[ERROR] Критическая ошибка загрузки данных: {e}")

    def _ui_render_finish(self, agents, tasks, parsers):
        # 1. Отрисовка агентов
        container_clear(self.frame_agents)

        # 1. Разделяем на две группы
        # agents_data — это список кортежей (model, is_active)
        main_agents = [a for a in agents if not a[0].specialization]
        sub_agents = [a for a in agents if a[0].specialization]

        # 2. Рендерим основных агентов (сверху)
        for model, is_active in main_agents:
            agent_item_draw(model, self.frame_agents, is_active)

        # 3. Рисуем ОДИН разделитель, если есть субагенты
        if sub_agents:
            self._draw_section_separator(self.frame_agents, "🤖 Субагенты и специализации")

        # 4. Рендерим субагентов (снизу)
        for model, is_active in sub_agents:
            agent_item_draw(model, self.frame_agents, is_active)

        # Сохраняем общий список в стейт для работы логики переключения
        state_set('agent_model_list', [a[0] for a in agents])

        # 2. Отрисовка задач
        for t_name in tasks:
            task_item_draw(t_name, self.frame_tasks)

        # 3. Отрисовка парсеров (твоя логика с группами)
        for item in parsers:
            if isinstance(item, list):
                if item:
                    first_parser_obj = item[0]
                    folder_path = os.path.dirname(first_parser_obj.path)
                    folder_name = os.path.basename(folder_path).upper()

                    self._draw_section_separator(self.frame_parser, f"📂 {folder_name}")

                    for sub in item:
                        parser_item_draw(sub, self.frame_parser)
            else:
                parser_item_draw(item, self.frame_parser)

        # --- Рендерим список баз данных
        container_clear(self.frame_db)

        self._draw_section_separator(self.frame_db, f"🗳️ Sqllite3", 'http://localhost:8084')
        self._draw_section_separator(self.frame_db, f"🗳️ Qdrant", 'http://localhost:6333/dashboard')

    def _draw_section_separator(self, container, title, url=None):
        # 1. Основной контейнер
        sep_wrapper = ctk.CTkFrame(container, fg_color="transparent")
        sep_wrapper.pack(fill="x", padx=2, pady=(20, 10))

        # 2. Плашка заголовка
        bg_bar = ctk.CTkFrame(
            sep_wrapper,
            height=34,
            fg_color="#3d424b",
            corner_radius=6
        )
        bg_bar.pack(fill="x")
        bg_bar.pack_propagate(False)

        # Контейнер для текста (чтобы всё было по центру)
        content_frame = ctk.CTkFrame(bg_bar, fg_color="transparent")
        content_frame.place(relx=0.5, rely=0.5, anchor="center")

        # 3. Основной текст
        lbl = ctk.CTkLabel(
            content_frame,
            text=title,
            font=("Arial", 23, "bold"),
            text_color="#DCE4EE"
        )
        lbl.pack(side="left")

        # 4. Проверка: если URL передан, добавляем кликабельный значок
        if url:
            link_icon = ctk.CTkLabel(
                content_frame,
                text=" 🔗",  # Смайлик ссылки или 🗄️
                font=("Arial", 18),
                text_color="#1f6aa5",  # Синеватый цвет ссылки
                cursor="hand2"
            )
            link_icon.pack(side="left", padx=(5, 0))

            # Обработка клика
            link_icon.bind("<Button-1>", lambda e: webbrowser.open_new_tab(url))

            # Эффект при наведении (опционально)
            link_icon.bind("<Enter>", lambda e: link_icon.configure(text_color="#3b8ed0"))
            link_icon.bind("<Leave>", lambda e: link_icon.configure(text_color="#1f6aa5"))