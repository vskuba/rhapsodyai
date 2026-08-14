import gzip
import io
import os
import subprocess
from datetime import datetime, timezone

from src.tool.datetime_.datetime_ import _utc_now_str

import pymysql
import pymysql.converters
from fastapi import APIRouter, Request, Depends
from fastapi.responses import FileResponse

from mysql_.mysql_ import host, port, user, password, db, mysql_conn_get
from setting_.setting_ import setting_get
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
BACKUPS_DIR = os.path.join(_BASE_DIR, 'data', 'backups')
_EXT = '.sql.gz'


@router.get("/backup/list")
async def backup_list(request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    return {"result": _backup_list()}


@router.post("/backup/create")
async def backup_create(request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    os.makedirs(BACKUPS_DIR, exist_ok=True)

    tz_offset = await setting_get('timezone', '+0')
    ts = _utc_now_str(tz_offset)
    # 'YYYY-MM-DD HH:MM:SSZ' → 'YYYY-MM-DD_HH-MM-SS'
    ts_clean = ts.rstrip('Z').replace(' ', '_').replace(':', '-')
    filename = f"backup_{ts_clean}{_EXT}"
    filepath = os.path.join(BACKUPS_DIR, filename)

    try:
        _backup_via_mysqldump(filepath)
    except FileNotFoundError:
        _backup_via_python(filepath, ts)
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return {"error": str(e)}

    stat = os.stat(filepath)
    return {"result": {"name": filename, "size": stat.st_size}}


@router.get("/backup/download/{filename}")
async def backup_download(filename: str, request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    if not _backup_filename_safe(filename):
        return {"error": "Недопустимое имя файла"}
    filepath = os.path.join(BACKUPS_DIR, filename)
    if not os.path.exists(filepath):
        return {"error": "Файл не найден"}
    return FileResponse(filepath, filename=filename, media_type="application/gzip")


@router.post("/backup/restore/{filename}")
async def backup_restore(filename: str, request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    if not _backup_filename_safe(filename):
        return {"error": "Недопустимое имя файла"}
    filepath = os.path.join(BACKUPS_DIR, filename)
    if not os.path.exists(filepath):
        return {"error": "Файл не найден"}

    env = os.environ.copy()
    env["MYSQL_PWD"] = password

    cmd = [
        "mysql",
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        "--default-character-set=utf8mb4",
        db,
    ]

    try:
        with gzip.open(filepath, 'rb') as gz:
            sql_bytes = gz.read()

        result = subprocess.run(
            cmd,
            input=sql_bytes,
            stderr=subprocess.PIPE,
            env=env,
            timeout=600,
        )
        if result.returncode != 0:
            return {"error": result.stderr.decode('utf-8', errors='replace')}
        return {"result": f"Бэкап {filename} успешно восстановлен"}
    except FileNotFoundError:
        return {"error": "mysql клиент не найден"}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/backup/{filename}")
async def backup_delete(filename: str, request: Request, user_=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    if not _backup_filename_safe(filename):
        return {"error": "Недопустимое имя файла"}
    filepath = os.path.join(BACKUPS_DIR, filename)
    if not os.path.exists(filepath):
        return {"error": "Файл не найден"}
    os.remove(filepath)
    return {"result": "Удалено"}


# ── Private ───────────────────────────────────────────────────────────────────

def _backup_via_mysqldump(filepath: str):
    env = os.environ.copy()
    env["MYSQL_PWD"] = password

    cmd = [
        "mysqldump",
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        "--single-transaction",
        "--routines",
        "--triggers",
        "--default-character-set=utf8mb4",
        db,
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=300)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))

    with gzip.open(filepath, 'wb', compresslevel=6) as gz:
        gz.write(result.stdout)


def _backup_via_python(filepath: str, ts: str = ""):
    conn = mysql_conn_get()
    try:
        buf = io.StringIO()
        buf.write(f"-- Backup (pymysql fallback)\n")
        buf.write(f"-- Generated: {ts}\n")
        buf.write(f"-- Database: {db}\n\n")
        buf.write("SET NAMES utf8mb4;\n")
        buf.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")

        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [list(row.values())[0] for row in cur.fetchall()]

        for table in tables:
            with conn.cursor() as cur:
                cur.execute(f"SHOW CREATE TABLE `{table}`")
                row = cur.fetchone()
                create_sql = list(row.values())[1]

            buf.write(f"-- TABLE: {table}\n")
            buf.write(f"DROP TABLE IF EXISTS `{table}`;\n")
            buf.write(create_sql + ";\n\n")

            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(f"SELECT * FROM `{table}`")
                rows = cur.fetchall()

            if rows:
                cols = list(rows[0].keys())
                col_str = ", ".join(f"`{c}`" for c in cols)
                values_list = [
                    "  (" + ", ".join(_backup_escape_value(row[c]) for c in cols) + ")"
                    for row in rows
                ]
                buf.write(f"INSERT INTO `{table}` ({col_str}) VALUES\n")
                buf.write(",\n".join(values_list) + ";\n\n")

        buf.write("SET FOREIGN_KEY_CHECKS = 1;\n")

        with gzip.open(filepath, 'wb', compresslevel=6) as gz:
            gz.write(buf.getvalue().encode('utf-8'))
    finally:
        conn.close()


def _backup_escape_value(val) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (bytes, bytearray)):
        return f"'{pymysql.converters.escape_string(val.decode('utf-8', errors='replace'))}'"
    return f"'{pymysql.converters.escape_string(str(val))}'"


def _backup_list():
    if not os.path.exists(BACKUPS_DIR):
        return []
    files = []
    for name in sorted(os.listdir(BACKUPS_DIR), reverse=True):
        if not name.endswith(_EXT):
            continue
        stat = os.stat(os.path.join(BACKUPS_DIR, name))
        files.append({
            "name": name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "Z",
        })
    return files


def _backup_filename_safe(filename: str) -> bool:
    return '/' not in filename and '..' not in filename and filename.endswith(_EXT)
