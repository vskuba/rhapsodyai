#!/usr/bin/env bash
# Срок хранения журналов в OpenSearch — 14 дней (политика ISM `app-logs-retention`).
#
# ЗАЧЕМ. Logstash пишет индекс на каждый день (`app-logs-%{+YYYY.MM.dd}`,
# docker/logstash/read-app-logs_prod.conf), а удалять их было некому: к 07.11.2026
# том `rhapsodyai_opensearch-data` дорос до 44 ГБ при диске, занятом на 91%.
#
# ЧТО. Политика живёт в самом кластере (переживает перезапуски), а
# `ism_template` вешает её на каждый новый `app-logs-*` сам. Уже существующим
# индексам шаблон не применяется — им политику навешивает `_ism/add`.
#
# ⚠ Идемпотентно: повторный запуск переписывает политику и навешивает её только
# тем индексам, у которых её нет. ⚠ OpenSearch не поднимает: погашен — выходим
# молча, политика встанет при первом запуске после включения.
set -u
OS=${OS_URL:-http://localhost:9200}
HERE=$(cd "$(dirname "$0")" && pwd)
NAME=app-logs-retention

if ! docker ps --format '{{.Names}}' | grep -qx opensearch; then
    echo "OpenSearch погашен — политику хранения поставим, когда его включат"
    exit 0
fi

run() { docker exec -i opensearch curl -s "$@"; }

# Переписать политику: при существующей нужна пара seq_no/primary_term.
cur=$(run "$OS/_plugins/_ism/policies/$NAME")
seq=$(echo "$cur" | grep -o '"_seq_no":[0-9]*' | cut -d: -f2)
term=$(echo "$cur" | grep -o '"_primary_term":[0-9]*' | cut -d: -f2)
q=""
[ -n "$seq" ] && q="?if_seq_no=$seq&if_primary_term=$term"
run -XPUT "$OS/_plugins/_ism/policies/$NAME$q" -H 'Content-Type: application/json' \
    --data-binary @- < "$HERE/ism_app_logs.json"; echo

# Существующим индексам без политики — навесить. ⚠ Индекс, у которого политика
# уже есть, ISM числит в `failures` («already has a policy») — на повторном
# запуске это норма, а не отказ, и печатается словами.
got=$(run -XPOST "$OS/_plugins/_ism/add/app-logs-*" -H 'Content-Type: application/json' \
    -d "{\"policy_id\": \"$NAME\"}")
other=$(echo "$got" | grep -o '"reason":"[^"]*"' | grep -v 'already has a policy' || true)
if [ -n "$other" ]; then
    echo "$got"
else
    echo "Политика навешена: $(echo "$got" | grep -o '"updated_indices":[0-9]*'), прочие индексы уже под ней"
fi
