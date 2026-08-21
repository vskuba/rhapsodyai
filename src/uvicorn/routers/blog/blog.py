"""Агенты «Блокнота» для BlogAi: разметка черновиков тегами.

Черновики живут в BlogAi, агенты — здесь, под нодой `Blog`. Точка своя, а не
общий `/chat/ask`, по той же причине, что и у STT: соседу незачем знать про
workflow, session_uuid и идентификаторы агентов. Он присылает текст и словарь
тегов, получает теги.

**Словарь — не подсказка, а условие работы.** Без него агент размечает каждый
черновик независимо, и через сотню записей получаются «бизнес», «про бизнес»,
«бизнес-идеи» и «business» — четыре полки вместо одной. Поэтому словарь идёт в
промпт, а агенту велено переиспользовать существующее.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import (ai_workflow_load, ai_workflow_variables_base,
                                ai_workflow_variables_defaults_apply)
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from qdrant_.qdrant_ import (EMBEDDING_MODEL, _qdrant_db_get_client, qdrant_remove_by,
                             qdrant_save)

from src.mysql_.repository.agent_repository import AgentRepository

router = APIRouter(prefix="/api/blog", tags=["blog"])

agent_manager = AiFrameworkAgentManager()

BLOG_TAGGER_AGENT_NAME = "blog_tagger"
BLOG_WRITER_AGENT_NAME = "blog_writer"

# Коллекция Qdrant под черновики «Блокнота». Своя, а не общая с фактами: у них
# разный смысл и разная жизнь, а смешивать их значило бы находить факты в
# ответе на «покажи похожие мысли».
BLOG_COLLECTION = "blog_draft"

# Схема полей коллекции. `document` — текст, по которому считается вектор;
# `id` — идентификатор черновика в BlogAi, по нему потом и находят.
BLOG_COLLECTION_META = {
    "id": {"table_name": "draft"},
    "document": {"table_name": "draft"},
}

# Ниже этой близости считаем, что связи нет. Замер на русских парах
# (fastembed, paraphrase-multilingual-MiniLM-L12-v2): близкие по смыслу дают
# 0.46-0.59, не связанные - 0.01-0.29. Порог 0.40 лежит в этом провале.
#
# Планка нужна: без неё «похожим» всегда окажется что-нибудь, и человек
# перестанет верить подсказке.
BLOG_SIMILAR_MIN_SCORE = 0.40

# От чьего имени идёт запрос. Учётка владельца: черновики — его личные мысли,
# и разводить их по пользователям пока незачем.
#
# `companion_id` = 1 (`user_admin`), а НЕ 3 как в телеграмных константах: там
# число из другой установки, и у нас запись в `agent_session` падала на внешнем
# ключе `fk_memory_companion` — собеседника с id 3 в таблице нет.
BLOG_USER_ID = 1
BLOG_COMPANION_ID = 1

# Ждём разметку не дольше минуты. Черновик короткий, и если модель думает
# дольше — что-то не так, а BlogAi не должен висеть на этом запросе.
BLOG_AGENT_TIMEOUT = 60.0

# Сборка текста дольше разметки: модель пишет абзацы, а не подбирает слова.
BLOG_COMPOSE_TIMEOUT = 180.0

# Сколько тегов из словаря показать агенту. Весь словарь в промпт не влезет,
# когда он разрастётся, а ходовые и есть те, которые надо переиспользовать.
BLOG_VOCABULARY_MAX = 120


@router.post("/tag")
async def blog_tag(data: dict, user=Depends(AuthChecker([AuthPermission.STT_CREATE]))):
    """Текст черновика + словарь → теги и заголовок.

    Право то же, что у расшифровки: это одна и та же учётка соседа, делающая
    одну и ту же работу — превращает надиктованное в черновик. Заводить второе
    право ради второй точки того же сценария незачем.
    """
    text = str(data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="пустой текст — размечать нечего")

    vocabulary = [str(v).strip() for v in (data.get("vocabulary") or []) if str(v).strip()]
    vocabulary = vocabulary[:BLOG_VOCABULARY_MAX]

    answer = await _agent_ask(BLOG_TAGGER_AGENT_NAME, _prompt(text, vocabulary))
    parsed = json_from_string(answer) or {}

    tags = [str(t).strip() for t in (parsed.get("tags") or []) if str(t).strip()]
    if not tags:
        # Пустая разметка — это либо модель ответила не JSON, либо решила, что
        # тегов нет. Различить можно только по сырому ответу, поэтому он идёт
        # в журнал: без него такой случай не разобрать.
        logger_info(f"[blog] разметка ПУСТАЯ, сырой ответ: {answer[:300]}")
    logger_info(f"[blog] разметка: {len(text)} знаков, словарь {len(vocabulary)} → "
                f"{', '.join(tags) or 'ничего'}")

    return {"result": {"tags": tags, "title": str(parsed.get("title") or "").strip()}}


@router.post("/compose")
async def blog_compose(data: dict, user=Depends(AuthChecker([AuthPermission.STT_CREATE]))):
    """Черновики → связный текст.

    Агенту приходят пронумерованные куски, а не склеенная простыня: так он
    видит границы мыслей и не смешивает их в одну.

    Отдаём текст как есть, без разбора: тут нет структуры, которую надо
    доставать, — есть материал, который человек будет читать и править.
    """
    drafts = [str(d).strip() for d in (data.get("drafts") or []) if str(d).strip()]
    if not drafts:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="нет черновиков — собирать нечего")

    hint = str(data.get("hint") or "").strip()
    body = "\n\n".join(f"[черновик {i + 1}]\n{text}" for i, text in enumerate(drafts))
    prompt = (f"Пожелание автора: {hint}\n\n" if hint else "") + body

    text = _thinking_strip(await _agent_ask(BLOG_WRITER_AGENT_NAME, prompt))
    logger_info(f"[blog] сборка: {len(drafts)} черновиков → {len(text)} знаков")

    return {"result": {"text": text}}


@router.post("/index")
async def blog_index(data: dict, user=Depends(AuthChecker([AuthPermission.STT_CREATE]))):
    """Кладёт черновик в векторный поиск.

    Зовётся при сохранении и при правке текста: вектор считается от текста, и
    после правки старый указывал бы не туда.
    """
    draft_id = int(data.get("id") or 0)
    text = str(data.get("text") or "").strip()
    if not draft_id or not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="нужны id и text")

    saved = await qdrant_save(BLOG_COLLECTION, BLOG_COLLECTION_META,
                              [{"id": draft_id, "document": text}])
    logger_info(f"[blog] в поиск: черновик #{draft_id}, {len(text)} знаков")

    return {"result": {"saved": saved}}


@router.post("/similar")
async def blog_similar(data: dict, user=Depends(AuthChecker([AuthPermission.STT_CREATE]))):
    """Похожие по СМЫСЛУ черновики.

    Отдельно от поиска в BlogAi, и это не дублирование. Тот ищет по словам
    (FULLTEXT) и по словам же ограничен: «ценообразование на консультации» и
    «пересмотреть тарифы, почасовая оплата» — одно и то же, но общих слов нет,
    и он их не свяжет. Проверено. Здесь ищется смысл.
    """
    text = str(data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="пустой текст")

    exclude = int(data.get("exclude_id") or 0)
    limit = max(1, min(int(data.get("limit") or 5), 20))

    found = await _dense_search(text, limit + 1)

    similar = []
    for point in found:
        payload = point.payload or {}
        found_id = int(payload.get("id") or 0)
        if not found_id or found_id == exclude:
            continue
        if float(point.score) < BLOG_SIMILAR_MIN_SCORE:
            continue
        similar.append({"id": found_id, "score": round(float(point.score), 3)})
        if len(similar) >= limit:
            break

    logger_info(f"[blog] похожие на {len(text)} знаков: {len(similar)} из {len(found)}")

    return {"result": similar}


@router.post("/index/remove")
async def blog_index_remove(data: dict, user=Depends(AuthChecker([AuthPermission.STT_CREATE]))):
    """Убирает черновик из поиска — вместе с его удалением в BlogAi.

    Без этого удалённая мысль осталась бы всплывать в «похожих» указателем в
    никуда.
    """
    draft_id = int(data.get("id") or 0)
    if not draft_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="нужен id")

    await qdrant_remove_by(BLOG_COLLECTION, BLOG_COLLECTION_META, {"id": draft_id})

    return {"result": "ok"}


# ---------------------------------------------------------------------------

async def _dense_search(text: str, limit: int):
    """Поиск по косинусной близости, БЕЗ слияния с полнотекстовым.

    Общий `qdrant_search` из `py_modules` для этой задачи не годится: он сливает
    векторный и BM25-поиск через RRF (Reciprocal Rank Fusion), а оценка RRF
    отражает **ранг, а не близость**. Наступили на это сразу: запрос «квантовая
    физика элементарных частиц» получил 0.5 против черновика про тарифы —
    просто потому, что тот оказался первым в выдаче. Отсечь такое порогом
    невозможно, RRF-оценка почти не зависит от смысла.

    Здесь берётся чистая косинусная близость, и `BLOG_SIMILAR_MIN_SCORE`
    работает так, как задумано. Для фактов RRF по-прежнему уместен: там ищут по
    ключевым словам, и подмешать точное совпадение полезно.
    """
    client = _qdrant_db_get_client()
    if not await client.collection_exists(BLOG_COLLECTION):
        return []

    client.set_model(EMBEDDING_MODEL)
    # Имя вектора Qdrant складывает из имени модели — то же, что при записи.
    vector_name = client.get_vector_field_name()

    from qdrant_.qdrant_ import dense_encoder, _init_encoders
    _init_encoders()
    from qdrant_.qdrant_ import dense_encoder as encoder

    response = await client.query_points(
        collection_name=BLOG_COLLECTION,
        query=next(encoder.embed([text])).tolist(),
        using=vector_name,
        limit=limit,
        with_payload=True,
    )

    return response.points


def _thinking_strip(text: str) -> str:
    """Убирает размышления модели из ответа.

    Рассуждающие модели пишут ход мысли в `<think>…</think>` и только потом
    ответ. Обычно движок это срезает, но при обрыве по лимиту закрывающий тег
    приходит без открывающего — и в текст протекает хвост вроде «exceeded,
    let\'s stop and write the final answer now.</think>». Наступили на это на
    первом же прогоне сборки.
    """
    marker = text.rfind("</think>")

    return text[marker + len("</think>"):].strip() if marker >= 0 else text.strip()


def _prompt(text: str, vocabulary: list) -> str:
    """Промпт с словарём впереди текста.

    Словарь идёт ПЕРВЫМ намеренно: модель сильнее держит начало инструкции, а
    переиспользование существующих тегов — главное требование, а не приписка.
    """
    if vocabulary:
        head = ("Существующие теги (переиспользуй подходящие, новый заводи только "
                "если ни один не годится):\n" + ", ".join(vocabulary))
    else:
        head = "Словарь пока пуст — это первые черновики, теги задаёшь ты."

    return f"{head}\n\n=== Черновик ===\n{text}"


async def _agent_ask(agent_name: str, message: str) -> str:
    """Спрашивает агента и ждёт ответа.

    Повторяет путь `_telegram_agent_chat_ask`, но без телеграмных подробностей:
    сессия одноразовая, история не нужна — разметка не диалог.
    """
    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({"name": agent_name})
    if not entity_agent:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"агент '{agent_name}' не найден")

    workflow_id = entity_agent["workflow_id"]
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid = str(uuid.uuid4())

    variables = {
        **ai_workflow_variables_base(
            prompt_user=message, user_id=BLOG_USER_ID, entity_agent=entity_agent,
            session_uuid=session_uuid, workflow_id=workflow_id,
            companion_id=BLOG_COMPANION_ID, companion_name="user_admin",
            companion_title="admin"),
        **json_from_string(entity_agent.get("workflow_variable") or "{}"),
    }
    ai_workflow_variables_defaults_apply(variables, workflow_data["variables"])

    async with mysql_get_db_async() as db:
        await db.execute("SELECT name, path FROM tool WHERE id > 0")
        raw_tools = await db.fetchall()
    tools = {t["name"].strip(): t["path"].strip()
             for t in raw_tools if t.get("name") and t.get("path")}

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entities_llm": await ai_llm_node_get(entity_agent.get("node_id")),
        "workflow_steps": workflow_data["steps"],
        "workflow_variables": variables,
        "prompt_user": message,
        "user_id": BLOG_USER_ID,
        "companion_id": BLOG_COMPANION_ID,
        "session_uuid": session_uuid,
        "tools": tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = BLOG_COMPOSE_TIMEOUT if agent_name == BLOG_WRITER_AGENT_NAME else BLOG_AGENT_TIMEOUT
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail="агент разметки не ответил вовремя")
