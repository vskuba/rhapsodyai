"""
Пул моделей проекта и захват модели ролью на круг (`src/project/team/team_llm_pool.py`).

Главное, что здесь проверяется: **модель достаётся ровно одному кругу**. Захват —
это `UPDATE ... WHERE свободна`, и вся его надёжность держится на том, что второй
претендент видит `rowcount = 0`. Проверять это разговорами бессмысленно: ошибка в
условии проявится не отказом, а двумя ролями на одном прокси — они будут мешать друг
другу, и виноватым будет выглядеть агент.

Рядом — то, из-за чего пул вообще завели вместо флага `--llm` при запуске:
прилипание к задаче (её прежняя модель предпочтительнее любой свободной, иначе
оболочке придётся перезапускать агента и терять контекст) и предел параллельности,
равный размеру пула.

Тесты работают на живой базе и убирают за собой: ключ настройки и строки захвата
именуются проектом `TEST_PROJECT_ID`, которого в базе нет.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST`
на импорте, а подмена хоста живёт в фикстурах `conftest.py`. Та же дисциплина в
`test_team_setting_autocompact.py` и соседних.
"""

import pytest

# Номер проекта, которого в базе нет: пул и захваты пишутся под ним, и уборка
# сносит ровно их, не задевая настоящие проекты установки.
TEST_PROJECT_ID = 987654

# Имена моделей тестовые: попади сюда настоящая из каталога — тест отнял бы её у
# работающего конвейера на всё время прогона.
TEST_LLM_A = 'test_pool/model-a'
TEST_LLM_B = 'test_pool/model-b'


@pytest.fixture(autouse=True)
async def pool_cleanup():
    """
    Снести пул и захваты тестового проекта — до теста и после.

    До теста тоже: прогон, упавший на середине, оставил бы строки, и следующий
    захват достался бы «занятой» модели без всякой причины.
    """
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestPoolStorage:
    """Пул как значение настройки: что записали, то и прочли."""

    async def test_set_returns_items_with_context(self):
        from src.project.team.team_llm_pool import team_llm_pool_items, team_llm_pool_set

        saved = await team_llm_pool_set(TEST_PROJECT_ID,
                                        [{'name': TEST_LLM_A, 'context': '125k'},
                                         {'name': TEST_LLM_B, 'context': '900k'}])

        assert saved == await team_llm_pool_items(TEST_PROJECT_ID)
        assert [i['name'] for i in saved] == [TEST_LLM_A, TEST_LLM_B]
        assert [i['context'] for i in saved] == ['125k', '900k']

    async def test_bare_names_get_default_context(self):
        """
        Запись без окна — модель с окном по умолчанию.

        Так читаются пулы, сохранённые до появления окон: миграции у настройки нет,
        и строка `имя,имя` обязана остаться рабочей.
        """
        from src.project.team.team_llm_pool import (TEAM_LLM_POOL_CONTEXT_DEFAULT,
                                                    team_llm_pool_items, team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A])
        items = await team_llm_pool_items(TEST_PROJECT_ID)

        assert items == [{'name': TEST_LLM_A, 'context': TEAM_LLM_POOL_CONTEXT_DEFAULT}]

    async def test_duplicates_collapse(self):
        """
        Дубль в списке значит то же, что одно вхождение.

        Оставь мы его — предел параллельности вырос бы на пустом месте: он равен
        длине пула, а второй модели за вторым именем нет.
        """
        from src.project.team.team_llm_pool import team_llm_pool_get, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_A, TEST_LLM_B])

        assert await team_llm_pool_get(TEST_PROJECT_ID) == [TEST_LLM_A, TEST_LLM_B]

    async def test_parallel_is_pool_size(self):
        """Предел одновременной работы — размер пула, отдельной настройки нет."""
        from src.project.team.team_llm_pool import team_llm_pool_parallel, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])
        assert await team_llm_pool_parallel(TEST_PROJECT_ID) == 2

        await team_llm_pool_set(TEST_PROJECT_ID, [])
        assert await team_llm_pool_parallel(TEST_PROJECT_ID) == 1, \
            'Пустой пул — облачный Anthropic, там предел прежний, «по одной»'


