"""Мост «обмен → прогон»: у ответа во вкладке «Чат» есть ссылка на trace.

## ⚠⚠ Что здесь стережётся

`companion_session.request_uuid` — ключ того вызова движка, который сочинил
ответ. Им вкладка «Чат» отвечает на вопрос «каким прогоном это написано»:
роутер по ключу находит верхний прогон и отдаёт его `run_uuid`, страница
ставит чип «⚙ trace», а чип ведёт на `/admin/workflow_trace?run=<uuid>`.

Мост завёлся не на пустом месте: колонка существовала, но не заполнялась
никем. Поэтому у связки три конца, и каждый здесь под сторожем:

1. **Запись.** Штамп ставит движок в момент, когда `companion_session_add`
   вернул номер строки, — единственное место, где прогон и строка известны
   одновременно (инструмент про прогон не знает, `request_uuid` в переменные
   workflow не попадает). Правку workflow для этого не заводили намеренно.
2. **Чтение.** Скалярный подзапрос роутера: `depth = 0` (прогон под-сюжета
   ответ не сочинял) и `ORDER BY id LIMIT 1` при повторном прогоне с тем же
   ключом — иначе лента дублировала бы обмен.
3. **Дорога наружу.** Чип рисуют только у обмена с ответом (или с убранным
   ответом): «тишина» тоже штампует строку, но ссылаться в ней не на что.

⚠ Тесты чистые там, где можно: движковый прогон стоит вызова модели, общей
с продом, — связь движка стережётся разбором исходника, по образцу
`test_companion_session_message_id.py`. Запись в таблицу и подзапрос роутера
проверяются базой.
"""
import ast
import re
import uuid as uuidlib
from pathlib import Path

import pytest

from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

from src.mysql_.repository.companion_session_repository import \
    CompanionSessionRepository
from src.tool.companion.companion_session import companion_session_add
from src.uvicorn.routers.session.session_companion import \
    (SessionCompanionMessagesRequest, session_companion_messages)

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parent.parent
ENGINE_FILE = ROOT / 'src/ai/framework/agent/ai_framework_manager.py'
CHAT_JS = ROOT / 'data/uvicorn/public/js/session/chat.js'
TRACE_PAGE = ROOT / 'data/uvicorn/template/admin/workflow_trace.html'


def _migration_file() -> Path:
    """Файл моста ищется по хвосту имени: метка — метка времени."""
    found = sorted((ROOT / 'migrations').glob('*_trace_request_bridge.sql'))
    assert found, 'миграция моста «обмен → прогон» пропала из migrations/'
    return found[0]


# ── Сюда пишет только движок ──────────────────────────────────────────────────

class TestEngineStampIsThere:
    """Штамп `request_uuid` стоит в движке и берёт ключ у модели, не из базы.

    ⚠ Разбором исходника, а не прогоном: довести вызов до инструмента можно
    только прогоном workflow с живой моделью, — правило объявлено в
    `test_chat_variables_allowed.py`. Ломается связь молча (прогон без ссылки
    выглядит как прогон с ссылкой), потому сторож статический.
    """

    def _steps_run_body(self) -> tuple[str, ast.AST]:
        """Исходник движка и узел `_workflow_steps_run` из ЕГО дерева.

        ⚠ Один разбор на файл: `get_source_segment` над уже вырезанным
        куском режет смещения — смещения узлов говорят на языке всего файла.
        """
        source = ENGINE_FILE.read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and node.name == '_workflow_steps_run'):
                return source, node
        raise AssertionError('`_workflow_steps_run` не найден в движке')

    def test_stamp_shares_site_with_session_tool_capture(self):
        """Штамп стоит в том же `if`, что перехват ответ инструмента.

        ⚠ Это не косметика: ветка «тишина» идёт тем же `if`-ом по тому же
        имени инструмента, — разойдутся места, и строки тишины останутся без
        ключа, а вместе с ними замолчит и половина журнала.
        """
        source, steps_run = self._steps_run_body()
        guarded = [ast.get_source_segment(source, node)
                   for node in ast.walk(steps_run)
                   if isinstance(node, ast.If)
                   and 'AI_FRAMEWORK_SESSION_TOOL' in (
                       ast.get_source_segment(source, node.test) or '')]
        assert guarded, 'перехват `companion_session_add` в движке пропал'
        assert any('request_uuid' in seg and 'CompanionSessionRepository' in seg
                   for seg in guarded), \
            'штамп `request_uuid` уехал из перехвата: строки тишины снова без ключа'

    def test_stamp_takes_key_from_model_not_from_workflow(self):
        """Ключ берётся из `model.request_uuid`, а не из переменной workflow."""
        assert re.search(r"\{\s*['\"]request_uuid['\"]:\s*model\.request_uuid\s*\}",
                         ENGINE_FILE.read_text(encoding='utf-8')), \
            'ключ берётся не из модели — переменная может оказаться чужой'

    def test_stamp_swallows_failure(self):
        """Сбой моста не роняет прогон: запись обёрнута в `try`."""
        source, steps_run = self._steps_run_body()
        stamps = [node for node in ast.walk(steps_run)
                  if isinstance(node, ast.Try)
                  and 'CompanionSessionRepository' in ast.dump(node)]
        assert stamps and all(node.handlers for node in stamps), \
            'штамп без обработки сбоя: база ответит отказом — упадёт прогон'

    def test_tool_layer_does_not_write_the_bridge(self):
        """Инструменты про `request_uuid` обмена не знают — иначе вторая точка записи.

        ⚠ `src/tool/session/session_.py` рядом не тот мост: он про
        `agent_session`, там ключ пишет сам движок с 2026 года.
        """
        for py in (ROOT / 'src/tool/companion').glob('*.py'):
            assert 'request_uuid' not in py.read_text(encoding='utf-8'), \
                f'{py.name} пишет мост в обход движка'


