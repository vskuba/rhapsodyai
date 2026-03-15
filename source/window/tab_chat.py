import customtkinter as ctk
import source.window
from source.ai.framework.pydanticai.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic

from source.ai.framework.pydanticai.ai_framework_task_pydantic import AiFrameworkTaskManagerPydantic
from source.config import config_get, config_update_and_save
from source.window.component import CustomTextbox
from source.window.ui import task_item_draw, window_chat_input_send, window_chat_voice_toggle, agent_item_draw

ai_task_manager = AiFrameworkTaskManagerPydantic()
ai_agent_manager = AiFrameworkAgentManagerPydantic()

class TabChat:
    def __init__(self):
        self._initialized = False
        self.chat_frame = None  # можно хранить ссылки, если нужно

    def tab_chat_setup(self, parent_frame=None):
        if parent_frame is None:
            parent_frame = self.tabview.tab("Чат")

        if self._initialized:
            return

        self.chat_frame = ctk.CTkFrame(parent_frame, corner_radius=10, fg_color="transparent")
        self.chat_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.chat_frame.grid_columnconfigure(0, weight=3)  # Чат (было 2)
        self.chat_frame.grid_columnconfigure(1, weight=1)  # Агенты (НОВАЯ)
        self.chat_frame.grid_columnconfigure(2, weight=2)  # Задачи (было 1)
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

        # 2. Колонку: Агенты
        chat_frame_agents = ctk.CTkScrollableFrame(
            self.chat_frame,
            label_text="Агенты",
            label_font=("Arial", 23, "bold"),
            border_width=1
        )
        chat_frame_agents._label.configure(anchor="w")
        chat_frame_agents.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=10, pady=10)

        all_agents = ai_agent_manager.list()
        active_agent_name = "researcher"

        if active_agent_name in all_agents:
            all_agents.remove(active_agent_name)
            all_agents.insert(0, active_agent_name)
        elif all_agents:
            active_agent_name = all_agents[0]

        for agent_name in all_agents:
            is_active = (agent_name == active_agent_name)
            agent_item_draw(agent_name, chat_frame_agents, is_active)

        # Правая колонка: задачи
        chat_frame_tasks = ctk.CTkScrollableFrame(
            self.chat_frame,
            label_text="Доступные задачи",
            label_font=("Arial", 23, "bold"),
            border_width=1
        )
        chat_frame_tasks._label.configure(anchor="w")
        chat_frame_tasks.grid(row=0, column=2, rowspan=3, sticky="nsew", padx=10, pady=10)

        # Отрисовка задач
        for name in ai_task_manager.list():
            task_item_draw(name, chat_frame_tasks)

        self._initialized = True