class TestAcquire:
    """Захват модели на круг: кому досталась и что видит второй."""

    async def test_empty_pool_gives_nothing(self):
        """Пула нет — захватывать нечего, роль идёт штатным бэкендом."""
        from src.project.team.team_llm_pool import team_llm_pool_acquire

        assert await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer') is None

    async def test_second_claim_gets_the_other_model(self):
        from src.project.team.team_llm_pool import team_llm_pool_acquire, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])

        first = await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer')
        second = await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'qa')

        assert {first, second} == {TEST_LLM_A, TEST_LLM_B}, \
            'Две работы получили одну и ту же модель — они поделили бы один прокси'

    async def test_exhausted_pool_returns_none(self):
        """
        Свободных нет — `None`, а не чужая модель.

        Это и есть предел параллельности: работа ждёт очереди, как ждала при прежнем
        числе «Parallel LLM».
        """
        from src.project.team.team_llm_pool import team_llm_pool_acquire, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A])
        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer')

        assert await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'qa') is None

    async def test_release_returns_model_to_the_pool(self):
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_release,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A])
        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer')
        released = await team_llm_pool_release(llm_name=TEST_LLM_A, task_id=1, role='developer')

        assert released == 1
        assert await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'qa') == TEST_LLM_A

    async def test_release_ignores_foreign_lock(self):
        """
        Снимаем свой захват, а не «эту модель».

        Круг мог протухнуть по сроку и уйти другой работе, пока шёл; сняв его по
        одному имени модели, мы отобрали бы чужую посреди прогона.
        """
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_locks,
                                                    team_llm_pool_release, team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A])
        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer')

        assert await team_llm_pool_release(llm_name=TEST_LLM_A, task_id=999, role='qa') == 0
        assert len(await team_llm_pool_locks(TEST_PROJECT_ID)) == 1

    async def test_sticky_model_preferred_for_same_task(self):
        """
        Задаче возвращают ту модель, на которой она работала прошлый круг.

        Смена модели стоит агенту перезапуска, то есть всего накопленного контекста.
        Проверяем именно предпочтение: к моменту второго круга свободны обе, и первой
        в пуле стоит другая — без прилипания задача получила бы её.

        Первый круг уводят на B чужой ролью, занявшей A: одна роль двумя моделями
        сразу не работает (`test_role_holds_one_model_at_a_time`), и разложить круги
        по разным ролям — единственный способ занять A, не подменяя правило.
        """
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_release,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])

        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'qa')
        assert await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'developer') == TEST_LLM_B
        await team_llm_pool_release(task_id=1)
        await team_llm_pool_release(task_id=2)

        assert await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'developer') == TEST_LLM_B

    async def test_shell_holds_one_model_at_a_time(self):
        """
        Новый круг оболочки гасит её прошлые захваты: агент в ней один.

        На `_llm_release` в `finally` нельзя закладываться целиком — воркер могут
        убить по таймауту job'а или перезапуском контейнера, и модель выпала бы из
        пула до конца срока протухания, то есть на часы. Живьём так и вышло: за
        задачей #2437 повисли обе модели проекта.
        """
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_locks,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])

        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'manager', session_uuid='shell-1')
        await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'manager', session_uuid='shell-1')
        held = [lock for lock in await team_llm_pool_locks(TEST_PROJECT_ID)
                if lock.get('role') == 'manager']

        assert len(held) == 1, 'Оболочка держит две модели разом — вторая осиротела'

    async def test_second_shell_of_role_keeps_its_own_model(self):
        """
        Круг соседней оболочки той же роли модель не отнимает.

        Гасили по роли — и второй менеджер снимал захват первого: в логе «снято 1
        захватов прошлых кругов» ровно в момент старта соседа, а дальше оба круга
        делили один прокси. Оболочек у роли столько, сколько терминалов, и модель у
        каждой своя.
        """
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_locks,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])

        first = await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'manager', session_uuid='shell-1')
        second = await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'manager', session_uuid='shell-2')
        held = {lock['llm_name'] for lock in await team_llm_pool_locks(TEST_PROJECT_ID)}

        assert first != second
        assert held == {TEST_LLM_A, TEST_LLM_B}, 'Сосед по роли отнял модель у идущего круга'

    async def test_foreign_role_lock_survives(self):
        """Чужие захваты новый круг не трогает: гасится только своя роль."""
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_locks,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])

        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'qa')
        await team_llm_pool_acquire(TEST_PROJECT_ID, 2, 'developer')
        roles = {lock.get('role') for lock in await team_llm_pool_locks(TEST_PROJECT_ID)}

        assert roles == {'qa', 'developer'}


