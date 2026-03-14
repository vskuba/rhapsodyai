import time
import CTkToolTip
import customtkinter as ctk
import source.window
import source.ai.ai_thread
from source.ai.framework.ai_framework import AiFrameworkModel
from source.ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel
from source.ai.framework.ai_framework_task import AbstractAiFrameworkTaskModel
from source.ai.framework.pydanticai.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.ai.framework.pydanticai.ai_framework_task_pydantic import AiFrameworkTaskManagerPydantic

from source.async_ import async_waiting_is_active, async_waiting_clear, async_loop_task_cancel
from source.filesystem import open_file_in_editor
from source.logging_ import logger_info
from source.queue import queue_get

ai_task_manager = AiFrameworkTaskManagerPydantic()
ai_agent_manager = AiFrameworkAgentManagerPydantic()
agents_widgets_storage = {}

task_active: AbstractAiFrameworkTaskModel | None = None
agent_active: AbstractAiFrameworkAgentModel | None = None


def task_item_animate_pulse(button, colors, text_target, state=0):
    # Прекращаем, если текст кнопки изменился (статус сменился)
    if button.cget("text") != text_target and text_target != "📄 .yml":
        return
    # Для кнопки YML проверяем специфическое состояние (например, цвет)
    if text_target == "📄 .yml" and button.cget("fg_color") == "#2D5A27":
        return

    next_state = (state + 1) % len(colors)
    button.configure(fg_color=colors[state])
    button.after(220, lambda: task_item_animate_pulse(button, colors, text_target, next_state))


def task_item_toggle(button, task: AbstractAiFrameworkTaskModel):
    current_status = button.cget("text")

    if current_status == "▶":
        # проверяеи валидацию yml
        ai_task_manager.load(task.name)
        # СТАТУС 2: АКТИВНЫЙ (Запуск -> Пульсация красным)
        button.configure(text="⏹")
        task_item_animate_pulse(button, ["#7C2A2A", "#A93232", "#FF4C4C", "#A93232"], "⏹")
        # print(f"Задача {t_name} активна и пульсирует.")
        window_chat_loading_start()  # запуск индикатора под чатом
        logger_info(f'▶ Отправляю задачу в очередь: "{task.title}"')
        queue_get()['task'].put(task.name)
        window_chat_progress_title_display(task)
    else:
        async_loop_task_cancel()
        queue_get()['chat'].put({'text': f'Запрос на остановку задачи {task.title}', 'who': 'agent'})


