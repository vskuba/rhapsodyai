#!/usr/bin/env python3
"""Точка входа контейнера-браузера.

Отдельный сервис, а не роутер внутри `main_uvicorn`, по одной причине: у них
несовместимые ритмы жизни. :8011 перезапускается на каждой правке `.py`, а здесь
живут страницы, которые должны висеть неделями — открытый чат, ждущий сообщения,
переживать чужой рестарт не может.

Базы здесь нет и не будет: сервис ничего не хранит — ни реестр сессий (он в памяти
процесса), ни сценарии. Сценарий приходит телом запроса, а трасса прогона уходит
ответом; хранит и журналирует их `uvicorn`, у которого пул MySQL уже есть. Так
упавшая база не роняет живые страницы.

Сам контейнер живёт в `py_modules/browser_` — он ничего не знает про этот проект и
подключается любым соседним. Здесь остаётся ровно то, что проектное: имя сервиса,
инициализация журнала и поднятие Chromium на время жизни процесса.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from logging_.logging_ import logging_init

from browser_.browser_pool import browser_pool_start, browser_pool_stop
from browser_.browser_router import router as browser_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_init()

    print('Starting browser container...')
    await browser_pool_start()

    yield

    await browser_pool_stop()
    print('Browser container stopped.')


app = FastAPI(lifespan=lifespan, title='RhapsodyAi Browser')

# Один роутер на весь контейнер: состав ручек — дело общей библиотеки, и новое
# умение, добавленное там, появляется здесь без правки этого файла.
app.include_router(browser_router)
