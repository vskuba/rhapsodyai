import threading

import time

import speech_recognition as sr
import numpy as np

from faster_whisper import WhisperModel

from source.ai.framework.pydanticai.ai_pydantic_task import AiPydanticTaskManager
from source.config import config_get
from source.logging_ import logger_info
from source.microphone import microphone_create_microphone
from source.queue import queue_get
from source.window.ui import window_chat_voice_state_get


def faster_whisper_enable():
    (threading.Thread(
        target=faster_whisper_listening,
        args=(
            faster_whisper_create_model(config_get('whisper_model_name')),
            microphone_create_microphone()
        ),
        daemon=True
    )).start()
    logger_info('faster_whisper enabled')

def faster_whisper_create_model(whisper_model_name: str) -> WhisperModel:
    """
    Создает Whisper модель для прослушивания звуков
    """
    return WhisperModel(whisper_model_name, device="cpu", compute_type="int8", cpu_threads=16, num_workers=16)


def faster_whisper_listening(
        whisper_model: WhisperModel,
        recognizer: sr.Recognizer
) -> None:
    """
    Слушает микрофон. Трансформирует звук в текст и отдает текст как результат.
    """
    with sr.Microphone(sample_rate=16000) as source:
        print(">>> Я вас слушаю... (говорите)")

        while True:
            try:

                if not window_chat_voice_state_get():
                    time.sleep(0.3)
                    continue

                # print('Язык распознавания: %s' % config['whisper_language'])
                # Записываем фразу до наступления тишины
                audio = recognizer.listen(source, phrase_time_limit=5)

                # Конвертируем байты в формат, который понимает Whisper (float32)
                audio_data = np.frombuffer(audio.get_raw_data(), np.int16).flatten().astype(np.float32) / 32768.0

                # Распознаем
                segments, info = whisper_model.transcribe(
                    audio_data,
                    language=config_get('whisper_language'),
                    beam_size=1,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.5,
                    repetition_penalty=1.0,
                    vad_filter=True,
                    best_of=1
                )

                text = "".join([segment.text for segment in segments]).strip()

                # print("Результат звука в текст: %s" % text)

                if not text or not window_chat_voice_state_get():
                    time.sleep(0.3)
                    continue

                queue_get()['chat'].put({
                    "text": text,
                    "who": 'iam'
                })

                ai_task_manager = AiPydanticTaskManager()
                welcome_task = ai_task_manager.load(config_get('welcome_task_name'), {'question': text})
                if ai_task_manager.task_active_get().name == welcome_task.name:
                    queue_get()['task'].put(welcome_task)

                # print(">>> Слушаю далее... (говорите)")

            except Exception as e:
                print(f"Ошибка: {e}")
