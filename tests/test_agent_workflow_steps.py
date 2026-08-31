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

pytestmark = pytest.mark.ai


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


class TestStepTimeouts:
    """
    Срок шага не должен обрывать работу — это дело потолка роли.

    У каждого обращения к оболочке свой срок, литералом `_const_N` в `inputs_map`, и
    он срабатывает раньше потолка прогона. Поставь его ниже, чем такой ход занимает на
    самом деле, — и шаг рвёт работу посреди дела, конвейер ставит прогон заново, круг
    повторяется. Живьём: подняли `timeout_developer_run` до четырёх часов, а обрывы
    продолжились с прежней формулировкой и другой цифрой — «не ответил за 1200с».

    Глазами это не видно: в трейсе шаг выглядит как «долгий», а не как «обрезанный».
    Отличает их одно — максимум упирается в срок до секунды.
    """

    ROLE_WORKFLOWS = (55, 56, 57, 59)

    # Потолки прогона по ролям (`task_setting_timeout.py`). Ключ — workflow роли.
    WORKFLOW_CEILING_KEY = {
        55: 'timeout_manager_run',
        56: 'timeout_developer_run',
        57: 'timeout_qa_run',
        59: 'timeout_bugfix_run',
    }

    async def test_step_timeout_below_role_ceiling(self):
        """
        Ни один шаг не длиннее потолка своей роли.

        Такой шаг не может отработать никогда: потолок оборвёт прогон раньше, чем
        истечёт срок шага. Роль при этом выглядит рабочей — она просто всегда падает.
        """
        from src.project.task.task_setting_timeout import (
            TASK_SETTING_TIMEOUT_ITEMS, task_setting_timeout_all)
        from src.project.task.task_setting_step import task_setting_step_timeout_of

        values = {item['key']: item['value'] for item in await task_setting_timeout_all()}
        defaults = {item['key']: item['default'] for item in TASK_SETTING_TIMEOUT_ITEMS}

        over = []
        for step in await _live_steps():
            workflow_id = int(step['workflow_id'])
            key = self.WORKFLOW_CEILING_KEY.get(workflow_id)
            if not key:
                continue

            seconds = task_setting_step_timeout_of(json.loads(step['metadata'] or '{}'))
            if not seconds:
                continue

            ceiling = int(values.get(key) or defaults.get(key) or 0)
            if ceiling and seconds >= ceiling:
                over.append(f"шаг {step['id']} «{step['step_title']}»: "
                            f'{seconds}с при потолке {key} = {ceiling}с')

        assert not over, ('шаги, которые не успеют отработать до потолка роли:\n'
                          + '\n'.join(over))

    async def test_step_timeout_above_observed_work(self):
        """
        Срок шага выше того, что этот шаг занимал на самом деле.

        Замеры живые (`project_task_metric`), поэтому проверка растёт вместе с
        проектом: сегодня она молчит, а стоит какому-то шагу упереться в свой срок —
        краснеет с именем шага. Ровно этого не хватало, когда обрывы искали глазами
        по трейсам.

        Метрик нет вовсе (свежая база) — проверять нечего, и это не повод падать.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_setting_step import task_setting_step_timeout_of

        limits = {}
        for step in await _live_steps():
            if int(step['workflow_id']) not in self.ROLE_WORKFLOWS:
                continue
            seconds = task_setting_step_timeout_of(json.loads(step['metadata'] or '{}'))
            if seconds:
                limits[str(step['step_title'])] = seconds

        if not limits:
            pytest.skip('шагов со сроком не нашлось')

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT step_title, ROUND(MAX(duration_ms) / 1000) AS max_s '
                '  FROM project_task_metric '
                ' WHERE duration_ms IS NOT NULL GROUP BY step_title')
            observed = {str(r['step_title']): int(r['max_s'] or 0)
                        for r in await db.fetchall() or []}

        if not observed:
            pytest.skip('замеров ещё нет — сравнивать не с чем')

        walls = [f'«{title}»: доходил до {observed[title]}с при сроке {limit}с'
                 for title, limit in limits.items()
                 if observed.get(title, 0) >= limit]

        assert not walls, ('шаги упирались в собственный срок — работу режет шаг, а не '
                           'потолок роли:\n' + '\n'.join(walls))


class TestMigrationNames:
    """
    Метка времени миграции — до секунд, и она не должна повторяться.

    Правило `YYYYMMDDHHMMSS` записано давно, но большая часть меток в проекте
    «круглая» (`...150000`, `...140500`): их писали руками, округляя до минуты. Роль
    копирует то, что видит, и две работы одного часа берут один номер — вся
    уникальность метки пропадает.

    Живьём: подзадача #5219 собиралась завести `20260831150000_wf57_qa_mode.sql`, а
    такой номер за четверть часа до неё занял соседний файл. Два файла на одну метку
    yoyo применит в неопределённом порядке, а при слиянии веток это конфликт.

    Старые метки не трогаем: они уже применены, и переименование сдвинуло бы журнал
    yoyo без всякой пользы. Проверяем только то, что дубликатов нет — это и есть
    свойство, ради которого метка времени выбрана.
    """

    MIGRATION_DIR = 'migrations'

    def test_no_duplicate_timestamps(self):
        """
        Двух миграций с одной меткой быть не должно: порядок их применения не
        определён, а при слиянии веток одна молча потеряется.
        """
        import os
        from collections import Counter

        stamps = Counter(name.split('_', 1)[0]
                         for name in os.listdir(self.MIGRATION_DIR)
                         if name.endswith('.sql'))
        doubled = {stamp: count for stamp, count in stamps.items() if count > 1}

        assert not doubled, f'метки повторяются: {doubled}'

    def test_timestamps_are_full_length(self):
        """
        Метка — ровно `YYYYMMDDHHMMSS`, четырнадцать цифр. Короче — это не время, и
        сортировка файлов перестанет совпадать с хронологией.
        """
        import os

        bad = [name for name in sorted(os.listdir(self.MIGRATION_DIR))
               if name.endswith('.sql')
               and not (name.split('_', 1)[0].isdigit() and len(name.split('_', 1)[0]) == 14)]

        assert not bad, f'метка не похожа на YYYYMMDDHHMMSS: {bad}'


class TestSelfCheckLoop:
    """
    Круг самопроверки разработчика должен иметь возможность сработать.

    Дефект был тихий. Переходы шага «Ответ JSON: самопроверка» проверяются по
    порядку, и условие лимита (`dev_iteration >= max_dev_iterations`) стоит раньше,
    чем `dev_ok != yes`. При лимите в единицу первый же круг его достигает: рецензент
    находит замечания, выносит `dev_ok: no` — и работа всё равно уходит к QA как есть.

    Живьём #5235: три замечания (185 продублированных строк, контракт ответа не по
    правилам, потерянные докстринги) написаны, прочитаны человеком в журнале и
    выброшены. Шаг существовал в режиме, где не мог сработать ни разу, а токены на
    него тратились — шесть минут работы агента.
    """

    # Замеры по 41 прогону разработчика (`project_task_metric`, секунды):
    #
    #            разбор  реализация  отчёт  самопроверка  ответ
    #   среднее     481        1169    240           355     53
    #   худшее     1226        4807   1207          1240    106
    #
    # Первый круг дороже последующих на разбор — он не повторяется.
    #
    # Порог составной, и это не произвол. **Первый круг берём по худшим замерам**:
    # именно долгие прогоны рвались по таймауту, а по средним всё укладывалось и в
    # прежние 7000с — проверка по среднему прошла бы на сломанной конфигурации, то
    # есть не проверяла бы ничего. **Доработки — по средним**: три круга по худшим
    # это 6.5 часа, и покрывать их потолком нельзя намеренно (см. миграцию
    # 20260831221943) — оболочка в проекте одна, и висящая подзадача останавливает
    # всю очередь.
    ROUND_FIRST_SEC = 8586      # худший первый круг: 1226+4807+1207+1240+106
    ROUND_REWORK_SEC = 1817     # средняя доработка: 1169+240+355+53

    async def test_dev_iterations_allow_rework(self):
        """
        Лимит больше единицы — иначе шаг самопроверки бесполезен по построению.
        """
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT `default` FROM agent_workflow_variable WHERE name = %s',
                ('max_dev_iterations',))
            row = await db.fetchone()

        assert row, 'переменная max_dev_iterations не заведена'
        assert int(row['default']) >= 2, (
            'при лимите 1 круг самопроверки не может сработать: условие лимита '
            'проверяется раньше, чем dev_ok != yes')

    async def test_timeout_covers_all_rework_rounds(self):
        """
        Потолок прогона обязан покрывать все разрешённые круги доработки.

        Разойдись они — разработчик получает право на три круга и обрывается на
        третьем по таймауту. Именно это и происходило: у #5219 семь из десяти
        последних попыток кончились «не ответил за 4800с», и каждая ставилась заново,
        сжигая по восемьдесят минут работы агента.

        Считаем по замерам, а не по догадке: первый круг дороже последующих на
        разбор, который не повторяется.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_setting_timeout import (
            TASK_SETTING_TIMEOUT_DEVELOPER_RUN, task_setting_timeout_get)

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT `default` FROM agent_workflow_variable WHERE name = %s',
                ('max_dev_iterations',))
            rounds = int((await db.fetchone() or {}).get('default') or 0)

        timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_DEVELOPER_RUN)
        need = self.ROUND_FIRST_SEC + self.ROUND_REWORK_SEC * (rounds - 1)

        assert timeout >= need, (
            f'{rounds} кругов требуют ~{need}с (медленный первый + средние доработки), '
            f'а timeout_developer_run = {timeout}с: круги оборвутся по таймауту, '
            f'и каждый оборванный прогон будет ставиться заново')

    async def test_timeout_ladder_holds(self):
        """
        Лестница «прогон агента < job воркера < блокировка строки» цела.

        Поднимая потолок агента, легко забыть про соседей: тогда воркера убьют
        раньше, чем прогон сорвётся сам, либо соседний тик заберёт строку, над
        которой ещё работают, — и оба исхода выглядят как «агент не ответил».
        """
        from src.project.task.task_setting_timeout import (
            task_setting_timeout_all, task_setting_timeout_ladder_problem)

        rows = await task_setting_timeout_all()
        values = {item['key']: item.get('value') for item in rows}

        assert not task_setting_timeout_ladder_problem(values)

    async def test_rework_step_returns_to_implementation(self):
        """
        Цикл замкнут: шаг замечаний возвращает на реализацию, а не в никуда.

        Без этого перехода поднятый лимит ничего не дал бы — замечания записались бы
        в переменную, и работа всё равно ушла бы дальше.
        """
        import json

        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT id, title, metadata FROM agent_workflow_step "
                " WHERE workflow_id = 56 AND title LIKE %s", ('%Замечания%',))
            rows = await db.fetchall() or []

        assert rows, 'шага «Замечания на доработку» в workflow разработчика нет'

        step = dict(rows[0])
        data = json.loads(step['metadata'] or '{}')
        targets = {str(t.get('step_id')) for t in data.get('transitions_after') or []}

        assert targets, f"шаг {step['id']} никуда не ведёт — замечания повиснут"



    """
    Миграции промптов не должны оставлять шаг неразбираемым.

    Соседние тесты проверяют базу — и краснеют уже после применения, то есть когда
    конвейер сломан и роли получают пустые промпты. Здесь проверка идёт по файлам:
    каждую миграцию, правящую `metadata`, прогоняем через тот же разбор, что и живой
    шаг, и смотрим, переживёт ли он её.

    Дефект повторяется, и в этом всё дело. Первый раз пример `grep -ril "<имя>"`
    оборвал JSON шага 433: пять подзадач легли в `blocked`, четыре задачи ушли в
    `failed`. Второй — пример тела запроса вида {"name": ...} в шаге 435, спустя два
    дня и в другой миграции. Оба раза кавычки выглядели безобидно: это же просто
    пример в тексте.

    Причина — три уровня вложенности. Текст промпта лежит внутри JSON-строки колонки
    `metadata`, та внутри SQL-строки миграции, и незаэкранированная кавычка обрывает
    JSON молча: SQL отработает, шаг перестанет разбираться, а в журнале это выглядит
    как «агент не ответил».
    """

    async def test_applied_migrations_left_steps_parseable(self):
        """
        Каждый шаг, который трогали миграции промптов, разбирается сейчас.

        Проверка по базе, а не по тексту файлов: правило «кавычек в тексте быть не
        должно» слишком грубое — законных кавычек в миграциях полно (`CHAR(92)`,
        экранированный JSON внутри промпта, значения колонок). Важно не наличие
        кавычки, а то, читается ли шаг после неё.

        Номера шагов берём из самих файлов: какие правили, те и смотрим. Так тест
        растёт вместе с миграциями и не требует правки при каждой новой.
        """
        import json
        import os
        import re

        from mysql_.mysql_ import mysql_get_db_async

        touched = set()
        for name in sorted(os.listdir('migrations')):
            if not name.endswith('.sql'):
                continue
            text = open(os.path.join('migrations', name), encoding='utf-8').read()
            if 'agent_workflow_step' not in text:
                continue
            for chunk in re.findall(r'`id`\s*(?:=|IN)\s*\(?([\d,\s]+)\)?', text):
                touched.update(int(n) for n in re.findall(r'\d+', chunk))

        assert touched, 'миграций, правящих шаги, не нашлось — проверять нечего'

        async with mysql_get_db_async() as db:
            placeholders = ', '.join(['%s'] * len(touched))
            await db.execute(
                f'SELECT id, title, metadata FROM agent_workflow_step '
                f' WHERE id IN ({placeholders})', sorted(touched))
            rows = await db.fetchall() or []

        broken = []
        for row in rows:
            try:
                json.loads(row['metadata'] or '{}')
            except Exception as error:
                broken.append(f"шаг {row['id']} «{row['title']}»: {error}")

        assert not broken, (
            'шаги, которые правили миграции, перестали разбираться:\n' + '\n'.join(broken))


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
