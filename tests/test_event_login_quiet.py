"""Вход в панель не будит владельца бота, но остаётся в журнале.

## ⚠⚠ Что здесь стережётся

Событие `user.login` имело двух подписчиков: запись в журнал и уведомление в
Telegram. Второй отключён — вход в панель не то событие, ради которого шлют
сообщение человеку.

Отсев по роли там был (`admin` — сам владелец бота, `qa` логинится на каждом
тесте, десятки раз за прогон), и он оставлял входы обычных пользователей. Их и
оказалось достаточно, чтобы уведомления шумели.

⚠ **Журнал при этом остался.** Отключено уведомление, а не запись события: кто и
когда входил, по-прежнему видно.

## ⚠ Почему проверка на подписках, а не на «пришло ли сообщение»

Сообщение не приходит по двум разным причинам: подписки нет — и подписка есть, но
отсев по роли её погасил. Второе зависит от того, под кем идёт тест, и такая
проверка зеленела бы при вернувшейся подписке. Спрашиваем то, что решает: кто
подписан.
"""

import ast
import inspect
import textwrap

import pytest

from src.event import event_handlers

pytestmark = pytest.mark.core


def _subscribed() -> set:
    """Кто вправду подписан на `user.login` — разбором вызовов, а не текстом.

    ⚠ Имя обработчика встречается в файле и вне подписки: в комментарии, который
    объясняет отключение. Поиск подстрокой находил его и краснел при верном коде.
    """
    tree = ast.parse(
        textwrap.dedent(inspect.getsource(event_handlers.event_handlers_register)))

    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, 'id', '') != 'event_subscribe':
            continue
        for arg in node.args[1:]:
            if isinstance(arg, ast.Name):
                names.add(arg.id)

    return names


class TestTheLoginIsQuiet:
    """⚠ Уведомление о входе не подписано ни на что."""

    def test_telegram_is_not_subscribed_to_login(self):
        """⚠⚠ Главная проверка: подписки нет.

        Вернут строку `event_subscribe('user.login', _telegram_notify_login)` —
        тест покраснеет, и это правильно: отключение должно отменяться намеренно,
        а не заодно с чужой правкой.

        ⚠ Смотрим на **вызовы**, а не на текст: имя обработчика стоит рядом в
        комментарии, объясняющем отключение, и поиск подстрокой ловил его.
        Первая версия теста упала ровно на этом.
        """
        assert '_telegram_notify_login' not in _subscribed(), \
            'уведомление о входе снова подписано на user.login'

    def test_the_log_is_still_subscribed(self):
        """⚠⚠ Обратная сторона, и она важнее.

        Соблазн «убрать уведомление» легко исполняется удалением всей
        регистрации — вместе с журналом входов. Тогда пропало бы и то, чего никто
        не просил убирать: кто и когда заходил в панель.
        """
        assert '_event_log_persist' in _subscribed(), \
            'вместе с уведомлением пропала запись входа в журнал'

    def test_the_handler_itself_is_kept(self):
        """⚠ Сам обработчик оставлен, а не удалён.

        Включить обратно — одна строка в `event_handlers_register`. Удали мы
        функцию, вернуть пришлось бы вместе с отсевом ролей, а он куплен опытом:
        `qa` логинится на каждом тесте.
        """
        assert hasattr(event_handlers, '_telegram_notify_login'), \
            'обработчик удалён — включить уведомление обратно одной строкой нельзя'

    def test_the_role_filter_survives(self):
        """⚠ И отсев полноправных ролей внутри него — тоже.

        Он и есть то знание, ради которого функцию не стали удалять.
        """
        code = inspect.getsource(event_handlers._telegram_notify_login)

        assert 'auth_role_is_full' in code, \
            'отсев полноправных ролей пропал из обработчика'


class TestNothingElseSubscribedQuietly:
    """⚠ Сторож приёма: подписки заводятся в одном месте.

    `event_handlers_register` — единственная точка, где они объявлены. Подпишись
    кто-нибудь на `user.login` мимо неё, отключение выше перестало бы что-либо
    значить, а найти вторую подписку было бы нечем.
    """

    def test_subscriptions_live_in_one_place(self):
        import pathlib

        found = []
        for path in pathlib.Path('src').rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            if "event_subscribe('user.login'" in text \
                    or 'event_subscribe("user.login"' in text:
                found.append(str(path))

        assert found == ['src/event/event_handlers.py'], \
            f'на user.login подписываются мимо общего места: {found}'
