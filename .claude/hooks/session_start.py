#!/usr/bin/env python3
"""
SessionStart hook - при старте новой (не resume/clear/compact) сессии Claude
Code достает из реестра ai_claude_session_registry список сессий для текущего
проекта. Вся механика "оживления" сессии (файл session_uuid, фоновый watch)
инкапсулирована здесь и в session_client.py - не зависит от того, прочитает
ли агент какие-либо инструкции в CLAUDE.md (сознательно нигде не описана
там, см. .claude/docs/claude_session_registry.md).

Если .claude/session_uuid уже есть с прошлого запуска - хук резюмирует
сессию и поднимает watch САМ, без участия LLM вообще (даже без
AskUserQuestion). Агенту сообщается только то, что нужно сделать дальше
(Monitor + обработка inbox) - через additionalContext.

Только для совсем новой сессии (нет session_uuid) нужен агент - показать
пользователю выбор через AskUserQuestion (хук сам вопросы не задаёт).
"""

import json
import os
import sys

from session_client import SESSION_UUID_PATH, activate_session, api_call
from session_tool import load_config


def emit(context_lines: list[str]):
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(context_lines),
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


def main():
    hook_input = json.load(sys.stdin)
    cwd = hook_input.get("cwd") or os.getcwd()
    project_label = os.path.basename(os.path.normpath(cwd))

    secret, base_url = load_config()
    context_lines = [f"[session-registry] project_label: {project_label}"]

    if not secret:
        context_lines.append("(TELEGRAM_TOKEN_RHAPSODY не найден - реестр сессий недоступен)")
        emit(context_lines)
        return

    watch_log = f"/tmp/claude_watch_{project_label}.log"

    if os.path.isfile(SESSION_UUID_PATH):
        with open(SESSION_UUID_PATH, "r", encoding="utf-8") as f:
            session_uuid = f.read().strip()
        try:
            api_call("POST", "/telegram-app/claude/session/resume", secret, base_url,
                      body={"session_uuid": session_uuid})
            activate_session(session_uuid)
            context_lines.append(
                f"Сессия session_uuid={session_uuid} автоматически возобновлена, "
                f"фоновый watch (heartbeat+inbox) уже поднят и пишет в {watch_log}.\n"
                "⚠️ ОБЯЗАТЕЛЬНО ПЕРВЫМ ДЕЙСТВИЕМ В ЭТОМ ЖЕ ОТВЕТЕ (не откладывай, не пропускай): "
                f"заведи Monitor (persistent: true) на {watch_log}, паттерн NEW_MESSAGES. Без этого "
                "шага сообщения из чата Mini App будут приходить в очередь, но никто их не увидит - "
                "watch их находит, но разбудить тебя может только Monitor. По срабатыванию Monitor "
                "вызови `python3 .claude/hooks/session_client.py inbox --session-uuid " + session_uuid +
                "`, обработай непрочитанные как обычные промпты и ответь через `respond --inbox-id "
                "<id>` (--no-notify для промежуточных шагов, без флага - для финального ответа).\n"
                "Сразу после того, как заведёшь Monitor, вызови `python3 .claude/hooks/"
                "session_client.py status --session-uuid " + session_uuid + "` и выведи пользователю "
                "итоговый чек-лист по её результату (watch/server/session_uuid_file) плюс отдельной "
                "строкой Monitor от себя (это единственное, что снаружи не проверить - ты сам знаешь, "
                "что его завёл). Формат чек-листа: 🟢 перед каждым пунктом, который true/armed, 🔴 "
                "перед любым, который false - яркие цветные кружки, не текстовые галочки, чтобы "
                "сразу было видно, всё ли в порядке."
            )
        except Exception as e:
            context_lines.append(
                f"(не удалось резюмировать сохранённую сессию {session_uuid}: {e} - "
                "можно продолжать работу как обычно, реестр сессий недоступен временно)"
            )
        emit(context_lines)
        return

    try:
        result = api_call("GET", "/telegram-app/claude/sessions", secret, base_url,
                           params={"project_label": project_label})
        sessions = result.get("result", [])
    except Exception as e:
        context_lines.append(f"(не удалось получить список зарегистрированных сессий: {e})")
        emit(context_lines)
        return

    if sessions:
        context_lines.append("Найдены ранее зарегистрированные сессии для этого проекта:")
        for s in sessions:
            context_lines.append(
                f"- id={s['id']} role={s['role']} status={s['status']} "
                f"closed_at={s.get('closed_at')} summary={s.get('summary') or '(нет)'} "
                f"session_uuid={s['session_uuid']}"
            )
        context_lines.append(
            "\nИНСТРУКЦИЯ АГЕНТУ: спроси пользователя через AskUserQuestion, какую из этих сессий "
            "продолжить (кратко покажи роль/дату закрытия/summary по каждой), либо создать новую. "
            "При выборе существующей - вызови `python3 .claude/hooks/session_client.py resume "
            "--session-uuid <session_uuid>`. При выборе 'создать новую' - уточни роль (пока только "
            "'developer') и вызови `python3 .claude/hooks/session_client.py register --role <роль> "
            f"--project-label {project_label}`. Обе команды сами сохраняют session_uuid и "
            "поднимают фоновый watch, пишущий в /tmp/claude_watch_" + project_label + ".log.\n"
            "⚠️ ОБЯЗАТЕЛЬНО СРАЗУ ПОСЛЕ ЭТОГО ВЫЗОВА, В ТОМ ЖЕ ОТВЕТЕ: заведи Monitor "
            "(persistent: true) на этот лог-файл, паттерн NEW_MESSAGES - это не отдельная задача "
            "на потом, а обязательная часть того же самого шага регистрации/резюме. Без него "
            "сообщения из чата Mini App будут копиться в очереди незамеченными. По срабатыванию "
            "Monitor обрабатывай inbox так же, как описано для случая автовозобновления. Сразу после "
            "того, как заведёшь Monitor, вызови `python3 .claude/hooks/session_client.py status "
            "--session-uuid <uuid>` и выведи пользователю итоговый чек-лист (watch/server/"
            "session_uuid_file из результата) плюс строкой Monitor от себя. Формат: 🟢 перед каждым "
            "пунктом, который true/armed, 🔴 перед любым, который false - яркие цветные кружки, не "
            "текстовые галочки."
        )
    else:
        context_lines.append(
            "Зарегистрированных сессий для этого проекта нет.\n"
            "ИНСТРУКЦИЯ АГЕНТУ: спроси пользователя через AskUserQuestion, под какой ролью создать "
            "новую сессию (пока только 'developer'), затем вызови "
            "`python3 .claude/hooks/session_client.py register --role <роль> "
            f"--project-label {project_label}` - сама сохранит session_uuid и поднимет watch, "
            f"пишущий в /tmp/claude_watch_{project_label}.log.\n"
            "⚠️ ОБЯЗАТЕЛЬНО СРАЗУ ПОСЛЕ ЭТОГО ВЫЗОВА, В ТОМ ЖЕ ОТВЕТЕ: заведи Monitor "
            "(persistent: true) на этот лог-файл, паттерн NEW_MESSAGES - обязательная часть того же "
            "шага, не отдельная задача на потом. Затем вызови `python3 .claude/hooks/"
            "session_client.py status --session-uuid <uuid>` и выведи пользователю итоговый "
            "чек-лист (watch/server/session_uuid_file) плюс строкой Monitor от себя. Формат: 🟢 "
            "перед каждым пунктом, который true/armed, 🔴 перед любым, который false - яркие "
            "цветные кружки, не текстовые галочки."
        )

    emit(context_lines)


if __name__ == "__main__":
    main()
