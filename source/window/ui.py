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
from source.queue_ import queue_get
from source.state import state_set, state_get

ai_task_manager = AiFrameworkTaskManagerPydantic()
ai_agent_manager = AiFrameworkAgentManagerPydantic()
agents_widgets_storage = {}

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
        async_loop_task_cancel(task.name)
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


def window_chat_input_send(text: str) -> None:
    if not text or not text.strip():
        return

    window_chat_message_add(text, 'iam')
    window_chat_loading_start()

    if agent_active_init(text):
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
        state_set('agent_active', framework_model)

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


def agent_active_indicator_pulse(widget, state=True):
    if not widget.winfo_exists(): return
    if widget.cget("fg_color") == "#444444": return

    color = "#2ecc71" if state else "#1e8449"
    widget.configure(fg_color=color)
    widget.after(700, lambda: agent_active_indicator_pulse(widget, not state))


def agent_active_indicator_running_pulse(widget, state=0):
    if not widget.winfo_exists(): return

    # Прекращаем, если кнопка перестала быть красной (остановили агента)
    current_color = widget.cget("fg_color")
    if current_color not in ["#7C2A2A", "#A93232", "#FF4C4C"]:
        return

    colors = ["#7C2A2A", "#A93232", "#FF4C4C", "#A93232"]
    next_state = (state + 1) % len(colors)

    widget.configure(fg_color=colors[state])
    widget.after(220, lambda: agent_active_indicator_running_pulse(widget, next_state))


def agent_active_indicator_running_stop_pulse(button, agent_model):
    async_loop_task_cancel(agent_model.name)
    queue_get()['chat'].put({'text': f'Запрос на остановку агента {agent_model.title}', 'who': 'agent'})
    logger_info(f"🛑 Запрос на остановку агента: {agent_model.title}")
    button.configure(
        state="disabled",
        text="▶",
        fg_color="#444444",
        text_color_disabled="#888888"
    )

def agent_active_switch(target_name):
    for name, widgets in agents_widgets_storage.items():
        indicator = widgets["indicator"]
        lbl = widgets["label"]
        # btn = widgets["btn_state"] # Теперь кнопка статична, она нам тут не нужна

        if name == target_name:
            indicator.configure(fg_color="#2ecc71")  # Зеленый кружок
            lbl.configure(text_color="#A8E6CF")
            # ЗАПУСКАЕМ мигание кружка
            agent_active_indicator_pulse(indicator)

            # Системная активация
            model = ai_agent_manager.load(name)
            state_set('agent_active', model)
            window_chat_progress_title_display(model)
        else:
            indicator.configure(fg_color="#444444")  # Серый кружок
            lbl.configure(text_color="white")


def agent_item_toggle(button, agent_model):
    current_status = button.cget("text")

    if current_status == "▶":
        # Переводим в состояние ЗАПУЩЕН
        button.configure(text="⏹", fg_color="#A93232")  # Красный квадрат
        agent_active_indicator_running_pulse(button)
        logger_info(f"🚀 Агент {agent_model.title} запущен")
        # Здесь ваша логика запуска процесса агента
    else:
        # Возвращаем в состояние АКТИВНЫЙ (но не запущенный)
        button.configure(text="▶", fg_color="#2D5A27")  # Зеленый плей
        logger_info(f"🛑 Агент {agent_model.title} остановлен")


def agent_item_draw(agent_model: AbstractAiFrameworkAgentModel, parent_frame, is_active: bool = False):
    agent_item = ctk.CTkFrame(parent_frame, fg_color="#2b2e34", corner_radius=6)
    agent_item.pack(fill="x", padx=5, pady=3)

    # --- ВЕРХНЯЯ ЧАСТЬ (Индикатор + Название) ---
    header_frame = ctk.CTkFrame(agent_item, fg_color="transparent")
    header_frame.pack(side="top", fill="x", padx=10, pady=(8, 0))

    # 1. Тот самый ЗЕЛЕНЫЙ КРУЖОК (теперь он здесь)
    indicator = ctk.CTkButton(
        header_frame, text="",
        width=20, height=20, corner_radius=10,  # Чуть меньше для заголовка
        fg_color="#2ecc71" if is_active else "#444444",
        hover=False,
        command=lambda: agent_active_switch(agent_model.name)
    )
    indicator.pack(side="left", padx=(5, 10))

    # 2. Название агента
    lbl_name = ctk.CTkLabel(
        header_frame, text=agent_model.title,
        font=("Arial", 28, "bold"), anchor="w",
        text_color="#A8E6CF" if is_active else "white",
        cursor="hand2"
    )
    lbl_name.pack(side="left", fill="x")
    lbl_name.bind("<Button-1>", lambda e: agent_active_switch(agent_model.name))

    # --- НИЖНЯЯ ЧАСТЬ (Кнопки действий) ---
    actions_frame = ctk.CTkFrame(agent_item, fg_color="transparent")
    actions_frame.pack(side="top", fill="x", padx=10, pady=10)

    # Кнопка PLAY (СЕРАЯ, как на скрине)
    btn_state = ctk.CTkButton(
        actions_frame, text="▶", width=70, height=45,
        font=("Arial", 28), fg_color="#444444",
        state="disabled", text_color_disabled="#888888",
        corner_radius=8
    )
    btn_state.pack(side="left", padx=5)

    # Кнопка YML
    btn_yml = ctk.CTkButton(
        actions_frame, text="📄 .yml", width=110, height=45,
        font=("Arial", 24), fg_color="#3d65a1",
        command=lambda: open_file_in_editor(ai_agent_manager.filepath_get(agent_model.name))
    )
    btn_yml.pack(side="left", padx=10)

    # Обновляем ссылки в хранилище
    agents_widgets_storage[agent_model.name] = {
        "indicator": indicator,
        "btn_state": btn_state,
        "label": lbl_name
    }

    if is_active:
        agent_active_indicator_pulse(indicator)
        state_set('agent_active', agent_model)

    return agent_item


def agent_active_init(text: str) -> bool:
    agent_active = state_get('agent_active')
    if agent_active:
        agent_active.prompt = text
        window_chat_progress_title_display(agent_active)
        queue_get()['agent'].put(agent_active)
        window_chat_loading_start()

        widgets = agents_widgets_storage.get(agent_active.name)
        if widgets:
            btn = widgets["btn_state"]
            # Делаем кнопку активной, меняем на красный Квадрат
            btn.configure(
                state="normal",
                text="⏹",
                fg_color="#A93232",
                # При нажатии вызываем отмену
                command=lambda b=btn, a=agent_active: agent_active_indicator_running_stop_pulse(b, a)
            )
            agent_active_indicator_running_pulse(btn)

        return True
    return False
