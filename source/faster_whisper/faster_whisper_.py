import threading
import time
import traceback
import speech_recognition as sr
import numpy as np

from faster_whisper import WhisperModel

from config.config import config_get
from logging_.logging_ import logger_info
from microphone.microphone import microphone_create_microphone
from queue_.queue_ import queue_get
from source.faster_whisper.faster_whisper_model import faster_whisper_create_model
from source.window.ui import window_chat_voice_state_get


def faster_whisper_enable():
    (threading.Thread(
        target=faster_whisper_listening,
        args=(
            faster_whisper_create_model(),
            microphone_create_microphone()
        ),
        daemon=True
    )).start()
    logger_info('🗣️ faster_whisper запущен в потоке')


def faster_whisper_listening(
        whisper_model: WhisperModel,
        recognizer: sr.Recognizer
) -> None:
    recognizer.energy_threshold = 300

    with sr.Microphone(sample_rate=16000) as source:
        logger_info("🎙️ Микрофон готов к работе")

        while True:
            try:
                if not window_chat_voice_state_get():
                    time.sleep(0.05)  # Меньше задержка для отзывчивости
                    continue

                print("🎤 Запись пошла (держите кнопку)...")

                frames = []
                while window_chat_voice_state_get():
                    data = source.stream.read(1024)
                    frames.append(data)

                if not frames:
                    continue

                print("🎤 Кнопка отпущена. Обработка...")

                # Склеиваем и конвертируем
                raw_data = b"".join(frames)
                audio_data = np.frombuffer(raw_data, np.int16).flatten().astype(np.float32) / 32768.0

                # 3. Транскрибация
                segments, _ = whisper_model.transcribe(
                    audio_data,
                    language=config_get('whisper_language'),
                    vad_filter=True,
                    beam_size=1  # Для максимальной скорости на CPU
                )

                text = "".join([segment.text for segment in segments]).strip()

                if text:
                    logger_info(f"🗣️️ Распознано: {text}")
                    queue_get()['chat'].put({"text": text, "who": 'iam'})

                    queue_get()['chat_input_send'].put(text)
                else:
                    logger_info("⚠️ Речь не распознана.")

            except Exception as e:
                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Ошибка аудио: {e}"
                    f"Полный стек вызовов:\n{backtrace}"
                )
                break