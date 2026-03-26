import time
import source.window
import source.ai.ai_thread
from source.ai.framework.ai_framework import AiFrameworkModel
from source.ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel
from source.ai.framework.ai_framework_task import AbstractAiFrameworkTaskModel
from source.queue_ import queue_get


def window_chat_input_send(text: str) -> None:
    if not text or not text.strip():
        return

    window_chat_message_add(text, 'iam')
    window_chat_loading_start()

    queue_get()['chat_input_send'].put(text)

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
        current_step = framework_model.sub_task_current_index + 1
        total_steps = len(framework_model.yaml.sub_tasks)
        progress_text = f"Задача: {framework_model.title}  |  Прогресс: {current_step}/{total_steps}"

    if isinstance(framework_model, AbstractAiFrameworkAgentModel):
        progress_text = f"Агент: {framework_model.title}"

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