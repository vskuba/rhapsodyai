"""Намерение не задваивается между прогонами, а повторное — считается новым.

## ⚠⚠⚠ Две беды разом, и они тянут в разные стороны

**Дубль.** Намерение находят по тексту истории, а история накапливается:
реплика «can you send me your photos» остаётся в окне двадцати обменов. Без
границы одно обещание уезжало бы вызывающему на каждом ответе — раз двадцать
подряд.

**Потеря.** Но обещание, данное снова через две реплики, — **новое**, и его
ждут. Строка при этом та же самая (`instructions` темы — константа), так что
«было — больше не отдаём» убило бы второе обещание навсегда.

Мирит их **время**: намерение №2 родилось из реплик, пришедших позже намерения
№1. Отметка режет историю надвое, и новое ищут только в свежей половине.

## ⚠⚠ Граница не режет обмен пополам

Намерение находят **до** того, как прогон запишет свой ответ, — отметка ложится
между его репликой и нашей. Оставь её так, и наш ответ выпал бы из половины
«до» и всплыл в «свежей». А в нём те же слова, что в обещании («sure, i will
send you a photo»), — модель приняла бы **наше собственное** обещание за новое,
данное собеседником.

Поэтому отметка, попавшая внутрь обмена, сдвигается до его конца. Это
проверяется здесь же и отдельно: ошибка тихая, видна только дублем в выдаче.

⚠ Тесты идут на живой базе и убирают за собой: ключи пары одноразовые
(`tci_*`), чужих разговоров не трогают.
"""
import time

import pytest

from src.tool.companion.companion import companion_create
from src.tool.companion.companion_intention import (companion_intention_add,
                                                    companion_intention_last_at)
from src.tool.companion.companion_session import companion_session_history
from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

