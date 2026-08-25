"""Расшифровка речи для соседних проектов: потоковая и итоговая.

Модель Whisper живёт здесь, а голос присылает **BlogAi** (Блокнот): человек
диктует мысль в Telegram-приложение, текст становится черновиком.

Точек две, и это не дублирование, а следствие замеров (`blog_stt.md` в BlogAi,
20.08.2026 на 26.6 с русской речи с известным эталоном):

| Модель | Целиком | Чанки 5 с | Успевает за речью |
|--------|--------:|----------:|-------------------|
| `base` | 20.5% ошибок | 26.0% | да, 3.2 с на чанк |
| `small` | **16.4%** | 34.2% | **нет**, 7.0 с на чанк |

Большая модель делает целый файл лучше, а нарезанный - заметно хуже: чанки рвут
контекст, а она на него сильнее опирается. Поэтому:

* `/chunk` - пока человек говорит. Быстрая модель, живой текст на экран. 26%
  ошибок здесь не беда: это обратная связь «идёт запись, вот примерно о чём»;
* `/final` - когда закончил. Точная модель по целому файлу, и вот ЭТО
  сохраняется черновиком.

Итог чанков склеивать и сохранять нельзя - он на десять пунктов хуже.

Существующий `/telegram-app/chat/voice` не тронут: он берёт файл целиком и
работает.
"""

import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.faster_whisper.faster_whisper_model import faster_whisper_detect

router = APIRouter(prefix="/api/stt", tags=["stt"])

# Модель для живого показа. Маленькая намеренно: см. шапку модуля.
STT_CHUNK_MODEL = "base"

# Модель для итогового текста. Медленнее, но точнее, и торопиться ей некуда -
# человек уже договорил.
STT_FINAL_MODEL = "small"

# Потолок размера. Чанк - пять секунд моно 16 кГц, это ~160 КБ; запись целиком
# редко бывает длиннее получаса. Числа с запасом, но не безграничные: точка
# принимает файл в память, и «загрузить сюда фильм» не должно валить процесс.
STT_CHUNK_MAX_BYTES = 4 * 1024 * 1024
STT_FINAL_MAX_BYTES = 200 * 1024 * 1024


@router.post("/chunk")
async def stt_chunk(
    file: UploadFile = File(...),
    language: str = Form("ru"),
    user=Depends(AuthChecker([AuthPermission.STT_CREATE])),
):
    """Кусок записи -> текст. Быстро и приблизительно, для показа на экране.

    `language` по умолчанию `ru`, а не автоопределение: замер показал 39%
    экономии времени даром. Автоопределение остаётся доступным - передайте
    пустую строку, - но для потока оно того не стоит.

    В ответе рядом с текстом идут `language` и `probability` - см. шапку модуля.
    """
    detected = await _transcribe_upload(file, STT_CHUNK_MAX_BYTES,
                                        model_name=STT_CHUNK_MODEL,
                                        language=(language or None))

    return {"result": detected["text"], "language": detected["language"],
            "probability": detected["probability"]}


@router.post("/final")
async def stt_final(
    file: UploadFile = File(...),
    language: str = Form("ru"),
    user=Depends(AuthChecker([AuthPermission.STT_CREATE])),
):
    """Запись целиком -> текст. Медленнее и точнее; это и есть черновик.

    Определённый язык здесь надёжнее, чем у чанка: модель слушает всю запись, а
    не пять секунд. Именно этот ответ и стоит сохранять черновику.
    """
    detected = await _transcribe_upload(file, STT_FINAL_MAX_BYTES,
                                        model_name=STT_FINAL_MODEL,
                                        language=(language or None))

    return {"result": detected["text"], "language": detected["language"],
            "probability": detected["probability"]}


# ---------------------------------------------------------------------------

async def _transcribe_upload(file: UploadFile, max_bytes: int,
                             model_name: str, language: str | None) -> dict:
    """Читает загруженный файл, расшифровывает, убирает за собой.

    Отдаёт `{text, language, probability}` — то же, что `faster_whisper_detect`.

    Файл кладётся на диск, потому что faster-whisper принимает путь, а не
    байты. Временный каталог, а не рабочая папка: параллельные запросы не
    должны драться за одно имя (в `/telegram-app/chat/voice` имя собрано из
    имени загруженного файла - там это безопасно только потому, что звонящий
    один).
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="пустой файл")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"файл больше {max_bytes // (1024 * 1024)} МБ")

    handle, path = tempfile.mkstemp(suffix=".wav", prefix="stt_")
    os.close(handle)
    try:
        with open(path, "wb") as target:
            target.write(content)

        return await faster_whisper_detect(
            path, model_name=model_name, language=language)
    finally:
        # Не оставляем мусор даже когда расшифровка упала: точку дёргают
        # десятками раз за одну запись.
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
