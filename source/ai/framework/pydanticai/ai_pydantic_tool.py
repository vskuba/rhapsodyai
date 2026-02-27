from typing import Callable
from source.ai.ai_tool import ai_tools_get
from source.async_ import async_waiting_start, async_waiting_clear
from source.queue import queue_get

chat_last_message: str = ''


def ai_pydantic_tools_get() -> list[Callable]:
    """
    Возращает список инструментов для Pydantic AI
    """
    return ai_tools_get() + [

        # ------ Chat
        chat_me,
        chat_me_question,

        # ------ Task
        task_abort
    ]


def task_abort(final_text: str) -> bool:
    """
    This function close active task.
    Argument final_text is used for display in task report.
    """
    print(f'Инструмент "task_abort" был вызван (final_text: "{final_text}").')
    queue_get()['task_abort'].put(True)
    queue_get()['chat'].put(
        {
            "text": final_text,
            "who": 'agent',
        }
    )
    return True


async def chat_me_question(question: str) -> str:
    """
    Этот инструмент чтобы задать вопрос и получить ответ.
    Аргумент функции вопрос от тебя.
    Функция вернет строку текст с ответом на вопрос.

    Важно: не формируй final_result по результатам этой функции, если это не прописано.
    """
    print(f'Инструмент "chat_me_question" был вызван (question: "{question}").')
    queue_get()['chat'].put(
        {
            "text": question,
            "who": 'agent',
            "need_response": True
        }
    )

    print('Задача уходит в режим ожидания моего ответа на вопрос: "%s"' % question)
    await async_waiting_start()

    response = """
    Пользователь ответил '{chat_last_message}'
    """.format(**{'chat_last_message': chat_last_message}).strip()
    print(response)

    return response


async def chat_me(text: str) -> str:
    """
    Этот инструмент для твоих мыслей и сообшений. Используй его чтобы отправить сообщение.
    Аргумент функции текстовая строка с твоим сообщением.
    Инструмент вернет слово 'Принято' как результат, чтобы ты понимал, что сообщение было отправлено пользователю.
    """
    print(f'Инструмент "chat_me" был вызван (text: "{text}").')
    queue_get()['chat'].put(
        {
            "text": text,
            "who": 'agent',
        }
    )

    return 'Принято'


def chat_last_message_set(text: str):
    global chat_last_message
    chat_last_message = text
