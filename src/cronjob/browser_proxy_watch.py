"""Сторож выходных адресов: проверяет прокси по расписанию и докладывает о беде.

## Зачем

Прокси умирают молча. Канал кончился, провайдер сменил пароль, подсеть уехала в
чужие руки — и никакой ошибки при этом не происходит: она случится потом, когда
анкета не сможет войти на сайт. Кнопку «Проверить все» на вкладке «Proxy» жмут
руками и редко, то есть ровно тогда, когда беда уже случилась.

Сторож переворачивает это: проверка идёт по расписанию, а человек узнаёт о
поломке до того, как заметит её по молчащим анкетам.

## Что делает

1. Гонит проверку по всем включённым выходам (`browser_proxy_net_check_all`) —
   тем же кодом, что и кнопка: второй копии здесь быть не должно.
2. Сравнивает с тем, что было **до** прогона, и докладывает **только о переменах**:
   кто сломался, кто починился, у кого сменился внешний адрес.
3. Если ничего не изменилось — молчит. Ежечасное «всё хорошо» перестают читать
   через день, и вместе с ним перестают читать то единственное сообщение, ради
   которого сторож и заведён.

## ⚠ Чего он намеренно не делает

**Не снимает анкеты с умершего выхода.** Соблазн велик — прокси мёртв, работать
через него нельзя, — но цена ошибки высокая: сайт помнит, с какого адреса
входила учётка, и переезд живой анкеты на другой IP выглядит для него хуже, чем
её молчание. Смена адреса — решение человека, и он принимает его, увидев доклад.

Мёртвый выход при этом **сам собой выпадает из раздачи**: `check_ok = 0` означает
«куда его считать, неизвестно», и новых анкет на него не посадят
(`browser_proxy_net.py`).

**Не считает подряд идущие отказы.** Один отказ уже повод сказать; хранить
счётчик — значит завести колонку, которая нужна только чтобы промолчать в первый
раз.

## Запуск

Через Cronicle, как уборка логов:

    POST /cronjob {"cronjob_path": "src/cronjob/browser_proxy_watch.py",
                   "metadata": {}, "timeout": 300}

Разумный срок — раз в 15–30 минут: чаще значит стучаться к провайдеру без повода,
реже — узнавать о смерти канала позже, чем о ней узнают анкеты.

Прогон вручную без сообщения в Telegram — `"metadata": {"notify": false}`.
"""

import asyncio
import json
import sys

from logging_.logging_ import logger_info, logging_init
from src.error.error_log_handler import error_log_handler_install
from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

from src.telegram_.telegram_notify import telegram_notify_send_owner
from src.uvicorn.routers.browser.browser_proxy_net import browser_proxy_net_check_all

# Сколько строк доклада показываем по каждому роду перемен. Доклад читают с
# телефона: двадцать имён в одном сообщении не читает никто, а первые пять
# отвечают на вопрос «что случилось».
BROWSER_PROXY_WATCH_REPORT_MAX = 5


async def main():
    logging_init()
    # Ошибки кронджоба — в общий журнал установки (вкладка «Журнал» на
    # странице трасс): он живёт минуту в отдельном процессе, и его отказ
    # иначе теряется вместе с этим процессом.
    error_log_handler_install('cronjob')

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            metadata = {}

    was = await _snapshot()
    checked = await browser_proxy_net_check_all()
    changes = _changes(was, checked)

    report = _report(checked, changes)
    logger_info(f'[proxy] сторож: {report}')

    # Молчим, когда нечего сказать: ежечасное «всё хорошо» перестают читать, а с
    # ним перестают читать и то сообщение, ради которого сторож заведён.
    if changes and metadata.get('notify', True):
        try:
            await telegram_notify_send_owner(_message(checked, changes))
        except Exception as e:
            # Проверка уже состоялась, и молчащий Telegram её не отменяет: пишем
            # в лог и выходим успешно, иначе Cronicle отметит job провалившимся
            # из-за того, что не относится к его работе.
            logger_info(f'[proxy] сторож: доклад в Telegram не ушёл — {type(e).__name__}: {e}')

    await mysql_pool_close()

    print(report)
    print(json.dumps({'checked': len(checked), 'changes': changes}, ensure_ascii=False))


# ── Приватное ────────────────────────────────────────────────────────────────

