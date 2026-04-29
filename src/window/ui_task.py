import queue
import time
import traceback

import CTkToolTip
import customtkinter as ctk
import src.window
from ai.framework.ai_framework_task import AbstractAiFrameworkTaskModel
from ai.framework.pydantic.ai_framework_task_pydantic import AiFrameworkTaskManagerPydantic

from async_.async_ import async_loop_task_cancel, async_waiting_is_active, async_waiting_clear
from src.filesystem import open_file_in_editor
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from state.state import state_get, state_set
from src.window.ui import window_chat_loading_start, window_chat_progress_title_display, \
    window_chat_active_task_clear, window_chat_loading_stop

ai_task_manager = AiFrameworkTaskManagerPydantic()

task_active: AbstractAiFrameworkTaskModel | None = None


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

    if state_get('agent_active_type') and state_get('agent_active_type') != 'task': # другой тип агента уже запущен
        return

    if current_status == "▶":
        # проверяеи валидацию yml
        ai_task_manager.load(task.name)
        # СТАТУС 2: АКТИВНЫЙ (Запуск -> Пульсация красным)
        button.configure(text="⏹")
        task_item_animate_pulse(button, ["#7C2A2A", "#A93232", "#FF4C4C", "#A93232"], "⏹")
        # print(f"Задача {t_name} активна и пульсирует.")
        window_chat_loading_start()  # запуск индикатора под чатом
        logger_info(f'▶ Отправляю задачу в очередь: "{task.title}"')
        queue_get('task').put(task)
        window_chat_progress_title_display(task)
        global task_active
        task_active = task
        state_set('agent_active_type', 'task')
    else:
        async_loop_task_cancel(task.name)
        queue_get('chat').put({'text': f'Запрос на остановку задачи {task.title}', 'who': 'agent'})
        task_active = None
        state_set('agent_active_type', None)


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
        src.window.chat_task_btn_state[task.name] = btn_state

        btn_yml = ctk.CTkButton(
            actions_frame, text="📄 .yml", width=110, height=45,
            font=("Arial", 24), fg_color="#3d65a1",
            command=lambda: open_file_in_editor(ai_task_manager.filepath_get(task_name))
        )
        btn_yml.pack(side="left", padx=10)


def task_complete(framework_model: AbstractAiFrameworkTaskModel):
    window_chat_loading_stop()
    src.window.chat_task_btn_state[framework_model.name].configure(
        text="▶",
        fg_color="#2D5A27",
        hover_color="#3E7B35"
    )
    window_chat_active_task_clear()
    state_set('agent_active_type', None)

    global task_active
    task_active = None


def task_check_queue(root):
    try:
        if state_get('agent_active_type') != 'task':
            root.after(100, lambda: task_check_queue(root))
            return

        text = ''
        try:
            text = queue_get('chat_input_send').get_nowait()
        except queue.Empty:
            pass

        if text:
            if task_active and async_waiting_is_active():
                queue_get('chat_response').put(text)
                time.sleep(0.05)

                async_waiting_clear()
                src.window.chat_progress_bar.configure(
                    progress_color="#2ecc71"
                )
                window_chat_loading_stop()

    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Сбой в запуске ai framework: {e}."
            f"Полный стек вызовов:\n{backtrace}"
        )

    root.after(100, lambda: task_check_queue(root))