def task_item_draw(task_name, parent_container):
    # Пытаемся загрузить задачу для проверки валидности
    task = None
    is_yml_valid = False
    yml_error_text = ''
    try:
        task = ai_task_manager.load(task_name)
        is_yml_valid = True
    except Exception as e:
        yml_error_text = str(e)
        pass

    # Создаем фрейм-карточку
    task_item = ctk.CTkFrame(parent_container, fg_color="#2b2e34", corner_radius=6)
    task_item.pack(fill="x", padx=5, pady=3)

    # Название
    lbl_name = ctk.CTkLabel(
        task_item,
        text=task.title if task is not None else task_name,
        font=("Arial", 28, "bold"), anchor="w"
    )
    lbl_name.pack(side="top", fill="x", padx=10, pady=(5, 0))

    actions_frame = ctk.CTkFrame(task_item, fg_color="transparent")
    actions_frame.pack(side="top", fill="x", padx=10, pady=10)

    # Логика кнопок
    if not is_yml_valid:
        # КНОПКА REFRESH (вместо Старт)
        def refresh_cmd():
            task_item.destroy()  # Удаляем старую карточку
            task_item_draw(task_name, parent_container)  # Пробуем создать заново

        btn_refresh = ctk.CTkButton(
            actions_frame, text="🔄", width=70, height=45,
            font=("Arial", 28), fg_color="#d35400", hover_color="#e67e22",
            command=refresh_cmd
        )
        btn_refresh.pack(side="left", padx=5)

        # Кнопка YML (мигает)
        btn_yml = ctk.CTkButton(
            actions_frame, text="📄 .yml", width=110, height=45,
            font=("Arial", 24), fg_color="#3d65a1",
            command=lambda: open_file_in_editor(ai_task_manager.filepath_get(task_name))
        )
        btn_yml.pack(side="left", padx=10)
        CTkToolTip.CTkToolTip(
            btn_yml,
            message=yml_error_text,
            font=("Arial", 27),
            padding=(15, 10),
            border_width=2,
            border_color="#ff0000",
            bg_color="#2b2b2b",
            text_color="#ffffff",
            corner_radius=8
        )

        task_item_animate_pulse(btn_yml, ["#e67e22", "#f39c12", "#d35400", "#f39c12"], "📄 .yml")

    else:
        # КНОПКА СТАРТ (обычный режим)
        btn_state = ctk.CTkButton(
            actions_frame, text="▶", width=70, height=45,
            font=("Arial", 28), fg_color="#2D5A27", corner_radius=8
        )
        btn_state.configure(command=lambda b=btn_state, t=task: task_item_toggle(b, t))
        btn_state.pack(side="left", padx=5)
        source.window.chat_task_btn_state[task.name] = btn_state

        btn_yml = ctk.CTkButton(
            actions_frame, text="📄 .yml", width=110, height=45,
            font=("Arial", 24), fg_color="#3d65a1",
            command=lambda: open_file_in_editor(ai_task_manager.filepath_get(task_name))
        )
        btn_yml.pack(side="left", padx=10)

    # Чекбокс истории
    checkbox_history = ctk.CTkCheckBox(
        actions_frame,
        text="История",
        font=("Arial", 24),
        checkbox_width=32,
        checkbox_height=32,
        state="disabled"
    )
    checkbox_history.pack(side="right", padx=5)
    # checkbox_history.configure(
    #     command=lambda name=task_name: (
    #         ai_task_manager.task_schema_yaml_update(
    #             name, "history_save",
    #             bool(checkbox_history.get())
    #         )
    #     )
    # )
    if task and getattr(task, 'history_save', False):
        checkbox_history.select()


def window_chat_input_send(text: str) -> None:
    if not text or not text.strip():
        return

    window_chat_message_add(text, 'iam')
    window_chat_loading_start()

    if agent_active:
        agent_active.prompt = text
        window_chat_progress_title_display(agent_active)
        queue_get()['agent'].put(agent_active)
        return

    if task_active:
        if async_waiting_is_active():
            queue_get()['chat_response'].put(text)
            time.sleep(0.05)

            async_waiting_clear()
            source.window.chat_progress_bar.configure(
                progress_color="#2ecc71"
            )
            window_chat_loading_stop()


def window_chat_message_add(text: str, who: str) -> None:
    if not text or not text.strip():
        return

    source.window.chat_dialog_textbox.configure(state="normal")

    # Визуальные префиксы
    if who == 'iam':
        header = "👤 Я:"
        tag = "iam_tag"
    else:
        header = "🤖 Агент:"
        tag = "agent_tag"

    # Добавляем заголовок и само сообщение
    source.window.chat_dialog_textbox.insert("end", f"\n{header}\n", tag)
    source.window.chat_dialog_textbox.insert("end", f"{text.strip()}\n")

    source.window.chat_dialog_textbox.see("end")
    source.window.chat_dialog_textbox.configure(state="disabled")


def window_chat_clear() -> None:
    source.window.chat_dialog_textbox.delete("1.0", "end")


