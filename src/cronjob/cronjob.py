import asyncio
import json
from pathlib import Path
import sys

from typing import Optional
from pydantic import BaseModel


class CronjobJsonRequest(BaseModel):
    cronjob_path: str
    metadata: dict = {}
    timeout: int = 120


class CronjobJsonResponse(BaseModel):
    status: str
    result: Optional[str] = None
    error_message: Optional[str] = None


# Каталог, из которого разрешено запускать. Сравнение идёт по **разрешённому**
# пути, а не по началу строки: `startswith('src/cronjob/')` пропускал
# `src/cronjob/../../main_telegram.py` — приставка на месте, а файл чужой.
# Запуск был проверен пробой: точка отвечала «Timeout exceeded», то есть
# `main_telegram.py` успел стартовать. Точка публична (`/cronjob` в белом списке
# `auth_middleware`), так что это был запуск любого `.py` установки кем угодно.
CRONJOB_DIR = Path('src/cronjob')


class Cronjob:
    def __init__(self, json_request: CronjobJsonRequest):
        self.json_request = json_request

    async def execute(self) -> CronjobJsonResponse:
        current_process = None

        cronjob_path = self.json_request.cronjob_path
        file_path = Path(cronjob_path)
        allowed_dir = CRONJOB_DIR.resolve()

        # ⚠ `resolve()` до сравнения: он раскрывает `..` и симлинки, то есть
        # отвечает на вопрос «куда путь ведёт», а не «как он записан».
        try:
            resolved = file_path.resolve()
            resolved.relative_to(allowed_dir)
        except (ValueError, OSError):
            return CronjobJsonResponse(status="error", error_message=f"Недопустимый путь к cronjob: {cronjob_path}")

        if resolved.suffix != '.py':
            return CronjobJsonResponse(status="error", error_message=f"Недопустимый путь к cronjob: {cronjob_path}")

        if not resolved.exists():
            return CronjobJsonResponse(status="error", error_message=f"Файл {file_path} не найден")

        if not resolved.is_file():
            return CronjobJsonResponse(status="error", error_message=f"{file_path} не является файлом")

        try:
            metadata = json.dumps(self.json_request.metadata)

            # ⚠ Запускается `resolved`, а не присланная строка: проверен был он,
            # и запустить обязан тот же путь, иначе проверка ничего не значит.
            current_process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(resolved),
                metadata,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            if self.json_request.timeout > 0:
                stdout, stderr = await asyncio.wait_for(
                    current_process.communicate(),
                    timeout=self.json_request.timeout
                )
            else:
                stdout, stderr = await current_process.communicate()

            stdout_res = stdout.decode().strip()
            stderr_res = stderr.decode().strip()

            if current_process.returncode == 0:
                return CronjobJsonResponse(
                    status="success",
                    result=stdout_res
                )
            else:
                return CronjobJsonResponse(
                    status="error",
                    error_message=f"{stderr_res}\n{stdout_res}".strip()
                )
        except asyncio.TimeoutError:
            if current_process:
                current_process.kill()
                await current_process.wait()
            return CronjobJsonResponse(
                status="error",
                error_message=f"Timeout exceeded ({self.json_request.timeout} sec)"
            )
        except Exception as e:
            return CronjobJsonResponse(
                status="error",
                error_message=str(e)
            )
