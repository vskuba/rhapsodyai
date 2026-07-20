import os

from faster_whisper import WhisperModel
from config.config import config_get
from setting_.setting_ import setting_get

_model_cache: dict[str, WhisperModel] = {}


async def faster_whisper_create_model() -> WhisperModel:
    """
    Возвращает Whisper модель для распознавания речи, создавая ее лениво и
    переиспользуя между запросами (загрузка весов с диска - самая дорогая
    часть, повторять ее на каждый голосовой запрос не нужно).
    Название модели — настройка 'whisper_model_name' (страница настроек);
    фолбэк — env WHISPER_MODEL_NAME, затем 'base' (предзагружена в docker-образ).
    """
    model_name = str(await setting_get('whisper_model_name', config_get('whisper_model_name') or 'base'))

    if model_name not in _model_cache:
        # cpu_count вместо фиксированных 16: на слабых VM (2 ядра на проде)
        # 16 потоков создают oversubscription и работают медленнее, а не быстрее
        cpu_threads = os.cpu_count() or 4
        _model_cache[model_name] = WhisperModel(
            model_name, device="cpu", compute_type="int8",
            cpu_threads=cpu_threads, num_workers=cpu_threads
        )

    return _model_cache[model_name]
