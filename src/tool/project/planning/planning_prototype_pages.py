"""
Проверки и сохранение страниц прототипа.

Дробится на подмодули по ответственности:
- `planning_prototype_sitemap` — `planning_pages_check`, `planning_sitemap_check`
- `planning_prototype_qa` — `planning_prototype_qa_scan`
- `planning_prototype_render` — `planning_image_save`, `planning_blocks_component_map`

Соседние модули: `planning_prototype_state` — пути и парсинг sitemap, `planning_prototype_scaffold` — каркас страницы.
"""
# Реэкспорты: все функции перенесены в подмодули, импортируем оттуда
from src.tool.project.planning.planning_prototype_sitemap import (
    planning_pages_check,
    planning_sitemap_check,
)
from src.tool.project.planning.planning_prototype_qa import (
    planning_prototype_qa_scan,
)
from src.tool.project.planning.planning_prototype_render import (
    planning_image_save,
    planning_blocks_component_map,
)

__all__ = [
    'planning_pages_check',
    'planning_prototype_qa_scan',
    'planning_image_save',
    'planning_blocks_component_map',
    'planning_sitemap_check',
]
