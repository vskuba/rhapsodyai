#!/bin/sh
#
# Поставить git-хуки проекта.
#
# Копией, а не `core.hooksPath`. Причина в выкладках: `core.hooksPath` с
# относительным путём каждая выкладка разрешает от своего корня, и каталог с хуками
# должен быть выкачен в ней — а ветка, отрезанная до появления хуков, их не увидит.
# Каталог `.git/hooks` у выкладок общий с основным чекаутом (`git rev-parse
# --git-path hooks` отдаёт один и тот же путь), поэтому копия туда покрывает разом
# все выкладки, какой бы коммит в них ни был выкачен.
#
# Запускать после клона и после правки хуков: `.git/hooks` не версионируется, и без
# этого шага защита пропала бы молча.

set -e

root=$(git rev-parse --show-toplevel)
hooks=$(git rev-parse --git-common-dir)/hooks
source_dir="$root/scripts/git_hooks"

mkdir -p "$hooks"

for name in commit-msg; do
    cp "$source_dir/$name" "$hooks/$name"
    chmod +x "$hooks/$name"
    echo "поставлен: $hooks/$name"
done
