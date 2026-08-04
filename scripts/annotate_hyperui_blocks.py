"""
Аннотирует project_design_ui_block через AI:
- Заменяет текстовый контент на {{var_name}} плейсхолдеры
- Заполняет поле vars (JSON схема переменных с дефолтами)
- Заполняет поле slot (если блок является дочерним элементом)
- Заполняет поле slots (если блок является контейнером с вложениями)

Запуск:
  .venv/bin/python3 scripts/annotate_hyperui_blocks.py [--dry-run] [--limit 10] [--id 42]
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pymysql
import pymysql.cursors

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "py_modules"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from config.config import config_get

SYSTEM_PROMPT = """You are an HTML template annotator. Your task is to analyze a UI block HTML and:

1. Replace all visible text content with [[variable_name]] placeholders
   - Use descriptive snake_case names: [[title]], [[description]], [[cta_text]], [[badge_label]], [[price]], [[author_name]], etc.
   - Replace text in: <h1-h6>, <p>, <span>, <a> text, <button> text, <li> text, <td>/<th>, <label>, <figcaption>, alt="" attributes, placeholder="" attributes
   - Do NOT replace Tailwind class names, icon SVG content, or structural attributes (id, class, href="#", type)
   - Do NOT add placeholders to empty elements

2. Detect if this block is a CONTAINER (has repeated child items — list of cards, grid, news feed, accordion list, etc.)
   - If yes:
     a) Replace ALL repeated child elements with a single [[slot:item]] placeholder in "html"
     b) Take ONE of the repeated child elements, replace its text with [[var_name]] placeholders, and put that annotated HTML into slots[0].template
     c) Put default values for template variables into slots[0].vars (NOT into top-level "vars")
     d) Top-level "vars" should only contain variables of the container itself (headings, descriptions outside the repeated items)
   - CRITICAL: slots[].template MUST always be filled when [[slot:item]] is used. Never leave template null or empty.

3. Detect if this block is a CHILD ITEM (a single card/row/cell that repeats inside a container)
   - If yes: fill "slot" field with the slot name it belongs to (usually "item")

Return ONLY valid JSON (no markdown, no explanation):
{
  "html": "<annotated html with [[slot:item]] for containers>",
  "vars": {"var_name": "Default value for container-level vars only"},
  "slot": "item" or null,
  "slots": [
    {
      "name": "item",
      "multiple": true,
      "min": 1,
      "max": 6,
      "template": "<single child item HTML with [[var_name]] placeholders — REQUIRED>",
      "vars": {"var_name": "Default text for child item vars"}
    }
  ] or null
}

