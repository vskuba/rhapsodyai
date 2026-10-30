"""Литерал `_const_` в карте входов: доживает свой век, новых не заводим.

## ⚠⚠ Чем плох литерал

Значение, записанное в `inputs_map` как `_const_600`, лежит **в метаданных
шага**. В списке переменных потока его нет; на странице оно видно, только если
раскрыть шаг; поправить его человек может лишь там же, вслепую. Больнее всего
это у долей жребия — единственного места, где задаётся разнообразие писем:
тринадцать тысяч знаков JSON были спрятаны в метаданных одного шага.

У объявленной переменной есть имя, подпись и **одно** место правки — даже
когда читателей двое, как у двух половин ленты истории в WF76.

## ⚠⚠ Запрет снят с памяти и поставлен в движок

С 30.10.2026 шаг с литералом отвечает **отказом словами**, а не работает
втихую: `ai_framework_manager` бросает `ValueError` с именем шага и довода.
Переезд шёл в порядке, обратном привычному — сперва потребители, потом
движок:

| Заход | Что |
|-------|-----|
| 1 | доли жребия и лента истории (`dating_*`, WF76) |
| 2 | 26 сроков шагов (`task_*`) **вместе с их читателями** — карточка команды и счёт прогресса разбирали литерал мимо движка |
| 3 | 16 предметных строк (`planning_*`) |
| 4 | ветка убрана из движка |

Сними мы ветку раньше второго захода — карточка показала бы ноль там, где шаг
ждёт два часа, и человек правил бы настройку, которая этот шаг не трогает.

⚠ Сторож остаётся **счётом**, а не проверкой кода: запрет движка виден только
на прогоне, а литерал заводят правкой базы — страницей или скриптом. Ноль
здесь значит «в базе чисто», и это единственный способ узнать о возврате до
того, как встанет прогон.

Поэтому здесь считается **потолок**, и он только убывает: перевёл потребителя —
опусти число. Завести новый литерал он не даст, а переезд не торопит.
"""
import json

import pytest

pytestmark = pytest.mark.ai


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


# Приставка литерала — та же, что читает движок.
PREFIX = '_const_'

# Сколько **доводов** его ещё держат. Ноль: переезд кончен, и движок такой шаг
# больше не исполняет — отвечает отказом.
#
# ⚠ Число **только вниз**. Оно и так на нуле, но правило остаётся: сторож
# падает и на росте, и на снижении без правки.
LEFT = 0

# Потоки, которые уже переведены: в них литерала быть не должно вовсе.
CLEAN = (5, 32, 38, 52, 55, 56, 57, 59, 67, 72, 76, 78)


