#!/bin/bash
# Сервер задачи на :8013 — код берётся из рабочего каталога подзадачи.
#
# Зачем: QA проверяет ветку на живом сервере, а :8011 в это время занят — на нём
# работает человек и соседние задачи конвейера. Отдельный контейнер поднимает тот
# же образ поверх каталога `.claude/worktrees/feature_task_<id>`.
#
#   ./task_server.sh up 492     — поднять сервер для подзадачи #492
#   ./task_server.sh down       — погасить
#   ./task_server.sh status     — что сейчас запущено и на каком каталоге
#   ./task_server.sh clean 492  — снять рабочий каталог задачи (ветка остаётся)
#
# Сервер один на всю машину: порт 8013 занимает первый поднявший. Повторный `up`
# с другим номером переносит сервер на другой каталог — это осознанное поведение,
# проверяющая роль в каждый момент одна.

set -euo pipefail

# Главный каталог репозитория, а не тот, из которого запустили: скрипт отслеживается
# git-ом и потому лежит в каждом каталоге подзадачи тоже. Запущенный оттуда, он искал
# бы `.claude/worktrees` внутри worktree, где их нет. `--git-common-dir` из любой
# рабочей копии показывает на общий `.git` главного чекаута.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)")"
SERVICE="uvicorn_task"
PORT=8013

cd "$REPO_DIR"

command_run="${1:-status}"

case "$command_run" in
    up)
        subtask_id="${2:-}"
        if [ -z "$subtask_id" ]; then
            echo "[task-server] нужен номер подзадачи: ./task_server.sh up 492" >&2
            exit 1
        fi

        worktree_dir="$REPO_DIR/.claude/worktrees/feature_task_${subtask_id}"
        if [ ! -d "$worktree_dir" ]; then
            echo "[task-server] каталога нет: $worktree_dir" >&2
            echo "[task-server] его заводит конвейер при взятии подзадачи в работу" >&2
            exit 1
        fi

        # Профиль `task` — сервис не поднимается обычным `docker compose up`.
        # Каталог передаём переменной: на неё смотрит монтирование в compose.
        TASK_WORKTREE_DIR="$worktree_dir" docker compose --profile task up -d "$SERVICE"

        echo "[task-server] поднят на http://localhost:${PORT} из $worktree_dir"
        ;;

    down)
        docker compose --profile task stop "$SERVICE" >/dev/null 2>&1 || true
        docker compose --profile task rm -f "$SERVICE" >/dev/null 2>&1 || true
        echo "[task-server] остановлен"
        ;;

    clean)
        subtask_id="${2:-}"
        if [ -z "$subtask_id" ]; then
            echo "[task-server] нужен номер подзадачи: ./task_server.sh clean 492" >&2
            exit 1
        fi

        worktree_dir="$REPO_DIR/.claude/worktrees/feature_task_${subtask_id}"

        # Гасим сервер, только если он поднят именно над этим каталогом: иначе
        # уборка одной задачи погасила бы проверку другой.
        if docker ps --format '{{.Names}}' | grep -qx "$SERVICE"; then
            mount_dir=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}{{end}}{{end}}' "$SERVICE")
            if [ "$mount_dir" = "$worktree_dir" ]; then
                "$0" down
            fi
        fi

        # Несохранённые правки — повод остановиться: работа упавшей задачи или
        # человека пропадать не должна. Проверяем сами, потому что собственная
        # проверка git до дела не доходит — каталог с подмодулем `py_modules` он
        # отказывается снимать без --force в любом случае.
        # Ссылки на общее (`.env`, окружение, рабочие каталоги) правками не считаем:
        # их кладёт сам конвейер, а не человек. Отличаем не по именам — у каждого
        # проекта они свои, — а по тому, что ссылка это симлинк, чего про настоящую
        # работу не скажешь. `-uall` обязателен: иначе папка из одних наших ссылок
        # свернулась бы в одну строку и выглядела бы как чужая работа.
        dirty=""
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            entry="${line:3}"
            if [ "${line:0:3}" = "?? " ] && [ -L "$worktree_dir/${entry%/}" ]; then
                continue
            fi
            dirty="${dirty}${line}"$'\n'
        done < <(git -C "$worktree_dir" status --porcelain -uall)
        dirty="$(printf '%s' "$dirty")"
        if [ -n "$dirty" ]; then
            echo "[task-server] в каталоге есть несохранённые правки — сначала посмотрите:" >&2
            echo "$dirty" >&2
            exit 1
        fi

        # Мусор от контейнера: сервер задачи работает root-ом, и оставленное им
        # хостовый git удалить не может («Permission denied»). Убираем тем же
        # root-ом. Новые каталоги этим не страдают — PYTHONDONTWRITEBYTECODE в
        # compose, — но каталоги, созданные раньше, ещё живы.
        if [ -n "$(find "$worktree_dir" ! -user "$(id -un)" -print -quit)" ]; then
            docker run --rm -v "$worktree_dir":/worktree alpine \
                find /worktree -name __pycache__ -type d -prune -exec rm -rf {} + || true
        fi

        # Ветку не трогаем: merge request живёт дольше каталога.
        git -C "$REPO_DIR" worktree remove --force "$worktree_dir"
        echo "[task-server] каталог снят: $worktree_dir (ветка feature/task_${subtask_id} осталась)"
        ;;

    status)
        # Каталог смотрим у самого контейнера, а не в переменной окружения:
        # запускали его прошлой командой, и в текущей оболочке её уже нет.
        if docker ps --format '{{.Names}}' | grep -qx "$SERVICE"; then
            mount_dir=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}{{end}}{{end}}' "$SERVICE")
            echo "[task-server] работает на :${PORT}, каталог: ${mount_dir}"
        else
            echo "[task-server] не запущен"
        fi
        ;;

    *)
        echo "использование: ./task_server.sh {up <subtask_id>|down|status|clean <subtask_id>}" >&2
        exit 1
        ;;
esac
