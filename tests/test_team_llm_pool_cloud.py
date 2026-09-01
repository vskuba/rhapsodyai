"""
Оболочка без `--litellm` не берёт модель из пула — `team_llm_pool_shell_cloud`.

Зачем это правило. Флаг `--litellm` — единственная разница между двумя способами
работы роли: с ним оболочка ждёт модель от конвейера, без него работает родным
облачным агентом Claude Code. Выдай пул модель облачной оболочке — и `__SWITCH_LLM__`
переведёт её на пул молча: `shell.py:_switch_llm` режима запуска не спрашивает,
поднимает прокси, переписывает `ANTHROPIC_BASE_URL` и перезапускает агента. Флаг
оказался бы декорацией, а человек — с перезапущенным агентом и потерянным контекстом.

Второе, что держится на этом правиле, — сам признак режима. Режим и имя модели лежат
в одной колонке `server_llm`: оболочка пишет туда `anthropic`, пока своей модели нет,
и имя модели, когда её выдали. Одна выдача — и отличить облачную оболочку от пуловой
нечем навсегда, до перезапуска терминала.

Тесты идут на живой базе и убирают за собой: сессии заводятся в вымышленном каталоге,
и удаляются по нему же.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import uuid

import pytest

pytestmark = pytest.mark.team

# Каталог, которого не существует: по нему тестовые сессии отличимы от настоящих
# оболочек установки и сносятся уборкой целиком.
TEST_WORK_DIR = '/tmp/llm-pool-cloud-test'


@pytest.fixture(autouse=True)
async def registry_cleanup():
    """Снести тестовые сессии — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestShellCloud:
    """Кому пул модель не выдаёт."""

    async def test_shell_without_flag_is_cloud(self):
        """`anthropic` в реестре — оболочку подняли без `--litellm`."""
        from src.project.team.team_llm_pool import team_llm_pool_shell_cloud

        session_uuid = await _session_write('anthropic')

        assert await team_llm_pool_shell_cloud(session_uuid) is True

    async def test_shell_under_pool_is_not_cloud(self):
        """`litellm` — оболочка ждёт выдачи, и она ей полагается."""
        from src.project.team.team_llm_pool import team_llm_pool_shell_cloud

        session_uuid = await _session_write('litellm')

        assert await team_llm_pool_shell_cloud(session_uuid) is False

    async def test_shell_on_model_is_not_cloud(self):
        """
        Оболочка уже работает моделью пула — следующий круг она получит так же.

        Иначе прилипание к модели ломалось бы на первом же круге: захват гаснет вместе
        с кругом, а имя в реестре остаётся, и вторую выдачу такая оболочка не получила
        бы никогда.
        """
        from src.project.team.team_llm_pool import team_llm_pool_shell_cloud

        session_uuid = await _session_write('gx10/qwen-large')

        assert await team_llm_pool_shell_cloud(session_uuid) is False

    async def test_unknown_session_is_not_cloud(self):
        """
        Оболочки в реестре нет — решает не эта функция.

        Пустой ответ здесь означал бы «модель не выдавать», то есть отправить круг на
        облачные токены из-за того, что строку не нашли.
        """
        from src.project.team.team_llm_pool import team_llm_pool_shell_cloud

        assert await team_llm_pool_shell_cloud(str(uuid.uuid4())) is False

    async def test_empty_session_is_not_cloud(self):
        """Адреса нет вовсе — прежний путь выдачи, как было до захвата оболочек."""
        from src.project.team.team_llm_pool import team_llm_pool_shell_cloud

        assert await team_llm_pool_shell_cloud('') is False


async def _session_write(server_llm: str) -> str:
    """Строка реестра с заданным режимом. Возвращает `session_uuid`."""
    from datetime_.datetime_ import datetime_utc_now
    from mysql_.mysql_ import mysql_get_db_async

    session_uuid = str(uuid.uuid4())
    now = datetime_utc_now()
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO ai_claude_session_registry '
            '       (session_uuid, role, role_index, project_label, status, '
            '        server_llm, work_dir, created_at, last_seen_at) '
            "VALUES (%s, 'developer', 1, 'llm-pool-cloud-test', 'active', %s, %s, %s, %s)",
            (session_uuid, server_llm, TEST_WORK_DIR, now, now))
        await db.connection.commit()

    return session_uuid


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM ai_claude_session_registry WHERE work_dir LIKE %s',
                         (f'{TEST_WORK_DIR}%',))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