async def _steps() -> list[dict]:
    """Шаги, у которых в карте входов стоит литерал.

    ⚠ Импорт базы внутри функции, как у соседних тестов: модульный привязывает
    пул к чужому циклу событий, и прогон падает «attached to a different loop».
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT s.id, s.workflow_id, s.title, s.metadata'
            '  FROM agent_workflow_step s'
            " WHERE s.metadata LIKE '%%_const_%%'")
        rows = [dict(r) for r in (await db.fetchall() or [])]

    got = []
    for row in rows:
        meta = json.loads(row['metadata'])
        invoke = meta.get('tool_invoke') or {}
        for arg, value in (invoke.get('inputs_map') or {}).items():
            if isinstance(value, str) and value.startswith(PREFIX):
                got.append({**row, 'arg': arg, 'value': value})

    return got


class TestTheLiteralOnlyShrinks:
    """Их число не растёт, а переведённые потоки остаются чистыми."""

    async def test_no_new_literals(self):
        got = await _steps()

        assert len(got) <= LEFT, (
            f'литералов стало {len(got)} при потолке {LEFT}: новое значение '
            'задано в метаданных шага, а не переменной потока — у него нет ни '
            'имени, ни подписи, и правится оно вслепую')

    async def test_the_ceiling_is_not_stale(self):
        """⚠ Перевёл потребителя — опусти потолок. Иначе он перестаёт стеречь:
        место, освобождённое переводом, молча займёт новый литерал."""
        got = await _steps()

        assert len(got) >= LEFT, (
            f'литералов осталось {len(got)}, а потолок всё ещё {LEFT} — '
            f'опустите `LEFT` до {len(got)}')

    async def test_translated_workflows_stay_clean(self):
        """⚠⚠ Возврат литерала в переведённый поток — именно та беда, ради
        которой сторож и заведён: правка пришла бы обратно незамеченной."""
        back = [one for one in await _steps() if one['workflow_id'] in CLEAN]

        assert not back, (
            'литерал вернулся в переведённый поток: '
            + ', '.join(f"#{one['id']} wf{one['workflow_id']} "
                        f"{one['title']} ({one['arg']})" for one in back))

    async def test_the_dice_specs_are_declared_variables(self):
        """⚠ Доли жребия правит человек, и правит их чаще всего остального:
        это единственное место, где задаётся разнообразие писем."""
        # ⚠ Отбираем текстом, а не `JSON_EXTRACT`: у части шагов метаданные
        # пусты, и разбор падает отказом MySQL раньше, чем дойдёт до дела.
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT s.id, s.title, s.metadata FROM agent_workflow_step s'
                ' WHERE s.metadata LIKE \'%%"tool_name": "dice%%\'')
            rows = [dict(r) for r in (await db.fetchall() or [])
                    if (json.loads(r['metadata'] or '{}').get('tool_invoke')
                        or {}).get('tool_name') in ('dice', 'dice_batch')]

        assert rows, 'шагов жребия не нашлось вовсе — проверьте отбор'

        for row in rows:
            spec = ((json.loads(row['metadata']).get('tool_invoke') or {})
                    .get('inputs_map') or {}).get('spec', '')

            assert not spec.startswith(PREFIX), (
                f"#{row['id']} «{row['title']}»: описание жребия спрятано в "
                'метаданных шага — перенесите его в переменную потока')


class TestTheTimeoutCardStillSees:
    """⚠⚠ Карточка команды переживает перевод срока в переменную.

    Это главный риск перевода, и он молчаливый: `task_setting_step_timeout_of`
    читает срок **из метаданных шага**, мимо движка. Переведи мы значение в
    переменную, не научив его, — карточка вернула бы ноль, строка со шага
    пропала бы со страницы, и человек правил бы настройку
    `timeout_shell_call`, которая этот шаг не трогает вовсе. Ровно та беда,
    ради которой `task_setting_step` когда-то и завели.
    """

    def test_both_forms_are_understood(self):
        from src.project.task.task_setting_step import \
            task_setting_step_timeout_of as timeout_of

        def step(value):
            return {'tool_invoke': {'tool_name': 'claude_shell_call',
                                    'inputs_map': {'timeout': value}}}

        assert timeout_of(step('_const_600')) == 600, 'литерал разучились читать'
        assert timeout_of(step('timeout_plan_sec'),
                          {'timeout_plan_sec': '2400'}) == 2400

    def test_a_missing_variable_is_zero_not_a_guess(self):
        """⚠ Переменной нет — отвечаем нулём, то есть «своего срока нет»: так же
        поступит инструмент, подставив настройку. Выдуманное число разошлось бы
        с тем, что произойдёт на самом деле."""
        from src.project.task.task_setting_step import \
            task_setting_step_timeout_of as timeout_of

        got = timeout_of({'tool_invoke': {'tool_name': 'claude_shell_call',
                                          'inputs_map': {'timeout': 'no_such'}}},
                         {})

        assert got == 0

    async def test_every_translated_step_still_has_a_number(self):
        """⚠⚠ Сторож на сам перевод: шаг, ссылающийся на переменную, которой
        нет, пропал бы с карточки — и срок правили бы вслепую."""
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT s.id, s.workflow_id, s.title, s.metadata'
                '  FROM agent_workflow_step s'
                ' WHERE s.workflow_id IN (55, 56, 57, 59)')
            steps = [dict(r) for r in (await db.fetchall() or [])]

            await db.execute(
                'SELECT workflow_id, name, `default`'
                '  FROM agent_workflow_variable'
                ' WHERE workflow_id IN (55, 56, 57, 59)')
            variables: dict = {}
            for row in (await db.fetchall() or []):
                variables.setdefault(int(row['workflow_id']), {})[
                    str(row['name'])] = row['default']

        from src.project.task.task_setting_step import \
            task_setting_step_timeout_of as timeout_of

        blind = []
        for step in steps:
            meta = json.loads(step['metadata'] or '{}')
            if (meta.get('tool_invoke') or {}).get('tool_name') != 'claude_shell_call':
                continue
            if not timeout_of(meta, variables.get(int(step['workflow_id']), {})):
                blind.append(f"#{step['id']} wf{step['workflow_id']} {step['title']}")

        assert not blind, (
            'у этих шагов срок не читается — они пропадут с карточки команды: '
            + ', '.join(blind))


class TestTheEngineRefuses:
    """⚠⚠ Движок отвечает на литерал **отказом**, а не молчаливой подстановкой.

    Проверяется чтением кода, а не прогоном: поднять движок ради одного шага
    дорого, а ветка здесь одна и видна. Цена ошибки при этом высока — вернись
    подстановка, значение снова уехало бы в метаданные, и заметили бы это
    через недели, по невозможности поправить долю жребия.
    """

    def test_the_branch_raises(self):
        """⚠⚠ Движок отвечает на литерал отказом, а не подстановкой.

        Переезд кончен: первый заход научил читать оба вида, второй перевёл
        данные в прод-базе (47 доводов, после него литералов там ноль), этот —
        третий. Вернись подстановка, значение снова уехало бы в метаданные, и
        заметили бы это через недели — по невозможности поправить долю жребия.
        """
        import inspect

        from src.ai.framework.agent import ai_framework_manager as engine

        code = inspect.getsource(engine)
        spot = code.find('AI_FRAMEWORK_CONST_PREFIX)')
        after = code[spot:spot + 1600]

        assert 'raise ValueError' in after, (
            'движок снова подставляет литерал вместо отказа: значение уедет '
            'в метаданные шага и станет неправимым с виду')

    def test_the_prefix_is_still_known(self):
        """⚠ Приставка остаётся в коде **ради отказа**: без неё шаг молча
        передал бы инструменту строку `_const_600` как имя переменной, получил
        `None` и повёл себя непредсказуемо."""
        from src.ai.framework.agent.ai_framework_manager import \
            AI_FRAMEWORK_CONST_PREFIX

        assert AI_FRAMEWORK_CONST_PREFIX == '_const_'


class TestNoExtraToolArguments:
    """⚠⚠ Шаг не передаёт инструменту доводов, которых у того нет.

    Лишний ключ из карты входов **не отбрасывается**: он едет в вызов
    (`ai_tool_args_prepare`, оговорка о сигнатуре), и инструмент падает на
    `unexpected keyword argument`. Поймано чтением 30.10.2026 у шага 348
    `planning_widget_gen_block`: он передавал `content`, которого
    `planning_block_ai_update` не принимает.

    ⚠ Прогоном такое не ловится: у того потока трасс **ноль** — он ни разу не
    запускался. Беда ждала бы первого запуска, и объяснялась бы он уже не
    опечаткой в карте входов, а «планировщик не работает».
    """

    async def test_every_step_matches_its_tool(self):
        import inspect
        import importlib.util
        import pathlib

        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute('SELECT name, path FROM tool')
            paths = {str(r['name']): str(r['path'] or '')
                     for r in (await db.fetchall() or [])}

            await db.execute(
                'SELECT s.id, s.workflow_id, s.title, s.metadata'
                '  FROM agent_workflow_step s'
                " WHERE s.metadata LIKE '%%tool_invoke%%'")
            steps = [dict(r) for r in (await db.fetchall() or [])]

        root = pathlib.Path(__file__).resolve().parents[1]
        extra, skipped, looked = [], [], 0

        for step in steps:
            invoke = (json.loads(step['metadata'] or '{}').get('tool_invoke') or {})
            name = str(invoke.get('tool_name') or '')
            args = set(invoke.get('inputs_map') or {})
            path = paths.get(name, '')

            if not name or not args or not path:
                continue

            # ⚠⚠ Путь в реестре — абсолютный **внутри контейнера**
            # (`/app/src/tool/...`), а сторож гоняют с хоста. `root / path`
            # на абсолютном пути отбрасывает левую часть, файл «не находится»,
            # и сторож молча пропускает все шаги до единого — поймано его же
            # проверкой подделкой.
            file = root / path.split('/app/', 1)[-1].lstrip('/')
            if not file.is_file():
                skipped.append(f"{name}: нет файла {path}")
                continue

            # ⚠ Сигнатуру читаем разбором файла, а не импортом: импорт тянет
            # зависимости инструмента, а их у полусотни модулей разные, и
            # сторож падал бы на чужом окружении, а не на деле.
            try:
                tree = compile(file.read_text(encoding='utf-8'), str(file), 'exec',
                               flags=__import__('ast').PyCF_ONLY_AST)
            except SyntaxError:
                continue

            ast = __import__('ast')
            func = next((node for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and node.name == name), None)
            if func is None:
                continue

            # `**kwargs` принимает что угодно — к такому претензий нет.
            if func.args.kwarg:
                continue

            looked += 1

            known = {a.arg for a in
                     (func.args.args + func.args.posonlyargs + func.args.kwonlyargs)}
            odd = args - known
            if odd:
                extra.append(f"#{step['id']} wf{step['workflow_id']} "
                             f"«{step['title']}» → {name}: "
                             + ', '.join(sorted(odd)))

        # ⚠ Сторож, который ничего не посмотрел, зелен по ошибке: именно так
        # он и молчал, пока путь из реестра не разбирался.
        # ⚠⚠ Сторож, который ничего не посмотрел, зелен по ошибке — именно
        # так он и молчал, пока путь из реестра не разбирался: тот абсолютный
        # внутри контейнера (`/app/src/...`), и `root / path` отбрасывал левую
        # часть. Замер 30.10.2026: сверяется 197 шагов из 227 (у десяти нет
        # доводов, у двадцати инструмент не найден в реестре).
        assert looked > 150, (
            f'сверено всего {looked} шагов — сторож почти ничего не смотрит; '
            f'не нашлось файлов: {len(skipped)}')

        assert not extra, (
            'эти шаги передают инструменту доводы, которых он не принимает — '
            'вызов упадёт на `unexpected keyword argument`:\n  '
            + '\n  '.join(extra))


class TestEveryStepHasItsTool:
    """⚠⚠ Шаг зовёт инструмент, которого нет в реестре, — прогон падает сразу.

    Движок отвечает `ValueError: Инструмент не найден в доступных инструментах
    агента` и обрывает заход. Поймано 30.10.2026: двадцать шагов тринадцати
    потоков звали десять инструментов, которых нет ни в реестре, ни в коде.

    ## ⚠⚠ Почему это дожило до сегодня

    Шаги живут **в базе**, а не в коде. Переименование инструментов
    (коммит `9f7198a`, 26.08.2026: префиксы `design_`, `planning_prototype_`,
    `tables_`) прошло мимо них: `git grep` их не видит, тесты не трогают, а
    всплыло бы только на прогоне — которого у этих потоков не было ни одного.

    Двадцать один шаг исправлен 30.10.2026 — все, у кого нашёлся наследник:

    | Было | Стало | Шагов |
    |------|-------|-------|
    | `planning_document_save` | `planning_phase_document_save` | 5 |
    | `planning_document_section_save` | `planning_phase_document_section_save` | 4 |
    | `planning_image_save` | `planning_prototype_image_save` | 2 |
    | `planning_planning_project_list` | `planning_project_list` | 2 |
    | `list_render` | `list_implode` | 3 |
    | `planning_blocks_component_map`, `planning_sitemap_check`, `planning_project_delete`, `planning_project_meta_save` | свои наследники | 4 |
    | `session_messages_render` | шаг убран: работу встроили в `session_messages` | 1 |

    Сирот не осталось. Последние два жили в потоке `mysql_export_tables`,
    чей механизм упразднён целиком (`77819db`, 27.08.2026: «Данные едут
    миграциями, `data/migration_manual` упразднена»); поток снесён вместе с
    агентом `mysql_export` — трасс у него было ноль, жёстких ссылок тоже.

    ⚠ Сторож смотрит **все** шаги с `tool_invoke`, включая те, у которых карта
    входов пуста: соседний `TestNoExtraToolArguments` их пропускает (сверять
    нечего), и три поломки прятались именно там.
    """

    # Шаги, у которых инструмента нет и замена неизвестна. ⚠ Список **только
    # убывает**: починил — вычеркни. Он же показывает, что именно осталось.
    # ⚠ Пусто, и это состояние надо держать: шаг, зовущий несуществующий
    # инструмент, падает на первом же прогоне. Появился такой — либо найди
    # наследника (переименование видно в коммите), либо впиши сюда с
    # объяснением, почему он пока жив.
    ORPHANS: dict[int, str] = {}

    async def test_no_new_steps_call_a_missing_tool(self):
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute('SELECT name FROM tool')
            live = {str(r['name']) for r in (await db.fetchall() or [])}

            await db.execute(
                'SELECT s.id, s.workflow_id, s.title, s.metadata'
                '  FROM agent_workflow_step s'
                " WHERE s.metadata LIKE '%%tool_invoke%%'")
            steps = [dict(r) for r in (await db.fetchall() or [])]

        missing = {}
        for step in steps:
            name = str((json.loads(step['metadata'] or '{}').get('tool_invoke')
                        or {}).get('tool_name') or '')
            if name and name not in live:
                missing[int(step['id'])] = name

        fresh = {sid: name for sid, name in missing.items()
                 if sid not in self.ORPHANS}

        assert not fresh, (
            'эти шаги зовут инструмент, которого нет в реестре — заход упадёт '
            'на первом же прогоне:\n  '
            + '\n  '.join(f'#{sid} → {name}' for sid, name in sorted(fresh.items())))

    async def test_the_orphan_list_is_not_stale(self):
        """⚠ Починил шаг — вычеркни его из списка. Иначе список перестаёт
        показывать, что осталось, и в освободившееся место молча встанет
        новая такая же поломка."""
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute('SELECT name FROM tool')
            live = {str(r['name']) for r in (await db.fetchall() or [])}

            await db.execute(
                'SELECT s.id, s.metadata FROM agent_workflow_step s'
                " WHERE s.metadata LIKE '%%tool_invoke%%'")
            steps = [dict(r) for r in (await db.fetchall() or [])]

        still = set()
        for step in steps:
            name = str((json.loads(step['metadata'] or '{}').get('tool_invoke')
                        or {}).get('tool_name') or '')
            if name and name not in live:
                still.add(int(step['id']))

        healed = set(self.ORPHANS) - still

        assert not healed, (
            'эти шаги уже починены — вычеркните их из `ORPHANS`: '
            + ', '.join(f'#{sid}' for sid in sorted(healed)))