def window_chat_progress_title_display(framework_model: AiFrameworkModel):
    progress_text = ''

    if isinstance(framework_model, AbstractAiFrameworkTaskModel):
        task = framework_model
        current_step = task.sub_task_current_index + 1
        total_steps = len(task.yaml.sub_tasks)
        progress_text = f"Задача: {task.title}  |  Прогресс: {current_step}/{total_steps}"
        global task_active
        task_active = task

    if isinstance(framework_model, AbstractAiFrameworkAgentModel):
        progress_text = f"Агент: {framework_model.title}"
        global agent_active
        agent_active = framework_model

    source.window.chat_dialog_task_active_label.configure(
        text=progress_text,
        fg_color="#1f538d"  # Меняем цвет на синий, когда задача активна
    )


def window_chat_active_task_clear():
    source.window.chat_dialog_task_active_label.configure(text='Нет активной задачи')


def window_chat_voice_toggle(state: int):
    source.window.chat_voice_listening = False if state == 0 else True


def window_chat_voice_state_get() -> bool:
    return source.window.chat_voice_listening


def window_chat_loading_start():
    """Показывает индикатор и запускает анимацию"""
    source.window.chat_progress_bar.pack(fill="x", padx=15, pady=2, before=source.window.chat_dialog_task_active_label)
    source.window.chat_progress_bar.start()
    source.window.chat_agent_status_label.configure(text="● Агент думает...", text_color="#FFD3B6")


def window_chat_loading_stop():
    """Скрывает индикатор"""
    source.window.chat_progress_bar.stop()
    source.window.chat_progress_bar.pack_forget()
    source.window.chat_agent_status_label.configure(text="")


def agent_animate_pulse(widget, state=True):
    if not widget.winfo_exists(): return

    current_color = widget.cget("fg_color")
    if current_color == "#444444":
        return

    color = "#3a7ebf" if state else "#1f3d5e"
    widget.configure(fg_color=color)

    widget.after(600, lambda: agent_animate_pulse(widget, not state))


def agent_item_draw(agent_name: str, parent_frame, is_active: bool = False):
    # Контейнер
    agent_card = ctk.CTkFrame(
        parent_frame,
        fg_color="#3d424b" if is_active else "#2b2b2b",
        corner_radius=8,
        cursor="hand2"
    )
    agent_card.pack(fill="x", padx=5, pady=5)

    # Индикатор
    status_indicator = ctk.CTkButton(
        agent_card, text="", width=24, height=24, corner_radius=7,
        fg_color="#1f538d" if is_active else "#444444",
        hover=False, state="disabled", cursor="hand2"
    )
    status_indicator.pack(side="left", padx=10, pady=10)

    # Текст
    name_label = ctk.CTkLabel(
        agent_card, text=agent_name, font=("Arial", 26, "bold"),
        text_color="#A8E6CF" if is_active else "white",
        cursor="hand2"
    )
    name_label.pack(side="left", padx=5)

    # Сохраняем в глобальный словарь
    agents_widgets_storage[agent_name] = (agent_card, status_indicator, name_label)

    # Функция-обертка для клика
    def on_click(event):
        select_agent(agent_name)

    # Привязываем клик к фрейму и лейблу (чтобы попадать по всей области)
    agent_card.bind("<Button-1>", on_click)
    name_label.bind("<Button-1>", on_click)

    if is_active:
        agent_animate_pulse(status_indicator)
        global agent_active
        agent_active = ai_agent_manager.load(agent_name)

    return agent_card


def select_agent(selected_name):
    for name, (card, indicator, label) in agents_widgets_storage.items():
        if name == selected_name:
            # Делаем активным
            card.configure(fg_color="#3d424b")  # Подсветка карточки
            indicator.configure(fg_color="#1f538d")
            label.configure(text_color="#A8E6CF")
            # Запускаем анимацию мигания (если еще не запущена)
            agent_animate_pulse(indicator, True)
            global agent_active
            agent_active = ai_agent_manager.load(selected_name)
        else:
            # Делаем неактивным
            card.configure(fg_color="#2b2b2b")
            indicator.configure(fg_color="#444444")
            label.configure(text_color="white")