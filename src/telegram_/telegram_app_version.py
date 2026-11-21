"""
Отпечаток фронтенда Mini App: по нему открытое приложение узнаёт, что код обновился.

Telegram держит Mini App в памяти: свёрнутое стрелкой ∨ при возврате показывает ту же
страницу, без новой загрузки, — после выкладки человек работает со старым кодом и не
видит новых кнопок. Пинг (`/telegram-app/ping`) отдаёт этот отпечаток, страница
запоминает его при загрузке и, увидев другой, перезагружается сама.

Отпечаток — хэш содержимого файлов Mini App, а не время старта процесса: перезапуск без
правки фронтенда не должен дёргать человека перезагрузкой. Считается с коротким кэшем, а
не один раз на старте: локально файлы смонтированы из репозитория и меняются без
перезапуска.
"""
import glob
import hashlib
import os
import time

from config.config import config_get

# Что входит в отпечаток — относительно `<DATA_DIR>/<UVICORN_DIR>`.
TELEGRAM_APP_VERSION_PATTERNS = (
    'template/telegram_app.html',
    'public/css/telegram_app.css',
    'public/js/telegram_app/*.js',
)
# Сколько секунд живёт посчитанный отпечаток: пинг идёт раз в 5 с с каждого окна.
TELEGRAM_APP_VERSION_TTL = 10

_cache = {'at': 0.0, 'version': ''}


def telegram_app_version_get() -> str:
    """Короткий хэш файлов Mini App; пустая строка, если файлов не нашлось."""
    now = time.monotonic()
    if _cache['version'] and now - _cache['at'] < TELEGRAM_APP_VERSION_TTL:
        return _cache['version']

    _cache['version'] = _telegram_app_version_compute()
    _cache['at'] = now
    return _cache['version']


def _telegram_app_version_compute() -> str:
    root = os.path.join(_project_root(), config_get('DATA_DIR'), config_get('UVICORN_DIR'))
    paths = sorted({path for pattern in TELEGRAM_APP_VERSION_PATTERNS
                    for path in glob.glob(os.path.join(root, pattern))})
    if not paths:
        return ''

    digest = hashlib.sha1()
    for path in paths:
        digest.update(os.path.relpath(path, root).encode())
        try:
            with open(path, 'rb') as f:
                digest.update(f.read())
        except OSError:
            continue
    return digest.hexdigest()[:12]


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
