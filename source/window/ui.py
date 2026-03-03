import time

import CTkToolTip
import customtkinter as ctk
import source.window
import source.ai.ai_thread

from source.ai.ai_task import AbstractAiTask
from source.ai.framework.pydanticai.ai_pydantic_task import AiPydanticTaskManager
from source.async_ import async_waiting_is_active, async_waiting_clear, async_loop_task_cancel
from source.filesystem import open_file_in_editor
from source.logging_ import logger_info
from source.queue import queue_get

ai_task_manager = AiPydanticTaskManager()


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


def task_item_toggle(button, task: AbstractAiTask):
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
        queue_get()['task'].put(task)
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


def window_chat_active_task_display(task: AbstractAiTask):
    current_step = task.sub_task_current_index + 1
    total_steps = len(task.yaml.sub_tasks)
    progress_text = f"Задача: {task.title}  |  Прогресс: {current_step}/{total_steps}"
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