Rules:
- vars values should be realistic placeholder text (not "Lorem ipsum"), e.g. "Latest News", "Learn more", "$29/mo"
- For containers: NEVER use indexed top-level vars like item_1_title, item_2_title — use [[slot:item]] + template instead
- A block can be BOTH a container AND have top-level text vars (e.g. a section heading above the grid)
- Keep all HTML attributes, classes, structure, and SVG icons intact — only replace visible text content
- template must be a single complete child element (one <li>, one <div class="card">, one <details>, etc.)"""


def db_connect() -> pymysql.Connection:
    host = config_get("MYSQL_HOST") or "localhost"
    port = int(config_get("MYSQL_PORT") or 3306)
    # When running outside Docker, use localhost:3302 (mapped port)
    if host == "mysql":
        host = "localhost"
        port = 3302
    return pymysql.connect(
        host=host,
        port=port,
        user=config_get("MYSQL_USER") or "developer",
        password=config_get("MYSQL_PASSWORD") or "password",
        database=config_get("MYSQL_DATABASE") or "project",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


GX10_MODEL = "/home/vskuba/models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
GX10_THINK_RE = re.compile(r'<think>.*?</think>', re.DOTALL)


def _make_gx10_client():
    import openai
    return openai.OpenAI(
        base_url=config_get("GX10_API_URL"),
        api_key=config_get("GX10_API_KEY"),
    )


def _make_openrouter_client():
    import openai
    return openai.OpenAI(
        base_url=config_get("OPENROUTER_API_URL"),
        api_key=config_get("OPENROUTER_API_KEY"),
    )


def _call_ai(client, user_msg: str, max_tokens: int = 8192, model: str = GX10_MODEL) -> dict | None:
    is_gx10 = model == GX10_MODEL
    kwargs = dict(
        model=model,
        max_tokens=32768 if is_gx10 else max_tokens,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    if is_gx10:
        # Отключаем thinking-режим Qwen3 — иначе <think> съедает лимит токенов
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    response = client.chat.completions.create(**kwargs)
    raw = response.choices[0].message.content.strip()
    # На случай если thinking всё равно просочился
    raw = GX10_THINK_RE.sub('', raw).strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw).strip()
    raw = re.sub(r'```\s*$', '', raw).strip()
    decoder = json.JSONDecoder()
    result, _ = decoder.raw_decode(raw)
    return result


def _validate(result: dict) -> str | None:
    """Returns error string if result is invalid, else None."""
    html = result.get("html", "")
    slots = result.get("slots") or []
    if "[[slot:" in html:
        for slot in slots:
            if not slot.get("template"):
                return f"slot '{slot.get('name')}' has no template despite [[slot:]] in html"
        if not slots:
            return "[[slot:]] in html but slots is empty"
    return None


def _warn_indexed_vars(result: dict) -> str | None:
    """Returns warning string if indexed vars detected, but does not block saving."""
    vars_ = result.get("vars") or {}
    indexed = [k for k in vars_ if re.match(r'.+_\d+_.+', k)]
    if indexed:
        return f"indexed vars (fixed columns, saving anyway): {indexed[:3]}"
    return None


def annotate_block(html: str, name: str, max_tokens: int = 8192) -> dict | None:
    """Call AI to annotate a single block. GX10 primary, OpenRouter fallback."""
    gx10 = _make_gx10_client()
    openrouter = _make_openrouter_client()

    # (client, model, label)
    backends = [
        (gx10, GX10_MODEL, "gx10"),
        (openrouter, "anthropic/claude-haiku-4-5", "openrouter"),
    ]

    user_msg = f"Block name: {name}\n\nHTML:\n{html}"
    retry_msg = (
        f"Block name: {name}\n\nHTML:\n{html}\n\n"
        "IMPORTANT: If this is a container with repeated items, "
        "you MUST include 'template' in each slots entry. "
        "Do NOT use indexed vars like item_1_title."
    )

    for client, model, label in backends:
        for attempt in range(2):
            msg = user_msg if attempt == 0 else retry_msg
            try:
                result = _call_ai(client, msg, max_tokens=max_tokens, model=model)
                err = _validate(result)
                if err:
                    if attempt == 0:
                        print(f"\n    ⚠ [{label}] validation failed: {err} — retrying...", end=" ", flush=True)
                        continue
                    else:
                        print(f"\n    ✗ [{label}] validation failed after retry: {err} — trying next backend...", end=" ", flush=True)
                        break  # try next backend
                warn = _warn_indexed_vars(result)
                if warn:
                    print(f"\n    ⚠ {warn}", end=" ", flush=True)
                return result
            except json.JSONDecodeError as e:
                print(f"\n    ✗ [{label}] JSON parse error: {e}")
                if attempt == 0:
                    continue
                print(f"    → trying next backend...", end=" ", flush=True)
                break
            except Exception as e:
                print(f"\n    ✗ [{label}] error: {e} → trying next backend...", end=" ", flush=True)
                break

    return None


def main(dry_run: bool = False, limit: int | None = None, block_id: int | None = None, max_tokens: int = 8192):
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            if block_id:
                cur.execute(
                    "SELECT id, name, html FROM project_design_ui_block WHERE id = %s",
                    (block_id,)
                )
            else:
                # Only process blocks that haven't been annotated yet
                sql = "SELECT id, name, html FROM project_design_ui_block WHERE vars IS NULL AND html IS NOT NULL ORDER BY id ASC"
                if limit:
                    sql += f" LIMIT {limit}"
                cur.execute(sql)
            blocks = cur.fetchall()

        print(f"📋 Blocks to annotate: {len(blocks)}")
        if dry_run:
            print("  [DRY RUN — no DB writes]\n")

        done = 0
        errors = 0

        for block in blocks:
            bid = block["id"]
            name = block["name"]
            html = block["html"] or ""

            print(f"  [{bid}] {name} ...", end=" ", flush=True)

            result = annotate_block(html, name, max_tokens=max_tokens)
            if not result:
                errors += 1
                continue

            annotated_html = result.get("html", html)
            vars_json = json.dumps(result.get("vars") or {}, ensure_ascii=False)
            slot = result.get("slot") or None
            slots_raw = result.get("slots")
            slots_json = json.dumps(slots_raw, ensure_ascii=False) if slots_raw else None

            # Count placeholders found
            placeholders = re.findall(r'\[\[[\w:]+\]\]', annotated_html)
            print(f"{len(placeholders)} vars, slot={slot}, container={'yes' if slots_raw else 'no'}")

            if not dry_run:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE project_design_ui_block SET html=%s, vars=%s, slot=%s, slots=%s WHERE id=%s",
                        (annotated_html, vars_json, slot, slots_json, bid)
                    )
                conn.commit()
                done += 1
            else:
                # Show preview in dry-run
                print(f"    vars: {vars_json[:120]}...")
                if slot:
                    print(f"    slot: {slot}")
                if slots_json:
                    print(f"    slots: {slots_json[:120]}...")

        print(f"\n✅ Done: {done} annotated, {errors} errors")

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Не писать в БД")
    parser.add_argument("--limit", type=int, default=None, help="Обработать только N блоков")
    parser.add_argument("--id", type=int, default=None, help="Обработать один блок по ID")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Лимит токенов ответа AI (default: 8192)")
    args = parser.parse_args()
    main(dry_run=args.dry_run, limit=args.limit, block_id=args.id, max_tokens=args.max_tokens)
