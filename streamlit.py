import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# 1. Настройка страницы Streamlit
st.set_page_config(page_title="AI Engine Studio", page_icon="🚀", layout="wide")

st.title("🚀 Custom AI Engine Studio (Powered by GX10)")
st.subheader("Локальный бизнес-ассистент на базе Qwen3.6-35B")


# GX10: vLLM — адрес, ключ и модель берём из .env (GX10_* переменные)
GX10_API_URL = os.getenv("GX10_SMALL_API_URL", "")
GX10_API_KEY = os.getenv("GX10_API_KEY", "")
GX10_MODEL   = os.getenv("GX10_MODEL", "")

if not (GX10_API_URL and GX10_API_KEY and GX10_MODEL):
    st.error("Не заданы GX10_SMALL_API_URL / GX10_API_KEY / GX10_MODEL в .env")
    st.stop()


# 2. Инициализация клиента OpenAI для работы с GX10 vLLM
@st.cache_resource
def get_vllm_client():
    return OpenAI(base_url=GX10_API_URL, api_key=GX10_API_KEY)


client = get_vllm_client()

# 3. Сайдбар для настроек генерации и загрузки файлов
with st.sidebar:
    st.header("⚙️ Настройки")
    temperature = st.slider("Креативность (Temperature)", 0.0, 1.0, 0.7, step=0.1)
    max_tokens = st.number_input("Макс. токенов ответа", 100, 4000, 1000, step=100)

    st.write("---")
    st.header("📁 Контекст (Опционально)")
    # Загрузчик файлов (например, код, референсы песен, JSON токенов)
    uploaded_file = st.file_uploader("Загрузить файл референса (.txt, .json, .py)", type=["txt", "json", "py", "css"])

    file_context = ""
    if uploaded_file is not None:
        file_context = uploaded_file.read().decode("utf-8")
        st.success(f"Файл {uploaded_file.name} успешно считан в контекст!")

# 4. Инициализация истории чата в сессии Streamlit
if "messages" not in st.session_state:
    st.session_state.messages = []

# Отображение старых сообщений из истории при перезапуске скрипта
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 5. Обработка ввода нового сообщения от пользователя
if user_input := st.chat_input("Напишите ваш запрос здесь..."):
    # Выводим сообщение пользователя на экран
    with st.chat_message("user"):
        st.markdown(user_input)

    # Формируем финальный промпт с учетом загруженного файла
    final_prompt = user_input
    if file_context:
        final_prompt = f"ИСХОДНЫЕ ДАННЫЕ/КОНТЕКСТ:\n```\n{file_context}\n```\n\nЗАПРОС ПОЛЬЗОВАТЕЛЯ: {user_input}"

    # Добавляем в историю сессии
    st.session_state.messages.append({"role": "user", "content": final_prompt})

    # Выводим ответ модели со стримингом токенов
    with st.chat_message("assistant"):
        message_placeholder = st.empty()  # Блок, куда будут капать токены
        full_response = ""

        # Отправляем асинхронный запрос к вашему локальному движку vLLM
        with st.spinner("Думаю..."):
            stream = client.chat.completions.create(
                model=GX10_MODEL,
                messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True  # Включаем стриминг
            )

            # Читаем токены из чанка по мере их генерации со скоростью GX10
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    full_response += chunk.choices[0].delta.content
                    # Мгновенно обновляем интерфейс для пользователя
                    message_placeholder.markdown(full_response + "▌")

        # Убираем курсор генерации и выводим финальный текст
        message_placeholder.markdown(full_response)

    # Сохраняем ответ ассистента в историю
    st.session_state.messages.append({"role": "assistant", "content": full_response})