async def _snapshot() -> dict:
    """Каким был каждый выход **до** проверки: `{id: (проверяли, годен, адрес)}`.

    Снимаем заранее, потому что проверка перезаписывает строку: сравнить «было» и
    «стало» после неё уже нечем.

    ⚠ **Первое поле — «проверяли ли вообще», и без него доклад врёт.** У свежей
    строки `check_ok = 0`, как и у сломанной, и удачная первая проверка
    читалась бы как «починился» — про выход, который минуту назад завели руками.
    Поймано на живом прогоне: сторож доложил о починке того, что не ломалось.
    Различает их `checked_at`: NULL значит «не проверяли ни разу».
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, check_ok, check_ip, checked_at FROM browser_proxy '
                         ' WHERE is_enabled = 1')
        rows = await db.fetchall() or []

    return {int(row['id']): (row['checked_at'] is not None, bool(row['check_ok']),
                             str(row['check_ip'] or '')) for row in rows}


def _changes(was: dict, checked: list[dict]) -> dict:
    """Что изменилось: сломались, починились, сменили адрес.

    ⚠ **Смена адреса — тоже перемена, и о ней надо знать.** Прокси жив, проверка
    зелёная, а выходит он теперь из другой подсети: у резидентных каналов это
    обычное дело. Для сайта это переезд учётки на новый IP — то самое, что он
    считает подозрительным, — и человек должен узнать об этом не от сайта.

    ⚠ **Строка, которую ещё ни разу не проверяли, переменой не считается** — ни
    удачей, ни отказом. Её только что завели руками, и докладывать человеку о
    том, что он сам сделал минуту назад, незачем. Прежде сторож называл такую
    «починившейся»: у свежей строки `check_ok = 0`, как и у сломанной.
    """
    broke, fixed, moved = [], [], []

    for row in checked:
        proxy_id = int(row.get('id') or 0)
        if proxy_id not in was:
            continue

        seen_was, ok_was, ip_was = was[proxy_id]
        if not seen_was:
            # Первая проверка в жизни строки: сравнивать не с чем.
            continue

        ok_now, ip_now = bool(row.get('ok')), str(row.get('ip') or '')
        name = str(row.get('name') or f'#{proxy_id}')

        if ok_was and not ok_now:
            broke.append(f'{name}: {row.get("error") or "отказал"}')
        elif not ok_was and ok_now:
            fixed.append(f'{name}: снова отвечает, адрес {ip_now}')
        elif ok_now and ip_was and ip_now != ip_was:
            moved.append(f'{name}: адрес сменился, {ip_was} → {ip_now}')

    return {key: value for key, value in
            (('broke', broke), ('fixed', fixed), ('moved', moved)) if value}


def _report(checked: list[dict], changes: dict) -> str:
    """Строка для журнала: коротко и с числами."""
    ok = sum(1 for row in checked if row.get('ok'))
    tail = ', '.join(f'{_WORD[key]} {len(value)}' for key, value in changes.items())

    return (f'проверено {len(checked)}, годных {ok}'
            + (f'; {tail}' if tail else '; без перемен'))


def _message(checked: list[dict], changes: dict) -> str:
    """Доклад владельцу. Перемены построчно, лишнее отрезано."""
    ok = sum(1 for row in checked if row.get('ok'))
    lines = [f'🌐 Выходы: проверено {len(checked)}, годных {ok}']

    for key in ('broke', 'moved', 'fixed'):
        rows = changes.get(key) or []
        if not rows:
            continue

        lines.append(f'\n{_MARK[key]} {_WORD[key].capitalize()}:')
        lines.extend(f'  • {one}' for one in rows[:BROWSER_PROXY_WATCH_REPORT_MAX])
        if len(rows) > BROWSER_PROXY_WATCH_REPORT_MAX:
            lines.append(f'  … и ещё {len(rows) - BROWSER_PROXY_WATCH_REPORT_MAX}')

    if changes.get('broke'):
        # Говорим, что делать, а не только что случилось: анкеты с мёртвого
        # выхода **не сняты** намеренно (см. шапку), и решение за человеком.
        lines.append('\nАнкеты с этих выходов не сняты: смена IP у живой учётки '
                     'заметнее паузы. Решение — на вкладке «Proxy».')

    return '\n'.join(lines)


_WORD = {'broke': 'сломались', 'fixed': 'починились', 'moved': 'сменили адрес'}
_MARK = {'broke': '🔴', 'fixed': '🟢', 'moved': '🔀'}


if __name__ == '__main__':
    asyncio.run(main())
