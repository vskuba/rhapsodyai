"""
Layout, каркас и сохранение страниц прототипа.

Дробится на подмодули по ответственности:
- `planning_prototype_scaffold` — `planning_prototype_page_layout_load`, `planning_prototype_scaffold_build`, `planning_prototype_blocks_pending`
- `planning_prototype_page_save` — `planning_prototype_component_save`, `planning_prototype_page_assemble`, `planning_prototype_page_save`

Соседние модули: `planning_prototype_state` — пути и хелперы версий.
"""
# Реэкспорты: все функции перенесены в подмодули, импортируем оттуда
from src.tool.project.planning.planning_prototype_scaffold import (
    planning_prototype_page_layout_load,
    planning_prototype_scaffold_build,
    planning_prototype_blocks_pending,
)
from src.tool.project.planning.planning_prototype_page_save import (
    planning_prototype_component_save,
    planning_prototype_page_assemble,
    planning_prototype_page_save,
)

__all__ = [
    'planning_prototype_page_layout_load',
    'planning_prototype_scaffold_build',
    'planning_prototype_blocks_pending',
    'planning_prototype_component_save',
    'planning_prototype_page_assemble',
    'planning_prototype_page_save',
]
