"""Приметы шагов `testing_facts` — записи факта и поиска по нему."""
import time

AGENT = 'testing_facts'

STEP_MAKE = 'Факт: собрать'
STEP_ADD = 'Факт: записать'
STEP_SYNC = 'Факт: синхронизировать'
STEP_FIND = 'Факт: найти'
STEP_FINAL = 'Финал'

# Коллекция сюиты: своя, чтобы не трогать боевые факты знакомств.
COLLECTION = 'testing_facts'

# Ключ документа — на прогон: факты остаются в базе, и повтор с тем же ключом
# нашёл бы прошлые.
RUN = int(time.time())


def fact_key(name: str) -> str:
    """Ключ документа этого прогона — чтобы прогоны не находили чужое."""
    return f'tf_{RUN}_{name}'