# ── Чтение: подзапрос роутера ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого свой."""
    yield
    await mysql_pool_close()


@pytest.fixture
async def pair():
    """Пара ключей и уборка за собой: обмены, прогон-строки, сами ключи."""
    mark = uuidlib.uuid4().hex[:8]
    keys = (f'comp_own_{mark}', f'comp_him_{mark}')
    run_uuids: list[str] = []

    yield keys, run_uuids

    async with mysql_get_db_async() as db:
        await db.execute('DELETE s FROM `companion_session` s'
                         ' JOIN `companion` c ON c.`id` = s.`owner_id`'
                         ' WHERE c.`unique_id` = %s', (keys[0],))
        if run_uuids:
            await db.execute('DELETE FROM `agent_workflow_trace`'
                             ' WHERE `run_uuid` IN ({})'
                             .format(', '.join(['%s'] * len(run_uuids))),
                             tuple(run_uuids))
        await db.execute('DELETE FROM `companion` WHERE `unique_id` IN (%s, %s)',
                         keys)
        await db.connection.commit()


async def _ids(keys) -> tuple[int, int]:
    """Числовые id пары — их ждёт ручка ленты."""
    async with mysql_get_db_async() as db:
        out = []
        for key in keys:
            await db.execute('SELECT `id` FROM `companion` WHERE `unique_id` = %s',
                             (key,))
            out.append((await db.fetchone())['id'])
    return out[0], out[1]


async def _add_trace(run_uuid: str, request_uuid: str, depth: int = 0,
                     response_json: str | None = None):
    """Строка журнала с ключом вызова; в тестовых прогонах всё остальное — лишнее."""
    async with mysql_get_db_async() as db:
        await db.execute('INSERT INTO `agent_workflow_trace`'
                         ' (`run_uuid`, `depth`, `request_uuid`, `status`, `response_json`)'
                         ' VALUES (%s, %s, %s, %s, %s)',
                         (run_uuid, depth, request_uuid, 'success', response_json))


async def _link_of(keys, exchange_id: int):
    """`trace_run_uuid` нужной строки из ответа ручки ленты."""
    owner_id, companion_id = await _ids(keys)
    res = await session_companion_messages(
        request=None,
        json_request=SessionCompanionMessagesRequest(
            owner_id=owner_id, companion_id=companion_id, kind='', limit=50),
        db=mysql_get_db_async())
    row = next(r for r in res['result'] if r['id'] == exchange_id)
    return row.get('trace_run_uuid')


async def _exchange(keys, answer='hello') -> int:
    made = await companion_session_add(keys[0], keys[1],
                                       question='hi', answer=answer)
    return int(made['id'])


