import http

import logging


def logging_adjust():
    """
    Настраиваем общий формат логов
    """
    # logging.basicConfig(
    #     level=logging.DEBUG,
    #     format='%(asctime)s - %(levelname)s - %(message)s'
    # )


def logging_http_adjust():
    """
    Логируем все http запросы
    """
    # http.client.HTTPConnection.debuglevel = 1

    # logging.getLogger("github").setLevel(logging.DEBUG)
    # logging.getLogger("urllib3").setLevel(logging.DEBUG)
    # logging.getLogger("httpx").setLevel(logging.DEBUG)
