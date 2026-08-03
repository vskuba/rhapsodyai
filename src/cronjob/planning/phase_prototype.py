"""
Фаза: Prototype (HTML-прототип на основе дизайн-документа).
Запускается после design-фазы. Генерирует самодостаточный HTML-файл
с навигацией и заглушками всех ключевых экранов.
Результат: ссылка /planning/document/{doc_id}/view
Cronicle (пример): POST /cronjob {"cronjob_path":"src/cronjob/planning/phase_prototype.py","timeout":600}
"""
import asyncio
import json

from src.cronjob.planning.phase_base import project_planning_phase_run

PROTOTYPE_REQUIRES = ['analyze', 'market', 'product', 'tech', 'gtm', 'financial', 'blueprint', 'design']


async def main():
    stats = await project_planning_phase_run(
        agent_name='planning_html_prototyper',
        phase='prototype',
        requires_phases=PROTOTYPE_REQUIRES,
        project_statuses=['pending', 'processing', 'complete'],
    )
    print(json.dumps(stats))


if __name__ == '__main__':
    asyncio.run(main())
