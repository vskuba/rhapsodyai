import uuid

from datetime import datetime
from chromadb import QueryResult
from source.ai.tool.ai_tool_agent import agent_invoke
from source.chroma_db import _chroma_db_get_client
from source.logging_ import logger_info

chroma_db_collection_name = 'bank_memory'

async def chromadb_memory_save(text: str):
    """This tool converts the input text into a high-dimensional vector embedding and stores
    it in the ChromaDB collection. This allows for persistent long-term memory, enabling the
    agent to perform semantic searches and retrieve relevant context in future interactions."""
    client = _chroma_db_get_client()
    collection = client.get_or_create_collection(chroma_db_collection_name)
    facts = await _chromadb_extract_facts_from_text(text)

    logger_info(f'🔍 Extracted facts from input text: {facts}')

    if not facts:
        return "No important facts found to save."

    saved_count = 0
    for fact in facts:
        existing = await _chromadb_memory_search(fact)

        # Если в результатах есть очень похожий текст (distance < 0.1) - пропускаем
        if existing and existing.get('distances') and len(existing['distances'][0]) > 0:
            distance = existing['distances'][0][0]
            if distance < 0.15:
                logger_info(f"⏭️ Факт '{fact}' уже известен (схожесть {distance:.4f}), пропускаю.")
                continue

        unique_id = f"fact_{uuid.uuid4().hex[:8]}"

        # 2. Сохраняем каждый факт как отдельный документ
        collection.add(
            documents=[fact],
            metadatas=[{
                "source": "extracted_fact",
                "created_at": datetime.now().isoformat(),
                "original_size": len(text)
            }],
            ids=[unique_id]
        )
        saved_count += 1

    return f"Extracted and saved {saved_count} facts."


async def chromadb_memory_search_text(query: str) -> str:
    """Performs a semantic similarity search within the ChromaDB collection to retrieve relevant
    context or past information. It converts the query into an embedding and returns the most
    closely related documents, effectively providing the agent with access to its long-term memory
    and previously stored knowledge."""
    results = await _chromadb_memory_search(query)
    if results and results['documents'] and len(results['documents'][0]) > 0:
        # Склеиваем найденные документы в одну строку
        return "\n".join(results['documents'][0])

    return "No relevant memories found."


async def _chromadb_memory_search(query: str) -> QueryResult:
    """Performs a semantic similarity search within the ChromaDB collection to retrieve relevant
    context or past information. It converts the query into an embedding and returns the most
    closely related documents, effectively providing the agent with access to its long-term memory
    and previously stored knowledge."""
    client = _chroma_db_get_client()
    results = client.get_or_create_collection(chroma_db_collection_name).query(
        query_texts=[query],
        n_results=3
    )

    return results


async def _chromadb_extract_facts_from_text(text: str) -> list[str]:
    """
    Extract facts from text using AI.
    """
    prompt = f"""
        Analyze the input text and extract all significant facts about the user, their preferences, or specific events.
        Convert them into a list of short, concise, and complete statements.
        Remove greetings, questions, and unnecessary reasoning.
        
        Input text:
        "{text}"
        
        Provide the response in the following format:
        - Fact 1
        - Fact 2
        """

    try:
        response = await agent_invoke(agent_name="thinker", prompt=prompt)

        if not response:
            return []

        # Парсим ответ: разбиваем по строкам, убираем маркеры списка и пустые строки
        facts = [
            line.strip("- *•").strip()
            for line in response.split('\n')
            if len(line.strip()) > 5  # Игнорируем слишком короткие обрывки
        ]

        return facts

    except Exception as e:
        logger_info(f"❌ Ошибка при экстракции фактов: {e}")
        return []
