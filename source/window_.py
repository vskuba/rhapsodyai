import os
import threading
import time
import traceback

import queue
import source.window
import customtkinter as ctk

from source.ai.ai_task import AbstractAiTask
from source.logging_ import logger_info
from source.queue import queue_get
from source.window.component import AiPopupWindow
from source.window.tab_chat import TabChat
from source.window.tab_log import TabLog
from source.window.tab_mcp import TabMcp
from source.window.tab_settings import TabSettings
from source.window.tab_tool import TabTool
from source.window.ui import (
    window_chat_message_add,
    window_chat_loading_stop,
    window_chat_active_task_clear,
)
from source.ai.framework.pydanticai.ai_pydantic_task import AiPydanticTaskManager

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

        self.protocol("WM_DELETE_WINDOW", self.window_close)

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
                    except AttributeError:
                        print("[WARN] chat_agent_status_label не найден")

                    AiPopupWindow(self, text, AiPydanticTaskManager().task_active_get())

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

    def thread_monitor(self, thread: threading.Thread, task: AbstractAiTask):
        if thread.is_alive():
            self.after(500, lambda: self.thread_monitor(thread, task))
        else:
            try:
                if task.name in source.ai.ai_thread.thread_task_started:
                    del source.ai.ai_thread.thread_task_started[task.name]
            except:
                pass

            try:
                source.window.chat_task_btn_state[task.name].configure(
                    text="▶",
                    fg_color="#2D5A27",
                    hover_color="#3E7B35"
                )
                window_chat_loading_stop()
                window_chat_active_task_clear()

                logger_info(f"🚀 Поток задачи '{task.name}' завершён, слот освобождён.")
            except Exception as e:
                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Ошибка при обновлении UI после завершения задачи {task.name}: {e}."
                    f"Полный стек вызовов:\n{backtrace}"
                )

    def window_close(self):
        print("Закрытие приложения...")

        try:
            from source.ai.ai_thread import thread_task_started
            for task in list(thread_task_started.values()):
                task.aborted = True
        except:
            pass

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