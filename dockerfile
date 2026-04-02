# Используем Python 3.12 (как в ваших логах)
FROM python:3.12-slim

# Устанавливаем системные зависимости для ffmpeg (нужен для Faster-Whisper и работы с голосом)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки
# --no-cache-dir экономит место в образе
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в контейнер
COPY . .

# Создаем папки для данных, если их нет (чтобы не было ошибок доступа)
RUN mkdir -p data/chroma_db data/history data/log data/report data/sqlite3

# Указываем переменную окружения, чтобы Python не буферизировал логи
ENV PYTHONUNBUFFERED=1

# Команда запуска (соответствует вашему main.py)
CMD ["python", "main.py"]