class TestLinkRead:
    async def test_keyed_exchange_links_to_top_run(self, pair):
        """Обмен с ключом получает ссылку на верхний прогон этого ключа."""
        keys, run_uuids = pair
        exchange_id = await _exchange(keys)
        request_uuid = str(uuidlib.uuid4())
        run_uuid = str(uuidlib.uuid4())
        await CompanionSessionRepository().update(exchange_id,
                                                  {'request_uuid': request_uuid})
        await _add_trace(run_uuid, request_uuid)
        run_uuids.append(run_uuid)

        assert await _link_of(keys, exchange_id) == run_uuid

    async def test_keyless_exchange_has_no_link(self, pair):
        """Без ключа ссылки нет: выдумывать прогон по времени — путь к чужому.

        ⚠ Так выглядят привезённые дверью `/chat/message/add` строки и ответы
        до контракта прогона (13.10.2026) — честное «не знаю» вернее догадки.
        """
        keys, _ = pair
        exchange_id = await _exchange(keys)

        assert not await _link_of(keys, exchange_id)

    async def test_subflow_never_wins(self, pair):
        """Прогон под-сюжета (depth > 0) ссылкой не считается, даже попав в выборку первым."""
        keys, run_uuids = pair
        exchange_id = await _exchange(keys)
        request_uuid = str(uuidlib.uuid4())
        await CompanionSessionRepository().update(exchange_id,
                                                  {'request_uuid': request_uuid})
        child, top = str(uuidlib.uuid4()), str(uuidlib.uuid4())
        await _add_trace(child, request_uuid, depth=1)   # раньше по id
        await _add_trace(top, request_uuid, depth=0)
        run_uuids += [child, top]

        assert await _link_of(keys, exchange_id) == top

    async def test_duplicate_key_takes_first_run(self, pair):
        """Два верхних прогона на один ключ — берётся первый, и это стабильно.

        ⚠ Без `ORDER BY id LIMIT 1` ссылка гуляла бы между прогонами от
        запроса к запросу, а строка ленты дублировалась бы `JOIN`-ом.
        """
        keys, run_uuids = pair
        exchange_id = await _exchange(keys)
        request_uuid = str(uuidlib.uuid4())
        await CompanionSessionRepository().update(exchange_id,
                                                  {'request_uuid': request_uuid})
        first, second = str(uuidlib.uuid4()), str(uuidlib.uuid4())
        await _add_trace(first, request_uuid)
        await _add_trace(second, request_uuid)
        run_uuids += [first, second]

        assert await _link_of(keys, exchange_id) == first


# ── Миграция: донастройка старых строк ───────────────────────────────────────

def _backfill_statement() -> str:
    """`UPDATE` из файла миграции — тот же текст, а не копия."""
    text = _migration_file().read_text(encoding='utf-8')
    match = re.search(r"(UPDATE `companion_session`.*?WHERE `s`\.`request_uuid` = '';)",
                      text, re.S)
    assert match, 'UPDATE-донастройка не найдена в файле миграции'
    return match.group(1)


class TestBackfill:
    """Старые строки цепляются к прогонам по `message_id` из контракта ответа.

    ⚠ Проверяется текст миграции, а не только факт её применения: на прод она
    уедет именно этим текстом, а качество донастройки на местной базе не
    проверить — прогонов с контрактом тут обрезано больше, чем осталось.
    """

    def test_statement_guards_bad_json(self):
        """`JSON_EXTRACT` обёрнут в проверку: не-JSON в `response_json` не роняет UPDATE.

        ⚠ Колонка `longtext`, а не `JSON`: там лежит всё, что роутер писал до
        контракта, а `AND` в MySQL короткое замыкание не обещает.
        """
        statement = _backfill_statement()
        assert 'JSON_VALID' in statement and 'CASE' in statement

    def test_statement_is_idempotent(self):
        """Вторая волна ничего не трогает: `WHERE` отбирает только пустые ключи."""
        assert "`s`.`request_uuid` = ''" in _backfill_statement()

    def test_statement_does_not_filter_answers(self):
        """Фильтра «у строки есть ответ» в донастройке нет — как и в штампе движка.

        ⚠ Разошлись бы — живые прогоны штамповали бы ответы, а донастройка
        только их, и «тишина» в ленте осталась бы без ключа навсегда.
        """
        assert '`answer`' not in _backfill_statement()

    async def test_backfill_links_row_and_survives_rerun(self, pair):
        """Строка без ключа получает его из контракта прогона; повтор — пусто."""
        keys, run_uuids = pair
        exchange_id = await _exchange(keys)
        request_uuid, run_uuid = str(uuidlib.uuid4()), str(uuidlib.uuid4())
        async with mysql_get_db_async() as db:
            await db.execute(
                'INSERT INTO `agent_workflow_trace`'
                ' (`run_uuid`, `depth`, `request_uuid`, `status`, `response_json`)'
                ' VALUES (%s, 0, %s, %s, %s)',
                (run_uuid, request_uuid, 'success',
                 f'{{"result": "hi", "message_id": {exchange_id}}}'))
            # Сосед с битым JSON: одна такая строка не должна испортить весь прогон.
            broken_run = str(uuidlib.uuid4())
            await db.execute(
                'INSERT INTO `agent_workflow_trace`'
                ' (`run_uuid`, `depth`, `request_uuid`, `status`, `response_json`)'
                ' VALUES (%s, 0, %s, %s, %s)',
                (broken_run, request_uuid, 'success', 'не json вовсе'))
            run_uuids += [run_uuid, broken_run]

            await db.execute(_backfill_statement())
            await db.execute('SELECT `request_uuid` FROM `companion_session`'
                             ' WHERE `id` = %s', (exchange_id,))
            assert (await db.fetchone())['request_uuid'] == request_uuid

            affected = await db.execute(_backfill_statement())
            assert not affected, 'вторая волна донастройки что-то изменила'


