from faster_whisper import WhisperModel


def faster_whisper_create_model(whisper_model_name: str) -> WhisperModel:
    """
    Создает Whisper модель для прослушивания звуков
    """
    return WhisperModel(whisper_model_name, device="cpu", compute_type="int8", cpu_threads=16, num_workers=16)
