import queue
import traceback
import source.window
import customtkinter as ctk

from ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel
from source.ai_pydantic.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic

from async_.async_ import async_loop_task_cancel
from source.filesystem import open_file_in_editor
from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from state.state import state_set, state_get
from source.window.ui import window_chat_progress_title_display, window_chat_loading_start, window_chat_loading_stop, \
    window_chat_active_task_clear

ai_agent_manager = AiFrameworkAgentManagerPydantic()
agents_widgets_storage = {}


def agent_active_indicator_pulse(widget, agent_name, state=True):
    if not widget.winfo_exists(): return

    active_agent = state_get('agent_active')
    if not active_agent or active_agent.name != agent_name:
        widget.configure(fg_color="#444444")
        return

    color = "#2ecc71" if state else "#1e8449"
    widget.configure(fg_color=color)
    widget.after(400, lambda: agent_active_indicator_pulse(widget, agent_name, not state))


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
    target_data = agents_widgets_storage.get(target_name)
    if not target_data: return

    state_set('agent_active', target_data["model"])
    window_chat_progress_title_display(target_data["model"])

    for name, widgets in agents_widgets_storage.items():
        indicator = widgets["indicator"]
        lbl = widgets["label"]

        if name == target_name:
            indicator.configure(fg_color="#2ecc71")
            lbl.configure(text_color="#A8E6CF")
            agent_active_indicator_pulse(indicator, name)
        else:
            indicator.configure(fg_color="#444444")
            lbl.configure(text_color="white")


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
    source.window.chat_agent_btn_state[agent_model.name] = btn_state

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
        "label": lbl_name,
        "model": agent_model
    }

    if is_active:
        state_set('agent_active', agent_model)
        agent_active_indicator_pulse(indicator, agent_model.name)

    return agent_item


def agent_complete(framework_model: AbstractAiFrameworkAgentModel):
    window_chat_loading_stop()
    window_chat_active_task_clear()
    source.window.chat_agent_btn_state[framework_model.name].configure(
        text="▶",
        fg_color="#444444",
        hover_color="#3E7B35",
        state="disabled",
        text_color_disabled="#888888"
    )
    state_set('agent_active_type', None)


def agent_check_queue(root):
    try:
        if state_get('agent_active_type'):
            root.after(100, lambda: agent_check_queue(root))
            return

        text = ''
        try:
            text = queue_get()['chat_input_send'].get_nowait()
        except queue.Empty:
            pass

        if text:
            agent_active = state_get('agent_active')
            if agent_active:
                state_set('agent_active_type', 'agent')
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

    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Сбой в запуске ai framework: {e}."
            f"Полный стек вызовов:\n{backtrace}"
        )

    root.after(100, lambda: agent_check_queue(root))