# ── Дорога наружу: чип и deep-link ───────────────────────────────────────────

class TestFrontRoad:
    """Чип «⚙ trace» и приём ссылки на странице прогона.

    ⚠ Разбором строк, а не браузером: здесь важен сам факт связи полей —
    `trace_run_uuid` из ручки в `href` и `?run=` обратно в детали прогона.
    Как чип выглядит — приёмка кадром, `frontend_check_rules.md`.
    """

    def test_chip_wired_to_field_and_gate(self):
        """Чип рисуется из `trace_run_uuid` и только у обмена с (убранным) ответом."""
        js = CHAT_JS.read_text(encoding='utf-8')
        assert 'row.trace_run_uuid' in js, 'чип не читает поле ручки'
        assert re.search(r'answered \|\| row\.answer_deleted_at', js), \
            'гейт по ответу пропал: «тишина» обзаведётся ссылкой в никуда'
        assert re.search(r'href="/admin/workflow_trace\?run=\$\{htmlEscape\(row\.trace_run_uuid\)\}"', js), \
            'href чипа больше не везёт `run_uuid` экранированным'

    def test_trace_page_accepts_the_link(self):
        """Страница прогона читает `?run=` и открывает детали до автоклика ленты."""
        page = TRACE_PAGE.read_text(encoding='utf-8')
        assert "URLSearchParams(location.search).get('run')" in page
        assert re.search(r'if \(deepRunUuid\) state\.activeRunUuid = deepRunUuid', page), \
            'ключ не кладётся в `activeRunUuid` — автоклик первой карточки собьёт детали'
        assert 'e.message ||' in page, \
            'битая ссылка прячет «не найдено» за «ошибкой загрузки»'

class TestCollationAligned:
    """Сравнение ключа исполнимо в любой среде: коллация колонки выровнена.

    ⚠⚠ На проде `agent_workflow_trace.request_uuid` достался таблице с
    серверной коллацией (начальная схема завела её без `COLLATE`), и первое же
    сравнение колонка-с-колонкой роняло вкладку «Чат» ошибкой 1267. На деве тот
    же код молчит — разницу видно только сторожем, а не прогоном здесь.
    """

    def test_migration_levels_the_column(self):
        """Миграция выравнивает колонку по проекту и не блокирует горячий журнал."""
        found = sorted((ROOT / 'migrations').glob('*_trace_request_uuid_collation.sql'))
        assert found, 'миграция выравнивания коллации ключа пропала из migrations/'
        sql = found[0].read_text(encoding='utf-8').lower()
        assert 'agent_workflow_trace' in sql and 'collate utf8mb4_general_ci' in sql, \
            'миграция больше не ровняет колонку ключа к общей проекту коллации'
        assert 'information_schema' in sql, \
            'миграция потеряла сторожа: на ровной установке она обязана пропускать ALTER'
        assert 'algorithm=inplace' not in sql and 'algorithm=copy' in sql, \
            'смена коллации не бывает INPLACE (1846) — ALTER встанет на старте слота'

    def test_query_compares_bare_columns(self):
        """Роутер сравнивает колонки голо — выравнивание живёт в схеме, не в `COLLATE`-костыле.

        ⚠ Костыль в запросе спасал бы одну страницу, но с убитым индексом
        трасс (сравнение не в коллации индекса — индекс не используется), а
        следующая связка этих таблиц наступила бы на то же.
        """
        py = (ROOT / 'src/uvicorn/routers/session/session_companion.py').read_text(encoding='utf-8')
        assert 'COLLATE' not in py.upper(), \
            'COLLATE в роутере — значит выравнивание уехало из схемы в запрос'

    async def test_comparison_runs_here(self):
        """То самое сравнение, что роняло прод, на этой установке исполнима.

        ⚠ Если среда разошлась (миграция не накатана), здесь прилетит 1267 —
        тест укажет прямо на причину, а не «Внутренняя ошибка сервера».
        """
        async with mysql_get_db_async() as db:
            await db.execute('SELECT COUNT(*) AS c FROM `companion_session` `s`'
                             ' WHERE EXISTS (SELECT 1 FROM `agent_workflow_trace` `t`'
                             '                WHERE `t`.`request_uuid` = `s`.`request_uuid`'
                             '                  AND `t`.`depth` = 0)')
            assert (await db.fetchone())['c'] >= 0
