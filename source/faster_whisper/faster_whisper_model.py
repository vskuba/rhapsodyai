from faster_whisper import WhisperModel
from source.config import config_get


def faster_whisper_create_model() -> WhisperModel:
    """
    Создает Whisper модель для прослушивания звуков
    """
    return WhisperModel(config_get('whisper_model_name'), device="cpu", compute_type="int8", cpu_threads=16, num_workers=16)
