#!/bin/bash
# Blue-Green zero-downtime deployment for uvicorn service.
# Alternates between 'blue' (uvicorn:8011) and 'green' (uvicorn_green:8012).
# Caddy is switched atomically via sed + caddy reload (graceful, no dropped connections).
#
# Source of truth for active slot: Caddyfile (what Caddy actually serves).
# .deploy_slot is a convenience cache; Caddyfile always wins.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$REPO_DIR/.deploy_slot"
CADDYFILE="$REPO_DIR/docker/caddy/Caddyfile"
HEALTH_TIMEOUT=90   # seconds to wait for new slot to become healthy
HEALTH_INTERVAL=5   # polling interval in seconds

# --- Determine active slot ---
# .deploy_slot is the primary source of truth — it survives git reset --hard
# (untracked + gitignored). Caddyfile is used only on first-ever run when
# .deploy_slot doesn't exist yet.
if [ -f "$STATE_FILE" ]; then
    ACTIVE_SLOT=$(cat "$STATE_FILE")
    echo "[BG] State из .deploy_slot: $ACTIVE_SLOT"
else
    CADDY_BACKEND=$(grep -oP 'reverse_proxy \K[a-zA-Z_]+:[0-9]+' "$CADDYFILE" 2>/dev/null | head -1 || echo "")
    if [ "$CADDY_BACKEND" = "uvicorn_green:8000" ]; then
        ACTIVE_SLOT="green"
    else
        ACTIVE_SLOT="blue"
    fi
    echo "[BG] .deploy_slot не найден, определяем по Caddyfile: $ACTIVE_SLOT (backend: $CADDY_BACKEND)"
fi

if [ "$ACTIVE_SLOT" = "blue" ]; then
    NEW_SLOT="green"
    NEW_SERVICE="uvicorn_green"
    NEW_PORT="8012"
    NEW_BACKEND="uvicorn_green:8000"
    OLD_SERVICE="uvicorn"
else
    NEW_SLOT="blue"
    NEW_SERVICE="uvicorn"
    NEW_PORT="8011"
    NEW_BACKEND="uvicorn:8000"
    OLD_SERVICE="uvicorn_green"
fi

echo "[BG] Caddy backend: $CADDY_BACKEND | Активный: $ACTIVE_SLOT -> Новый: $NEW_SLOT ($NEW_SERVICE:$NEW_PORT)"

# --- Build and start new slot ---
echo "[BG] Сборка и запуск $NEW_SERVICE..."
if [ "$NEW_SLOT" = "green" ]; then
    docker compose --profile green up -d --build --force-recreate --no-deps "$NEW_SERVICE"
else
    docker compose up -d --build --force-recreate --no-deps "$NEW_SERVICE"
fi

# --- Health check (from host via mapped port) ---
echo "[BG] Ожидание готовности $NEW_SERVICE (максимум ${HEALTH_TIMEOUT}с)..."
ELAPSED=0
HEALTHY=false

while [ "$ELAPSED" -lt "$HEALTH_TIMEOUT" ]; do
    sleep "$HEALTH_INTERVAL"
    ELAPSED=$((ELAPSED + HEALTH_INTERVAL))

    # curl exits non-zero when app isn't ready yet (e.g. 56 = connection reset by
    # docker-proxy before uvicorn binds the port). The || prevents set -e from
    # killing the script; we rely on the HTTP code check below instead.
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://127.0.0.1:$NEW_PORT/" 2>/dev/null) || HTTP_CODE="000"
    # Accept any 2xx/3xx/4xx — the app is up even if auth returns 401/403
    if [[ "$HTTP_CODE" =~ ^[2-4][0-9][0-9]$ ]]; then
        echo "[BG] Готов (HTTP $HTTP_CODE) за ${ELAPSED}с"
        HEALTHY=true
        break
    fi

    echo "[BG] Ожидание... ${ELAPSED}с (HTTP $HTTP_CODE)"
done

if [ "$HEALTHY" != "true" ]; then
    echo "[ERROR] $NEW_SERVICE не ответил за ${HEALTH_TIMEOUT}с. Откат."
    docker stop "$NEW_SERVICE" 2>/dev/null || true
    docker rm "$NEW_SERVICE" 2>/dev/null || true
    exit 1
fi

# --- Switch Caddy ---
# Matches: reverse_proxy uvicorn:8000 {
#      or: reverse_proxy uvicorn_green:8000 {
echo "[BG] Переключение Caddy -> $NEW_BACKEND"
sed -i "s|reverse_proxy [a-zA-Z_]*:[0-9]* {|reverse_proxy $NEW_BACKEND {|" "$CADDYFILE"

# caddy reload returns 0 even when it silently rejects the new config (e.g. when
# the new upstream isn't DNS-resolvable yet at reload time). A full restart is
# reliable: Caddy reads the Caddyfile fresh and starts with the correct upstream.
# Downtime window: ~2-3 seconds while Caddy restarts (TLS sessions resume quickly).
docker restart caddy
echo "[BG] Caddy перезапущен с backend $NEW_BACKEND"

# --- Persist new active slot ---
echo "$NEW_SLOT" > "$STATE_FILE"

# --- Stop and remove old slot (traffic already on new slot) ---
echo "[BG] Остановка $OLD_SERVICE..."
docker stop "$OLD_SERVICE" 2>/dev/null || true
docker rm "$OLD_SERVICE" 2>/dev/null || true

echo "[BG] Деплой завершён! Активный слот: $NEW_SLOT"
