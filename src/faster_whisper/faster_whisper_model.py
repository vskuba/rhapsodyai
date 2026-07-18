from faster_whisper import WhisperModel
from config.config import config_get
from setting_.setting_ import setting_get


async def faster_whisper_create_model() -> WhisperModel:
    """
    Создает Whisper модель для распознавания речи.
    Название модели — настройка 'whisper_model_name' (страница настроек);
    фолбэк — env WHISPER_MODEL_NAME, затем 'base' (предзагружена в docker-образ).
    """
    model_name = await setting_get('whisper_model_name', config_get('whisper_model_name') or 'base')
    return WhisperModel(str(model_name), device="cpu", compute_type="int8", cpu_threads=16, num_workers=16)
