"""
Список моделей для селекта на `/admin/team` — из каталога самой оболочки.

Почему не из справочника `llm`. Там модели, которые умеет вызывать этот проект, и
он шире: в нём есть строки, под которые у `claude-shell` прокси не описан. Выбрав
такую, человек получил бы отказ оболочки уже в терминале — список обещал бы больше,
чем оболочка умеет.

Источник истины — `claude-shell/llm_models.yaml`: ровно те модели, под
которые оболочка умеет поднять LiteLLM. Дописывают его руками там же, где добавляют
ключ провайдера, и селект подхватывает это сам, без правок здесь.

Каталог лежит в чужом репозитории, а uvicorn работает в контейнере, поэтому путь
приходит переменной `CLAUDE_SHELL_DIR` (монтирование — в `docker-compose.yml`).
Файла нет — отдаём одно умолчание и говорим об этом словами: пустой селект человек
прочтёт как поломку страницы, а не как «каталог не смонтирован».
"""
import os

import yaml

from logging_.logging_ import logger_info

# Куда смонтирован репозиторий оболочки внутри контейнера. Значение по умолчанию —
# для установок, где оболочки нет вовсе (прод): каталог не найдётся, и селект
# останется с одним умолчанием, не роняя страницу.
TEAM_LLM_CATALOG_DIR = os.environ.get('CLAUDE_SHELL_DIR', '/opt/claude-shell')

# Путь внутри репозитория оболочки — её корень. Совпадает с тем, что читает сама
# оболочка (`src/litellm/catalog.py`, `CATALOG_FILE`): разойдись они — селект
# показывал бы одно, а оболочка умела другое, и ошибку человек увидел бы только в
# терминале. Файл лежит в корне, а не рядом с кодом, потому что это данные, которые
# правят руками, — их ищут в корне, а не в недрах пакета.
TEAM_LLM_CATALOG_FILE = os.path.join(TEAM_LLM_CATALOG_DIR, 'llm_models.yaml')

# Что показываем, когда каталога нет. Та же модель, что подставляет сервер в команду
# запуска (`TEAM_COMMAND_LLM_DEFAULT`), — иначе селект предлагал бы одно, а кнопка
# отдавала другое.
TEAM_LLM_CATALOG_FALLBACK = 'gx10/qwen-large'


async def team_llm_catalog_models() -> dict:
    """
    Имена моделей из каталога оболочки и причина, если их взять не удалось.

    Returns: `{'models': [...], 'source': путь, 'problem': ''}`. Ошибку возвращаем
    текстом, а не исключением: страница про состояние команды, и ронять её из-за
    несмонтированного каталога незачем — но и молчать нельзя, иначе человек решит,
    что моделей всего одна.
    """
    path = TEAM_LLM_CATALOG_FILE
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return _fallback(path, f'каталог оболочки не найден: {path}')
    except (yaml.YAMLError, OSError) as e:
        logger_info(f'[team] каталог моделей оболочки не прочитан: {e}')
        return _fallback(path, f'каталог оболочки не разобран: {e}')

    names = [str(item.get('name') or '').strip()
             for item in (data.get('models') or []) if isinstance(item, dict)]
    names = [name for name in names if name]
    if not names:
        return _fallback(path, 'в каталоге оболочки нет ни одной модели')

    return {'models': names, 'source': path, 'problem': ''}


def _fallback(path: str, problem: str) -> dict:
    return {'models': [TEAM_LLM_CATALOG_FALLBACK], 'source': path, 'problem': problem}
