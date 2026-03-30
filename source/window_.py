import os
import threading
import traceback
import queue
import source.window
import customtkinter as ctk

from typing import Dict, Any
from source.ai.framework.ai_framework import AiFrameworkModel
from source.ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel
from source.ai.framework.ai_framework_task_model import AbstractAiFrameworkTaskModel
from source.logging_ import logger_info
from source.queue_ import queue_get
from source.window.component import AiPopupWindow
from source.window.tab_chat import TabChat
from source.window.tab_log import TabLog
from source.window.tab_mcp import TabMcp
from source.window.tab_settings import TabSettings
from source.window.tab_tool import TabTool
from source.window.ui import (
    window_chat_message_add,
    window_chat_active_task_clear,
)
from source.window.ui_agent import agent_complete, agent_check_queue
from source.window.ui_task import task_complete, task_check_queue

chat_message_last_get = None


class WindowAi(ctk.CTk):
    def __init__(self):
        super().__init__()

        self._mcp_config_lock = threading.Lock()
        self.tool_update_queue = queue.Queue()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Центрирование окна
        width, height = 1900, 1200
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2) - (self.winfo_screenheight() // 8)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.title("AI Window")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # Настраиваем структуру вкладок (здесь только ссылки на классы, объекты не создаем!)
        self.tabs_metadata: Dict[str, Dict[str, Any]] = {
            "Настройки": {"class": TabSettings, "instance": None},
            "Чат": {"class": TabChat, "instance": None},
            "Логи": {"class": TabLog, "instance": None},
            "Инструменты": {"class": TabTool, "instance": None},
            "MCP серверы": {"class": TabMcp, "instance": None},
        }

        # Добавляем сами вкладки в UI
        for name in self.tabs_metadata:
            self.tabview.add(name)

        self.tabview._segmented_button.configure(font=("Arial", 27, "bold"))
        self.tabview.configure(command=self.on_tab_changed)

        # Ставим фокус на "Чат" и триггерим отрисовку ТОЛЬКО этой вкладки
        self.tabview.set("Чат")
        self.on_tab_changed()

        # Очереди и протоколы
        self.queue_chat()
        self.queue_tools()
        self.queue_task_complete()

        self.protocol("WM_DELETE_WINDOW", self.window_close)
        self.after(100, lambda: agent_check_queue(self))
        self.after(100, lambda: task_check_queue(self))

    def on_tab_changed(self):
        tab_name = self.tabview.get()
        info = self.tabs_metadata.get(tab_name)

        if info and info["instance"] is None:
            print(f"[DEBUG] Ленивая загрузка вкладки: {tab_name}")
            parent_frame = self.tabview.tab(tab_name)

            # 1. Создаем экземпляр
            if tab_name in ["Инструменты", "MCP серверы"]:
                info["instance"] = info["class"](master=self)
            else:
                info["instance"] = info["class"]()

            mapping = {
                "Настройки": "tab_settings_setup",
                "Чат": "tab_chat_setup",
                "Логи": "tab_log_setup",
                "Инструменты": "tab_tool_setup",
                "MCP серверы": "tab_mcp_setup"
            }

            method_name = mapping.get(tab_name)

            if method_name:
                setup_method = getattr(info["instance"], method_name)
                setup_method(parent_frame)
            else:
                print(f"[ERROR] Не найден метод setup для вкладки: {tab_name}")

    def queue_chat(self):
        global chat_message_last_get
        try:
            message = queue_get()['chat'].get_nowait()
            logger_info(f'💬 Сообщение из очереди "chat": {message}')

            if chat_message_last_get == message:
                self.after(100, self.queue_chat)
                return

            chat_message_last_get = message

            if isinstance(message, dict):
                text = message.get("text", "Пустой текст")
                who = message.get("who", "agent")
                window_chat_message_add(text, who)

                if message.get("need_response", False):
                    try:
                        source.window.chat_agent_status_label.configure(
                            text="💬 Агент ждет вашего ответа..",
                            text_color="#A8E6CF"
                        )
                        source.window.chat_progress_bar.configure(
                            progress_color="#E33D1B"
                        )
                    except AttributeError:
                        print("[WARN] chat_agent_status_label не найден")

                    AiPopupWindow(self, text)

        except queue.Empty:
            pass
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ 💬 Ошибка в queue_chat: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

        self.after(100, self.queue_chat)

    def queue_tools(self):
        try:
            message = queue_get()['tool'].get_nowait()
            logger_info(f"🛠 Сообщение из очереди queue_tool {message}")

            tab_tool_info = self.tabs_metadata.get("Инструменты")
            if tab_tool_info and tab_tool_info["instance"]:
                tab_tool_info["instance"].tab_tool_setup()
            else:
                logger_info("🛠 Вкладка 'Инструменты' еще не инициализирована, пропускаем обновление UI")

        except queue.Empty:
            pass
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ 🛠 Ошибка в queue_tools: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

        self.after(100, self.queue_tools)

    def queue_task_complete(self):
        try:
            message = queue_get()['task_complete'].get_nowait()
            logger_info(f"🛠 Сообщение из очереди task_complete {message}")
            window_chat_active_task_clear()

        except queue.Empty:
            pass
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ 🛠 Ошибка в task_complete: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

        self.after(100, self.queue_task_complete)

    def thread_monitor(self, framework_model: AiFrameworkModel):
        try:
            if isinstance(framework_model, AbstractAiFrameworkTaskModel):
                task_complete(framework_model)
            if isinstance(framework_model, AbstractAiFrameworkAgentModel):
                agent_complete(framework_model)

            logger_info(f"🚀 Поток '{framework_model.name}' завершён, слот освобождён.")
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при обновлении UI после завершения задачи {framework_model.name}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

    def window_close(self):
        print("Принудительное завершение...")

        # 1. Останавливаем обработку событий Tkinter
        self.withdraw()  # Сразу прячем окно с экрана, чтобы юзер не ждал

        try:
            # 2. Быстрая очистка асинхронки (если она не зависает)
            from source.async_ import async_waiting_clear
            async_waiting_clear()
        except:
            pass

        # 3. Полный выход без церемоний
        # Мы не вызываем self.quit() и destroy(), если хотим мгновенно убить процесс
        os._exit(0)
