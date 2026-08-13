import json
import os
from datetime import datetime, timezone

from src.tool.datetime_.datetime_ import _utc_now_str

import pymysql
import pymysql.converters
from fastapi import APIRouter, Request, Depends
from fastapi.responses import FileResponse

from mysql_.mysql_ import mysql_conn_get
from setting_.setting_ import setting_get, setting_set
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
SEEDS_DIR = os.path.join(_BASE_DIR, 'data', 'seeds')


@router.get("/seed/tables")
async def seed_tables_list(request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    saved = await setting_get('seed_table_config')
    try:
        selected = json.loads(saved) if saved else []
    except Exception:
        selected = []
    groups = _seed_table_groups()
    return {"result": groups, "defaults": selected}


@router.post("/seed/config")
async def seed_config_save(request: Request, data: dict, user_=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    await setting_set('seed_table_config', json.dumps(data.get("tables", [])))
    return {"result": "ok"}


@router.get("/seed/files")
async def seed_files_list(request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    return {"result": _seed_files()}


@router.post("/seed/generate")
async def seed_generate(request: Request, data: dict, user_=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    selected = list(data.get("tables", []))

    os.makedirs(SEEDS_DIR, exist_ok=True)

    tz_offset = await setting_get('timezone', '+0')
    ts = _utc_now_str(tz_offset)
    # 'YYYY-MM-DD HH:MM:SSZ' → 'YYYY-MM-DD_HH-MM-SS'
    ts_clean = ts.rstrip('Z').replace(' ', '_').replace(':', '-')
    filename = f"seed_{ts_clean}.sql"
    filepath = os.path.join(SEEDS_DIR, filename)

    conn = mysql_conn_get()
    try:
        header = (
            f"-- Seed SQL\n"
            f"-- Generated: {_utc_now_str(tz_offset)}\n"
            f"-- Tables: {', '.join(sorted(selected))}\n\n"
            f"SET NAMES utf8mb4;\n"
            f"SET FOREIGN_KEY_CHECKS = 0;\n"
        )

        sections = [header]
        for tbl in sorted(selected):
            sections.append(_seed_table_to_sql(conn, tbl))

        sections.append("\nSET FOREIGN_KEY_CHECKS = 1;\n")
        sql_content = "\n".join(sections)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(sql_content)

        stat = os.stat(filepath)
        return {"result": {
            "name": filename,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "Z",
        }}
    finally:
        conn.close()


@router.post("/seed/apply/{filename}")
async def seed_apply(filename: str, request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    if not _seed_filename_safe(filename):
        return {"error": "Недопустимое имя файла"}
    filepath = os.path.join(SEEDS_DIR, filename)
    if not os.path.exists(filepath):
        return {"error": "Файл не найден"}

    with open(filepath, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    conn = mysql_conn_get()
    try:
        with conn.cursor() as cur:
            for stmt in _seed_split_sql(sql_content):
                cur.execute(stmt)
        conn.commit()
        return {"result": f"Seed {filename} успешно применён"}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}
    finally:
        conn.close()


@router.get("/seed/download/{filename}")
async def seed_download(filename: str, request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    if not _seed_filename_safe(filename):
        return {"error": "Недопустимое имя файла"}
    filepath = os.path.join(SEEDS_DIR, filename)
    if not os.path.exists(filepath):
        return {"error": "Файл не найден"}
    return FileResponse(filepath, filename=filename, media_type="application/sql")


@router.delete("/seed/{filename}")
async def seed_delete(filename: str, request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    if not _seed_filename_safe(filename):
        return {"error": "Недопустимое имя файла"}
    filepath = os.path.join(SEEDS_DIR, filename)
    if not os.path.exists(filepath):
        return {"error": "Файл не найден"}
    os.remove(filepath)
    return {"result": "Удалено"}


# ── Private ───────────────────────────────────────────────────────────────────

def _seed_table_groups() -> list:
    conn = mysql_conn_get()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
                "ORDER BY TABLE_NAME"
            )
            all_tables = [row['TABLE_NAME'] for row in cur.fetchall()]
    finally:
        conn.close()

    # group by first segment before underscore
    buckets: dict[str, list] = {}
    for tbl in all_tables:
        prefix = tbl.split('_')[0]
        buckets.setdefault(prefix, []).append(tbl)

    return [
        {"key": prefix, "label": prefix, "tables": tables}
        for prefix, tables in sorted(buckets.items())
    ]


def _seed_files() -> list:
    if not os.path.exists(SEEDS_DIR):
        return []
    files = []
    for name in sorted(os.listdir(SEEDS_DIR), reverse=True):
        if not name.endswith('.sql'):
            continue
        stat = os.stat(os.path.join(SEEDS_DIR, name))
        files.append({
            "name": name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "Z",
        })
    return files


def _seed_table_to_sql(conn: pymysql.Connection, table_name: str) -> str:
    lines = [f"\n-- TABLE: {table_name}"]
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(f"SELECT * FROM `{table_name}`")
        rows = cur.fetchall()

    if not rows:
        lines.append("-- (empty)")
        return "\n".join(lines)

    cols = list(rows[0].keys())
    col_str = ", ".join(f"`{c}`" for c in cols)
    values_list = [
        "  (" + ", ".join(_seed_escape_value(row[c]) for c in cols) + ")"
        for row in rows
    ]

    lines.append(f"INSERT IGNORE INTO `{table_name}` ({col_str}) VALUES")
    lines.append(",\n".join(values_list) + ";")
    return "\n".join(lines)


def _seed_escape_value(val) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (bytes, bytearray)):
        return f"'{pymysql.converters.escape_string(val.decode('utf-8', errors='replace'))}'"
    return f"'{pymysql.converters.escape_string(str(val))}'"


def _seed_filename_safe(filename: str) -> bool:
    return '/' not in filename and '..' not in filename and filename.endswith('.sql')


def _seed_split_sql(sql: str) -> list[str]:
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
