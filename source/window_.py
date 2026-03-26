import os
import threading
import time
import traceback
import queue
import source.window
import customtkinter as ctk

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
from source.window.ui_agent import agent_complete, agent_init
from source.window.ui_task import task_complete, task_init

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

        self.tabview.add("Настройки")
        self.tabview.add("Чат")
        self.tabview.add("Логи")
        self.tabview.add("Инструменты")
        self.tabview.add("MCP серверы")

        self.tabview.set("Чат")

        self.tabview._segmented_button.configure(font=("Arial", 27, "bold"))

        # Экземпляры вкладок
        self.tab_settings = TabSettings()
        self.tab_chat = TabChat()
        self.tab_log = TabLog()
        self.tab_tool = TabTool(master=self)
        self.tab_mcp = TabMcp(master=self)

        # Биндим переключение вкладок
        self.tabview.configure(command=self.on_tab_changed)

        # Первичная отрисовка активной вкладки
        self.on_tab_changed()

        # Запуск проверки очереди чата
        self.queue_chat()
        self.queue_tools()
        self.queue_task_complete()

        self.protocol("WM_DELETE_WINDOW", self.window_close)

        threading.Thread(target=agent_init, daemon=True).start()
        threading.Thread(target=task_init, daemon=True).start()

    def on_tab_changed(self):
        tab_name = self.tabview.get()
        print(f"[DEBUG] Открыта вкладка: {tab_name}")

        parent_frame = self.tabview.tab(tab_name)

        if tab_name == "Настройки":
            self.tab_settings.tab_settings_setup(parent_frame)
        elif tab_name == "Чат":
            self.tab_chat.tab_chat_setup(parent_frame)
        elif tab_name == "Логи":
            self.tab_log.tab_log_setup(parent_frame)
        elif tab_name == "Инструменты":
            self.tab_tool.tab_tool_setup(parent_frame)
        elif tab_name == "MCP серверы":
            self.tab_mcp.tab_mcp_setup(parent_frame)

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
            self.tab_tool.tab_tool_setup()

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
        print("Закрытие приложения...")

        try:
            from source.async_ import async_waiting_clear
            async_waiting_clear()
        except:
            pass

        time.sleep(0.3)

        self.quit()
        self.destroy()

        print("Принудительное завершение процесса...")
        os._exit(0)