pytestmark = pytest.mark.ai


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого свой.

    ⚠ Без этого второй тест берёт пул, заведённый первым, и падает на
    освобождении соединения — `Event loop is closed`, и ни слова о настоящей
    причине. Тот же приём, что у соседнего `test_companion_session_incoming.py`.
    """
    yield

    await mysql_pool_close()

# Метка разговора этого прогона: упавший тест оставит данные, а повтор не должен
# на них наткнуться.
RUN = int(time.time())
OWNER = f'tci_girl_{RUN}'
COMPANION = f'tci_man_{RUN}'

# Намерение темы «Отправка фото» — ровно то, что лежит в `instructions`.
INTENTION = 'she_promised_send_photo'


@pytest.fixture
async def talk():
    """Разговор из трёх обменов: обещание, пустой, повторное обещание.

    ⚠ Времена заданы явно, а не «сейчас»: весь разговор, записанный одной
    секундой, лёг бы по одну сторону любой границы — и тест зеленел бы, ничего
    не проверив.
    """
    owner_id = int((await companion_create(OWNER)).get('id') or 0)
    companion_id = int((await companion_create(COMPANION)).get('id') or 0)

    rows = (
        ('10:00:00', '10:00:10', 'can you send me your photos?',
         'sure, i will send you a photo'),
        ('10:30:00', '10:30:05', 'where do you live?', 'in Kyiv'),
        ('11:00:00', '11:00:05', 'can you send one more photo?', 'yes, of course'),
    )

    async with mysql_get_db_async() as db:
        for question_at, answer_at, question, answer in rows:
            await db.execute(
                'INSERT INTO `companion_session` (`owner_id`, `companion_id`, `kind`,'
                ' `question`, `question_at`, `answer`, `answer_at`, `delivered_at`,'
                ' `request_uuid`) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)',
                (owner_id, companion_id, 'chat', question, f'2026-10-11 {question_at}',
                 answer, f'2026-10-11 {answer_at}', f'tci-{RUN}'))

    yield {'owner_id': owner_id, 'companion_id': companion_id}

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM `companion_intention` WHERE `owner_id` = %s',
                         (owner_id,))
        await db.execute('DELETE FROM `companion_session` WHERE `owner_id` = %s',
                         (owner_id,))
        await db.execute('DELETE FROM `companion` WHERE `id` IN (%s, %s)',
                         (owner_id, companion_id))


class TestTheBoundary:
    """Отметка намерения как граница свежести."""

    async def test_no_intention_means_no_boundary(self, talk):
        """⚠ Ни одного намерения — граница пуста, и свежим считается весь разговор.

        Пустота тут законна: первое обещание надо найти, а резать нечего.
        """
        assert await companion_intention_last_at(OWNER, COMPANION) == ''

    async def test_the_boundary_is_not_inside_an_exchange(self, talk):
        """⚠⚠ Главный сторож: граница сдвигается до конца обмена.

        Намерение записано в 10:00:05 — между его репликой (10:00:00) и нашим
        ответом (10:00:10). Граница обязана стать 10:00:10, иначе наш ответ
        уедет в свежую половину и будет сочтён новым обещанием.
        """
        await _intention_at(talk, '2026-10-11 10:00:05')

        assert await companion_intention_last_at(OWNER, COMPANION) == \
            '2026-10-11 10:00:10', 'граница разрезала обмен пополам'

    async def test_our_own_promise_stays_on_the_checked_side(self, talk):
        """⚠⚠ Наш ответ с теми же словами не попадает в свежее.

        В нём стоят `send` и `photo` — ровно те метки, что подняли тему. Окажись
        он в свежей половине, дубль пришёл бы от наших же слов.
        """
        await _intention_at(talk, '2026-10-11 10:00:05')
        edge = await companion_intention_last_at(OWNER, COMPANION)

        fresh = await companion_session_history(OWNER, COMPANION, since=edge,
                                                companion_message_at_least=0)

        assert 'i will send you a photo' not in fresh, \
            f'наше обещание всплыло в свежей половине:\n{fresh}'


class TestTheHistoryIsCutInTwo:
    """Половины разговора: что в какой оказывается."""

    async def test_the_old_promise_goes_to_the_checked_half(self, talk):
        """⚠ Уже найденное обещание — в половине «до», она даётся для контекста."""
        await _intention_at(talk, '2026-10-11 10:00:05')
        edge = await companion_intention_last_at(OWNER, COMPANION)

        before = await companion_session_history(OWNER, COMPANION, until=edge,
                                                 companion_message_at_least=0)

        assert 'can you send me your photos' in before
        assert 'can you send one more photo' not in before, \
            'новое обещание попало в проверенную половину'

    async def test_the_new_promise_goes_to_the_fresh_half(self, talk):
        """⚠⚠ Повторная просьба — в свежей половине, и это новое намерение."""
        await _intention_at(talk, '2026-10-11 10:00:05')
        edge = await companion_intention_last_at(OWNER, COMPANION)

        fresh = await companion_session_history(OWNER, COMPANION, since=edge,
                                                companion_message_at_least=0)

        assert 'can you send one more photo' in fresh
        assert 'yes, of course' in fresh

    async def test_the_halves_never_overlap(self, talk):
        """⚠⚠ Ни одна строка не попадает в обе половины разом.

        `since` строго больше, `until` включительно. Будь обе включительными,
        обмен на самой отметке приехал бы дважды — и модель сочла бы его
        повтором обещания.
        """
        await _intention_at(talk, '2026-10-11 10:00:05')
        edge = await companion_intention_last_at(OWNER, COMPANION)

        before = set(_said(await companion_session_history(
            OWNER, COMPANION, until=edge, companion_message_at_least=0)))
        fresh = set(_said(await companion_session_history(
            OWNER, COMPANION, since=edge, companion_message_at_least=0)))

        assert not (before & fresh), f'строки в обеих половинах: {before & fresh}'

    async def test_without_a_boundary_the_whole_talk_is_fresh(self, talk):
        """⚠ Границы нет — свежим считается весь разговор, резать нечего."""
        whole = await companion_session_history(OWNER, COMPANION, since='',
                                                companion_message_at_least=0)

        assert 'can you send me your photos' in whole
        assert 'can you send one more photo' in whole


class TestTheSecondPromiseIsNotADuplicate:
    """Повторное обещание — своя запись, а не дубль."""

    async def test_the_same_wording_is_written_twice(self, talk):
        """⚠⚠⚠ Запись повтора не проверяет: второе обещание законно.

        Текст один и тот же — отличает их только время. Отсеки мы повтор по
        строке, и второе обещание пропало бы навсегда.
        """
        first = await companion_intention_add(OWNER, COMPANION, INTENTION)
        second = await companion_intention_add(OWNER, COMPANION, INTENTION)

        assert first.get('saved') == 1 and second.get('saved') == 1
        assert first.get('id') != second.get('id'), 'повтор не завёл своей строки'

        assert await _intentions_qty(talk) == 2, 'повтор не лёг второй строкой'

    async def test_the_boundary_follows_the_latest(self, talk):
        """⚠ Граница идёт за последним намерением, а не за первым."""
        await _intention_at(talk, '2026-10-11 10:00:05')
        await _intention_at(talk, '2026-10-11 11:00:30')

        assert await companion_intention_last_at(OWNER, COMPANION) == \
            '2026-10-11 11:00:30'

    async def test_after_the_second_the_fresh_half_is_empty(self, talk):
        """⚠⚠ Найдя второе обещание, свежую половину вычерпали досуха.

        Следующий прогон не найдёт в ней ничего — значит третий дубль не придёт.
        Это и есть проверка «намерение отдаётся один раз».
        """
        await _intention_at(talk, '2026-10-11 11:00:30')
        edge = await companion_intention_last_at(OWNER, COMPANION)

        fresh = await companion_session_history(OWNER, COMPANION, since=edge,
                                                companion_message_at_least=0)

        assert fresh.strip() == '', f'после второго намерения свежее не пусто:\n{fresh}'


class TestTheToolKeepsTheIntention:
    """Инструмент контракта пишет намерение в разговор."""

    async def test_it_writes_when_the_pair_is_named(self, talk):
        """⚠⚠ Пара названа — намерение попадает в разговор, и `at` это показывает."""
        from src.tool.chat.chat_intention import chat_intention_add

        answer = await chat_intention_add(INTENTION, OWNER, COMPANION)

        assert answer.get('intention') == INTENTION
        assert answer.get('at'), 'отметка времени не вернулась — записи не было'
        assert await companion_intention_last_at(OWNER, COMPANION)

    async def test_it_still_answers_without_a_pair(self, talk):
        """⚠ Без пары работает по-прежнему: намерение уедет в ответ, но не в разговор.

        Так зовут из пробных прогонов и чужих workflow. Молчаливой потери нет —
        пустой `at` виден в трассе шага.
        """
        from src.tool.chat.chat_intention import chat_intention_add

        answer = await chat_intention_add(INTENTION)

        assert answer.get('intention') == INTENTION
        assert answer.get('at') == ''
        assert await companion_intention_last_at(OWNER, COMPANION) == '', \
            'намерение записалось в разговор, которого ему не называли'


# ---------------------------------------------------------------------------
# Приватное
# ---------------------------------------------------------------------------

async def _intentions_qty(talk: dict) -> int:
    """Сколько намерений записано этой паре — прямым счётом в базе.

    ⚠ Запросом, а не через инструмент: отдельной функции чтения у намерений нет
    и заводить её ради теста нельзя — публичное имя, которое зовёт только его
    же тест, это мёртвый код, а не API.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT COUNT(*) AS qty FROM `companion_intention`'
            ' WHERE `owner_id` = %s AND `intention` = %s',
            (talk['owner_id'], INTENTION))
        row = await db.fetchone()

    return int((row or {}).get('qty') or 0)


async def _intention_at(talk: dict, at: str) -> None:
    """Намерение с заданной отметкой: живая запись ставит `NOW()`, а тесту нужна своя."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO `companion_intention` (`owner_id`, `companion_id`,'
            ' `intention`, `created_at`) VALUES (%s, %s, %s, %s)',
            (talk['owner_id'], talk['companion_id'], INTENTION, at))


def _said(history: str) -> list:
    """Слова реплик без отметок времени — чтобы сравнивать половины по содержанию."""
    return [line.split(': ', 1)[-1] for line in str(history or '').splitlines()
            if line.strip()]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
