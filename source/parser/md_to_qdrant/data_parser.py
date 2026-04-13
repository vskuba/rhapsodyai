import uuid
import os
from typing import Any, Dict
from langchain_text_splitters import MarkdownHeaderTextSplitter
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_.qdrant_ import _qdrant_db_get_client


class ParserMdToQdrant:
    def __init__(self, model: Any):
        self.config = model
        self.qdrant_client: AsyncQdrantClient = _qdrant_db_get_client()

        dest = self.config.destination[0]
        # Используем значение из конфига или дефолт
        model_name = getattr(dest, "embedding_model", "all-MiniLM-L6-v2")

        # 1. Настройка моделей для Гибридного поиска
        self.qdrant_client.set_model(model_name)
        self.qdrant_client.set_sparse_model("Qdrant/bm25")

    async def run(self):
        """Парсинг MD и загрузка в Qdrant"""
        source = self.config.source[0]
        dest = self.config.destination[0]

        if not os.path.exists(source.file_path):
            print(f"❌ Файл не найден: {source.file_path}")
            return

        with open(source.file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # Настройка сплиттера на основе уровней из конфига
        headers_to_split_on = [("#" * lvl, f"Header_{lvl}") for lvl in (source.header_levels or [1, 2, 3])]

        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False  # Оставляем заголовки в тексте для лучшего контекста
        )

        chunks = splitter.split_text(md_content)
        if not chunks:
            print("⚠️ Чанки не созданы. Проверьте структуру MD.")
            return

        if await self.qdrant_client.collection_exists(dest.collection_name):
            await self.qdrant_client.delete_collection(dest.collection_name)

        await self.qdrant_client.create_collection(
            collection_name=dest.collection_name,
            vectors_config=self.qdrant_client.get_fastembed_vector_params(),
            sparse_vectors_config=self.qdrant_client.get_fastembed_sparse_vector_params()
        )

        # 3. Индекс для полнотекстового поиска
        await self.qdrant_client.create_payload_index(
            collection_name=dest.collection_name,
            field_name="content",
            field_schema=models.TextIndexParams(
                type=models.TextIndexType.TEXT,
                tokenizer=models.TokenizerType.WORD,
                lowercase=True,
            )
        )

        documents, payloads = [], []

        for chunk in chunks:
            # Безопасно применяем шаблон
            doc_text = self._apply_md_template(chunk.page_content, chunk.metadata, dest.document_template)
            documents.append(doc_text)

            # Собираем метаданные согласно конфигу
            payload = {f: str(chunk.metadata.get(f, "")) for f in dest.metadata_fields if f != "source_file"}

            if "source_file" in dest.metadata_fields:
                payload["source_file"] = source.file_path

            payload["content"] = doc_text
            payloads.append(payload)

        if documents:
            # 4. Загрузка (автоматическая генерация Dense + Sparse векторов)
            await self.qdrant_client.add(
                collection_name=dest.collection_name,
                documents=documents,
                metadata=payloads,
                ids=[str(uuid.uuid4()) for _ in documents]
            )
            print(f"🚀 Готово! Коллекция '{dest.collection_name}' (Hybrid + Full-text). Чанков: {len(documents)}")

    def _apply_md_template(self, content: str, headers: Dict, template: str) -> str:
        """Безопасное форматирование текста по шаблону"""
        if not template:
            return content

        # Создаем словарь со всеми возможными ключами, чтобы .format() не падал
        # Мы знаем, что ищем Header_1, Header_2, Header_3
        render_data = {f"Header_{i}": headers.get(f"Header_{i}", "") for i in range(1, 4)}
        render_data["content"] = content

        try:
            return template.format(**render_data)
        except Exception:
            # Если в шаблоне есть другие ключи, которых нет в render_data
            return content