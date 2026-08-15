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
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from logging_.logging_ import logging_init

from src.browser.browser_api import router as browser_api_router
from src.browser.browser_pool import browser_pool_start, browser_pool_stop
from src.browser.browser_record import router as browser_record_router
from src.browser.browser_scenario_run import router as browser_scenario_run_router
from src.browser.browser_snapshot import router as browser_snapshot_router
from src.browser.browser_view import router as browser_view_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_init()

    print('Starting browser container...')
    await browser_pool_start()

    yield

    await browser_pool_stop()
    print('Browser container stopped.')


app = FastAPI(lifespan=lifespan, title='RhapsodyAi Browser')

app.include_router(browser_api_router)
app.include_router(browser_view_router)
app.include_router(browser_scenario_run_router)
app.include_router(browser_snapshot_router)
app.include_router(browser_record_router)
