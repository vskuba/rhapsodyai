import os

import pymysql

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_conn_get

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
_SEEDS_DIR = os.path.join(_BASE_DIR, 'data', 'seeds')


def mysql_seed_up():
    seed_file = _mysql_seed_latest()
    if not seed_file:
        logger_info("Seed: файлы не найдены в data/seeds/, пропускаем")
        return

    if not _mysql_seed_is_fresh_db():
        logger_info("Seed: база данных уже содержит данные, пропускаем")
        return

    logger_info(f"Seed: свежая БД, применяем {os.path.basename(seed_file)}")

    with open(seed_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    conn = mysql_conn_get()
    try:
        with conn.cursor() as cur:
            for stmt in _mysql_seed_split(sql):
                cur.execute(stmt)
        conn.commit()
        logger_info("Seed: успешно применён")
    except Exception as e:
        conn.rollback()
        logger_info(f"Seed: ошибка применения — {e}")
        raise
    finally:
        conn.close()


# ── Private ───────────────────────────────────────────────────────────────────

def _mysql_seed_split(sql: str) -> list[str]:
    """Split SQL by semicolons, ignoring semicolons inside quoted strings."""
    statements = []
    buf = []
    in_quote = None
    i = 0
    while i < len(sql):
        c = sql[i]
        if c == '\\' and in_quote:
            buf.append(c)
            i += 1
            if i < len(sql):
                buf.append(sql[i])
                i += 1
            continue
        if c in ("'", '"'):
            if in_quote == c:
                in_quote = None
            elif in_quote is None:
                in_quote = c
        elif c == ';' and in_quote is None:
            stmt = ''.join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    stmt = ''.join(buf).strip()
    if stmt:
        statements.append(stmt)
    return statements


def _mysql_seed_latest() -> str | None:
    if not os.path.isdir(_SEEDS_DIR):
        return None
    files = sorted(
        (f for f in os.listdir(_SEEDS_DIR) if f.endswith('.sql')),
        reverse=True,
    )
    return os.path.join(_SEEDS_DIR, files[0]) if files else None


def _mysql_seed_is_fresh_db() -> bool:
    conn = mysql_conn_get()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM `node`")
            row = cur.fetchone()
            count = list(row.values())[0] if isinstance(row, dict) else row[0]
        return count == 0
    except pymysql.Error:
        return False
    finally:
        conn.close()
