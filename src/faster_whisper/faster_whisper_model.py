import asyncio
import os

from faster_whisper import WhisperModel
from config.config import config_get
from setting_.setting_ import setting_get

_model_cache: dict[str, WhisperModel] = {}


async def faster_whisper_model_create_model(model_name: str | None = None) -> WhisperModel:
    """
    Возвращает Whisper модель для распознавания речи, создавая ее лениво и
    переиспользуя между запросами (загрузка весов с диска - самая дорогая
    часть, повторять ее на каждый голосовой запрос не нужно).
    Название модели — настройка 'whisper_model_name' (страница настроек);
    фолбэк — env WHISPER_MODEL_NAME, затем 'base' (предзагружена в docker-образ).
    """
    if not model_name:
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


async def faster_whisper_model_transcribe(
    file_path: str,
    model_name: str | None = None,
    language: str | None = None,
    beam_size: int = 5,
) -> str:
    """
    Транскрибирует аудиофайл в текст. vad_filter отсеивает тишину/фон до
    распознавания и сегменты с высоким no_speech_prob отбрасываются - без
    этого faster-whisper на пустом звуке нередко галлюцинирует однословные
    артефакты вроде "You"/"Thank you." (известная особенность моделей Whisper,
    обученных на YouTube-субтитрах, где тишине часто предшествовали эти фразы).

    model_name / language / beam_size вынесены в параметры ради потокового
    режима (`/api/stt/chunk`), где чанк надо расшифровать быстрее, чем он
    длится. Замеры на 26.6 с русской речи (20.08.2026):

      * явный `language` экономит 39% времени: автоопределение гоняет модель
        по началу КАЖДОГО чанка заново, и на коротком куске это заметная доля;
      * модель побольше делает целый файл лучше (small 16.4% ошибок против
        base 20.5%), а чанки - ХУЖЕ (34.2%) и перестаёт успевать: нарезка рвёт
        контекст, а большая модель на него сильнее опирается;
      * `beam_size=1` вдвое быстрее, но ломает слова - годится показать живой
        текст, не годится сохранить.

    Умолчания оставлены прежними: старые вызовы работают как работали.

    Возвращает ТОЛЬКО текст — обёртка над `faster_whisper_model_detect()`. Нужен ещё
    и определённый язык (авторежим диктовки) — зовите её напрямую.
    """
    detected = await faster_whisper_model_detect(file_path, model_name, language, beam_size)

    return detected["text"]


async def faster_whisper_model_detect(
    file_path: str,
    model_name: str | None = None,
    language: str | None = None,
    beam_size: int = 5,
) -> dict:
    """Расшифровка вместе с определённым языком: `{text, language, probability}`.

    Язык Whisper определяет ВСЕГДА — и когда его задали, и когда нет; в первом
    случае просто возвращает заданный. Считается он при том же проходе, что и
    текст, то есть **достаётся бесплатно**: до этой функции второй элемент
    ответа `model.transcribe()` молча отбрасывался (`segments, _ = ...`).

    Зачем понадобился: BlogAi даёт человеку диктовать в авторежиме, и тогда
    язык записи не знает никто. Без него черновик оставался с пустым языком, а
    сосед угадывал его по буквам-приметам текста — при том что настоящий ответ
    всё это время лежал рядом и выбрасывался.

    `probability` отдаём вместе с языком: на коротком чанке уверенность бывает
    низкой, и решать, верить ли ответу, должен вызывающий — здесь порога нет.
    """
    model = await faster_whisper_model_create_model(model_name)

    return await asyncio.to_thread(
        _transcribe_blocking, model, file_path, beam_size, language)


def _transcribe_blocking(model: WhisperModel, file_path: str,
                         beam_size: int, language: str | None) -> dict:
    """Сама расшифровка. Синхронная, поэтому вызывается ТОЛЬКО в отдельном потоке.

    ⚠ Прямой вызов из корутины блокирует цикл событий целиком: пока считается
    расшифровка, сервис не отвечает НИ НА ЧТО. Наступили на это в «Блокноте» —
    короткий чанк, попавший в окно длинной расшифровки, ждал 27 секунд вместо
    четырёх и падал по таймауту. Со стороны это выглядело как «живой текст не
    работает», хотя дело было в заблокированном цикле.

    `model.transcribe` возвращает ленивый генератор: работа идёт при переборе
    сегментов, поэтому перебор тоже обязан быть внутри потока.

    ⚠ `info` берётся ДО перебора сегментов и это правильно: язык определяется
    на первых секундах, ещё до расшифровки, и в объекте он уже есть. А вот сам
    текст до перебора пуст — генератор ленивый.
    """
    segments, info = model.transcribe(
        file_path,
        beam_size=beam_size,
        best_of=beam_size,
        language=language,
        condition_on_previous_text=False,
        vad_filter=True,
    )

    text = "".join(s.text for s in segments if s.no_speech_prob < 0.6).strip()

    return {
        "text": text,
        "language": str(getattr(info, "language", "") or ""),
        "probability": float(getattr(info, "language_probability", 0.0) or 0.0),
    }
