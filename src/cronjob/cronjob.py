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


class Cronjob:
    def __init__(self, json_request: CronjobJsonRequest):
        self.json_request = json_request

    async def execute(self) -> CronjobJsonResponse:
        current_process = None
        file_path = Path(self.json_request.cronjob_path)

        if not file_path.exists():
            return CronjobJsonResponse(status="error", error_message=f"Файл {file_path} не найден")

        if not file_path.is_file():
            return CronjobJsonResponse(status="error", error_message=f"{file_path} не является файлом")

        try:
            metadata = json.dumps(self.json_request.metadata)

            # Асинхронный запуск процесса
            current_process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(file_path),
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
