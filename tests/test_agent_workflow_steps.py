"""
Шаги workflow остаются разбираемыми: `metadata` — это JSON.

Зачем. Промпты ролей лежат в `agent_workflow_step.metadata` строкой JSON и правятся
миграциями через `REPLACE`. Подстановка не знает, куда попадает: вставь в текст
двойную кавычку — она оборвёт строку, и `json.loads` перестанет разбирать шаг целиком.

Так и вышло. Миграции требования к документации вставили в промпт пример команды
`grep -ril "<имя>"` с неэкранированными кавычками. Движок не собрал промпт и отправил
агенту пустоту; в журнале это выглядело как «Разработчик не ответил. Ошибка: prompt
пустой» — про кавычки ни слова. Пять подзадач исчерпали по три попытки и легли в
`blocked`, четыре задачи ушли в `failed`, а работы агент не делал вовсе: ему нечего
было читать.

Глазами такое не поймать: текст в колонке выглядит правильным, обрыв виден только
разбору. Поэтому проверка машинная.

**Проверяем те workflow, что заведены агентам.** Это ровно те, которые движок грузит;
у остальных сломанный шаг не вредит никому. Граница держит себя сама: привяжут агента
— workflow попадёт под проверку. В базе живут и мёртвые (`test`, `response_cashier`,
без единого агента, сломаны давно и не нами) — гонять по ним значило бы иметь красный
тест с первого дня, а такой перестают читать.
"""

import json

import pytest


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestStepMetadata:
    """Разбор колонки. Ломается она правкой промптов — и ломается молча."""

    async def test_every_live_step_parses(self):
        """
        Главное. Шаг, который не разбирается, — это роль без промпта: круги горят,
        попытки тратятся, задача уходит в `blocked`, а причина не названа нигде.
        """
        broken = []
        for step in await _live_steps():
            try:
                json.loads(step['metadata'] or '{}')
            except Exception as error:
                broken.append(f"workflow {step['workflow_id']}, шаг {step['id']} "
                              f"«{step['step_title']}»: {error}")

        assert not broken, 'шаги не разбираются как JSON:\n' + '\n'.join(broken)

    async def test_prompt_steps_are_not_empty(self):
        """
        Разбор — половина дела: пустой текст промпта тоже даёт круг ни о чём, но
        проходит разбор без единой жалобы.

        Смотрим `variable_conversion` — шаги, которые собирают переменные, в том числе
        промпты ролей. Пустое значение там законно (переменную гасят намеренно), а вот
        пустой промпт — нет: имя переменной кончается на `_prompt`.
        """
        empty = []
        for step in await _live_steps():
            try:
                data = json.loads(step['metadata'] or '{}')
            except Exception:
                continue   # разбор проверяет соседний тест, здесь он не при чём

            for item in data.get('variable_conversion') or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get('variable') or '')
                if name.endswith('_prompt') and not str(item.get('text') or '').strip():
                    empty.append(f"workflow {step['workflow_id']}, шаг {step['id']} "
                                 f"«{step['step_title']}»: переменная {name} пуста")

        assert not empty, 'промпты без текста:\n' + '\n'.join(empty)


class TestPipelineRoles:
    """Роли конвейера отдельно: их поломка останавливает работу целиком."""

    # Менеджер, разработчик, QA, багфиксер. Их промпты правятся чаще прочих — каждое
    # уточнение инструкции приезжает миграцией, — и цена поломки здесь наибольшая.
    ROLE_WORKFLOWS = (55, 56, 57, 59)

    async def test_role_workflows_have_steps(self):
        """
        Workflow без шагов — это роль, которая не запустится. Проверяем до разбора:
        пустой список разбирается прекрасно и ничего не говорит.
        """
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT workflow_id, COUNT(*) AS n FROM agent_workflow_step '
                f" WHERE workflow_id IN ({', '.join(['%s'] * len(self.ROLE_WORKFLOWS))}) "
                ' GROUP BY workflow_id', list(self.ROLE_WORKFLOWS))
            counts = {int(r['workflow_id']): int(r['n']) for r in await db.fetchall() or []}

        missing = [wf for wf in self.ROLE_WORKFLOWS if not counts.get(wf)]

        assert not missing, f'у workflow ролей нет шагов: {missing}'

    async def test_role_prompts_survive_migrations(self):
        """
        Промпт роли собирается: шаг разбирается и текст на месте.

        Проверка именно того, что упало живьём: `json.loads` шага 433 обрывался на
        кавычке, движок отдавал пустоту, и дефект всплыл только по вставшему конвейеру.
        """
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT id, workflow_id, title, metadata FROM agent_workflow_step '
                f" WHERE workflow_id IN ({', '.join(['%s'] * len(self.ROLE_WORKFLOWS))}) "
                "   AND metadata LIKE '%%_prompt%%'", list(self.ROLE_WORKFLOWS))
            steps = await db.fetchall() or []

        assert steps, 'шагов с промптами не нашлось — проверять нечего'

        for step in steps:
            try:
                data = json.loads(step['metadata'] or '{}')
            except Exception as error:
                pytest.fail(f"workflow {step['workflow_id']}, шаг {step['id']} "
                            f"«{step['title']}» не разбирается: {error}")

            for item in data.get('variable_conversion') or []:
                if isinstance(item, dict) and str(item.get('variable') or '').endswith('_prompt'):
                    assert str(item.get('text') or '').strip(), (
                        f"workflow {step['workflow_id']}, шаг {step['id']}: промпт пуст")


async def _live_steps() -> list:
    """
    Шаги workflow, которые заведены агентам, — то есть тех, что грузит движок.

    Мёртвые workflow не берём намеренно: см. докстринг модуля.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT s.id, s.workflow_id, s.title AS step_title, s.metadata '
            '  FROM agent_workflow_step s '
            ' WHERE s.workflow_id IN '
            '       (SELECT DISTINCT workflow_id FROM agent WHERE workflow_id IS NOT NULL) '
            ' ORDER BY s.workflow_id, s.position')

        return list(await db.fetchall() or [])


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
