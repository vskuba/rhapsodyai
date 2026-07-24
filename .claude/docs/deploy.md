# Blue-Green Deployment

Zero-downtime деплой для `uvicorn` сервиса. Во время обновления трафик переключается между двумя слотами; Caddy перезагружает конфиг без обрыва соединений.

## Архитектура

```
Internet → Caddy (:80/:443) → uvicorn:8000  (blue,  host port 8011)
                             или
                           → uvicorn_green:8000  (green, host port 8012)
```

Два Docker-сервиса поочерёдно становятся активными:

| Слот  | Сервис          | Внутренний порт  | Порт на хосте |
|-------|-----------------|------------------|---------------|
| Blue  | `uvicorn`       | `uvicorn:8000`   | `8011`        |
| Green | `uvicorn_green` | `uvicorn_green:8000` | `8012`    |

Текущий активный слот хранится в файле `.deploy_slot` в корне репозитория на сервере.

## Файлы

| Файл | Назначение |
|------|-----------|
| `bluegreen.sh` | Скрипт переключения (вызывается из deploy.yml) |
| `.deploy_slot` | Текущий активный слот (`blue` / `green`); создаётся на сервере |
| `docker-compose.yml` | `uvicorn_green` определён с `profiles: ["green"]` |
| `docker/caddy/Caddyfile` | Строка `reverse_proxy <backend>:8000 {` меняется скриптом через `sed` |
| `.github/workflows/deploy.yml` | CI/CD — вызывает `bluegreen.sh` |

## Процесс деплоя (bluegreen.sh)

```
1. Читает Caddyfile → определяет старый (blue) и новый (green) слот
   - Source of truth: grep reverse_proxy из docker/caddy/Caddyfile
   - Fallback: .deploy_slot файл
2. docker compose up -d --build --force-recreate --no-deps <new_service>
3. Polling http://127.0.0.1:<new_port>/ каждые 5с, до 90с
   - 2xx/3xx/4xx = готов; 000 = ждём (000 = нормально пока uvicorn стартует)
   - curl exit code 56 (connection reset) обрабатывается через || HTTP_CODE="000"
4. sed -i: меняет backend в Caddyfile (uvicorn:8000 → uvicorn_green:8000 или обратно)
5. docker exec caddy caddy reload  ← graceful, без dropped connections
6. echo <new_slot> > .deploy_slot
7. docker stop <old_service> && docker rm <old_service>
```

Если новый слот не поднялся за 90 секунд — контейнер удаляется, деплой завершается с ошибкой. Старый слот продолжает работать.

### Почему Caddyfile — source of truth

`git reset --hard origin/master` в deploy.yml восстанавливает Caddyfile из git (исходное `uvicorn:8000`), но **не перезагружает Caddy** — Caddy продолжает работать по runtime-конфигу. Поэтому state определяется из ФАЙЛА (что есть в git/на диске), а не из runtime Caddy. Это корректно: `sed` меняет файл → `caddy reload` синхронизирует runtime с файлом.

`.deploy_slot` защищён от `git clean -fd` через `.gitignore`.

## Первый запуск на свежем сервере

При отсутствии `.deploy_slot` скрипт считает активным `blue` и деплоит в `green`. Если `uvicorn` не запущен — `docker stop uvicorn || true` завершается без ошибки.

## Ручной запуск

```bash
cd ~/rhapsodyai
chmod +x bluegreen.sh
./bluegreen.sh
```

## Healthcheck endpoint

Скрипт проверяет `GET /` и считает приложение готовым при HTTP-коде 2xx/3xx/4xx.
Для надёжности рекомендуется добавить выделенный эндпоинт:

```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

И поменять в `bluegreen.sh` строку:
```bash
HTTP_CODE=$(curl ... "http://127.0.0.1:$NEW_PORT/health" ...)
```

## Сервисы, НЕ затрагиваемые Blue-Green

- `telegram` — перезапускается через `--force-recreate` (обновление образа из GHCR)
- `worker` — перезапускается с новым образом (downtime допустим, обрабатывает Redis-очередь)
- `caddy`, `redis`, `qdrant`, `mysql` — только `up -d` (запускаются если упали)

## Откат

Перезапустить вручную предыдущий слот:

```bash
cd ~/rhapsodyai
# Если активен green, вернуть blue вручную:
docker compose up -d --build uvicorn
sed -i "s|reverse_proxy [a-zA-Z_]*:[0-9]* {|reverse_proxy uvicorn:8000 {|" docker/caddy/Caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
docker stop uvicorn_green && docker rm uvicorn_green
echo "blue" > .deploy_slot
```
