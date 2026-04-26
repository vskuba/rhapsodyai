import time
import src.window

from ai.framework.ai_framework import AiFrameworkModel
from ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel
from ai.framework.ai_framework_task_model import AbstractAiFrameworkTaskModel

from queue_.queue_ import queue_get
from src.filesystem import open_file_in_editor
from state.state import state_get


def window_chat_input_send(text: str) -> None:
    if not text or not text.strip():
        return

    window_chat_message_add(text, 'iam')
    window_chat_loading_start()

    queue_get('chat_input_send').put(text)

def window_chat_message_add(text: str, who: str) -> None:
    if not text or not text.strip():
        return

    src.window.chat_dialog_textbox.configure(state="normal")

    # Визуальные префиксы
    if who == 'iam':
        header = "👤 Я:"
        tag = "iam_tag"
    else:
        header = "🤖 Агент:"
        tag = "agent_tag"

    # Добавляем заголовок и само сообщение
    src.window.chat_dialog_textbox.insert("end", f"\n{header}\n", tag)
    src.window.chat_dialog_textbox.insert("end", f"{text.strip()}\n")

    src.window.chat_dialog_textbox.see("end")
    src.window.chat_dialog_textbox.configure(state="disabled")


def window_chat_clear() -> None:
    src.window.chat_dialog_textbox.delete("1.0", "end")


def window_chat_progress_title_display(framework_model: AiFrameworkModel):
    progress_text = ''

    if isinstance(framework_model, AbstractAiFrameworkTaskModel):
        current_step = framework_model.sub_task_current_index + 1
        total_steps = len(framework_model.yaml.sub_tasks)
        progress_text = f"Задача: {framework_model.title}  |  Прогресс: {current_step}/{total_steps}"

    if isinstance(framework_model, AbstractAiFrameworkAgentModel):
        progress_text = f"Агент: {framework_model.title}"

    label = src.window.chat_dialog_task_active_label
    label.configure(
        text=progress_text,
        fg_color="#1f538d"  # Меняем цвет на синий, когда задача активна
    )
    label.unbind("<Button-1>")


def window_chat_active_task_clear():
    last_report = state_get('last_report_path')
    label = src.window.chat_dialog_task_active_label

    if last_report:
        label.configure(text='Последний отчет', cursor="hand2")
        label.bind("<Button-1>", lambda e: open_file_in_editor(str(last_report)))
    else:
        label.configure(text='Нет активной задачи')
        label.unbind("<Button-1>")


def window_chat_voice_toggle(state: int):
    src.window.chat_voice_listening = False if state == 0 else True


def window_chat_voice_state_get() -> bool:
    return src.window.chat_voice_listening


def window_chat_loading_start():
    """Показывает индикатор и запускает анимацию"""
    src.window.chat_progress_bar.pack(fill="x", padx=15, pady=2, before=src.window.chat_dialog_task_active_label)
    src.window.chat_progress_bar.start()
    src.window.chat_agent_status_label.configure(text="● Агент думает...", text_color="#FFD3B6")


def window_chat_loading_stop():
    """Скрывает индикатор"""
    src.window.chat_progress_bar.stop()
    src.window.chat_progress_bar.pack_forget()
    src.window.chat_agent_status_label.configure(text="")

def container_clear(container):
    """Удаляет все дочерние виджеты из контейнера"""
    for widget in container.winfo_children():
        widget.destroy()