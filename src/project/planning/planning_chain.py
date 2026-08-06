"""
Цепочка фаз планирования — единственный источник правды.

Раньше зависимости фаз были описаны в трёх местах (`phase_all.py`, `planning_runner.py`
и десять отдельных `phase_*.py`) и расходились: `phase_all` держал `gtm` до завершения
`tech`, хотя они задуманы параллельными. Теперь описание одно, а потребителей два —
`planning_runner` (событийный, внутри uvicorn) и `planning_batch` (пакетный, из Cronicle).
"""

# Волны: фазы внутри волны идут параллельно, следующая волна ждёт завершения текущей.
# requires — какие фазы должны быть complete, чтобы фазу можно было брать в работу.
PLANNING_CHAIN: list[list[tuple[str, str, list[str]]]] = [
    [('analyze',   'planning_analyzer',           [])],
    [('market',    'planning_market_researcher',  ['analyze'])],
    [('product',   'planning_product_planner',    ['market', 'analyze'])],
    [                                              # tech и gtm не зависят друг от друга
        ('tech',   'planning_tech_architect',     ['product']),
        ('gtm',    'planning_gtm_strategist',     ['market', 'product']),
    ],
    [('financial', 'planning_financial_modeler',  ['tech', 'gtm', 'market', 'product'])],
    [('blueprint', 'planning_blueprint_composer',
      ['analyze', 'market', 'product', 'tech', 'gtm', 'financial'])],
]

# Запускаются после blueprint.
PLANNING_SCORE_AGENT = 'planning_scorer'
PLANNING_SCORE_REQUIRES = ['blueprint']

PLANNING_SUPPLEMENT_AGENT = 'planning_supplement_writer'
PLANNING_SUPPLEMENT_REQUIRES = ['analyze', 'market', 'product', 'tech', 'gtm', 'financial', 'blueprint']
PLANNING_SUPPLEMENT_TYPES = ['market', 'product', 'tech', 'gtm', 'financial', 'launch']


def planning_chain_flat() -> list[tuple[str, str, list[str]]]:
    """Все фазы цепочки одним списком, в порядке выполнения (волны разворачиваются)."""
    return [item for wave in PLANNING_CHAIN for item in wave]


def planning_chain_phase_get(phase: str) -> tuple[str, str, list[str]] | None:
    """Описание фазы `(phase, agent_name, requires)` либо None, если такой фазы нет."""
    for item in planning_chain_flat():
        if item[0] == phase:
            return item
    return None