class TestLocksPrune:
    """Строки выбывших моделей уходят при пересборке пула."""

    async def test_dropped_model_lock_is_removed(self):
        """
        Модель убрали из пула — её строка захвата больше не нужна.

        Захват её не тронет (берутся только имена из пула), прилипание тоже, — она
        просто копилась бы в таблице. Живой повод: запись каталога развели на две с
        разными портами, и строка со старым именем осталась висеть.
        """
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_locks,
                                                    team_llm_pool_release, team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])
        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer')
        await team_llm_pool_release(task_id=1)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_B])

        assert await _lock_names() == [], 'Строка выбывшей модели осталась в таблице'
        assert await team_llm_pool_locks(TEST_PROJECT_ID) == []

    async def test_model_still_in_pool_survives(self):
        """
        Оставшейся в пуле строка сохраняется: в ней `task_id` прилипания.

        Снеси мы её, следующий круг той же задачи получил бы случайную модель, и агента
        пришлось бы перезапускать со всем накопленным контекстом.
        """
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_release,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])
        await team_llm_pool_acquire(TEST_PROJECT_ID, 7, 'developer')
        await team_llm_pool_release(task_id=7)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A])

        assert await _lock_names() == [TEST_LLM_A]

    async def test_busy_lock_is_kept(self):
        """
        Занятую строку не трогаем: на этой модели прямо сейчас идёт круг.

        Убрать её из-под него значило бы потерять и след работы, и `task_id`. Уйдёт
        следующим сохранением — к тому времени круг кончится.
        """
        from src.project.team.team_llm_pool import team_llm_pool_acquire, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])
        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer')

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_B])

        assert await _lock_names() == [TEST_LLM_A]

    async def test_empty_pool_clears_everything(self):
        """Пул очистили целиком — свободных строк проекта не остаётся."""
        from src.project.team.team_llm_pool import (team_llm_pool_acquire, team_llm_pool_release,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])
        await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer')
        await team_llm_pool_release(task_id=1)

        await team_llm_pool_set(TEST_PROJECT_ID, [])

        assert await _lock_names() == []


class TestConflicts:
    """Пулы проектов не пересекаются: модели общие на машину."""

    async def test_model_of_another_project_is_reported(self):
        from src.project.team.team_llm_pool import team_llm_pool_conflicts, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A])
        taken = await team_llm_pool_conflicts(TEST_PROJECT_ID + 1, [TEST_LLM_A])

        assert taken == {TEST_LLM_A: TEST_PROJECT_ID}

    async def test_own_pool_is_not_a_conflict(self):
        """Свои же модели при пересохранении пула конфликтом быть не могут."""
        from src.project.team.team_llm_pool import team_llm_pool_conflicts, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B])

        assert await team_llm_pool_conflicts(TEST_PROJECT_ID, [TEST_LLM_A, TEST_LLM_B]) == {}


async def _lock_names() -> list:
    """Имена строк захвата тестового проекта — и свободных, и занятых."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT llm_name FROM team_llm_lock WHERE project_id = %s ORDER BY llm_name',
                         (TEST_PROJECT_ID,))

        return [row['llm_name'] for row in await db.fetchall() or []]


async def _cleanup() -> None:
    """Снести настройку пула и строки захвата тестового проекта."""
    from mysql_.mysql_ import mysql_get_db_async
    from src.project.team.team_llm_pool import TEAM_LLM_POOL_KEY_PREFIX

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM team_llm_lock WHERE project_id = %s', (TEST_PROJECT_ID,))
        await db.execute('DELETE FROM setting WHERE `key` = %s',
                         (f'{TEAM_LLM_POOL_KEY_PREFIX}{TEST_PROJECT_ID}',))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
