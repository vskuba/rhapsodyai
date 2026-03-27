import uuid
import os
from typing import Any, Dict
from chromadb.utils import embedding_functions
from langchain_text_splitters import MarkdownHeaderTextSplitter

from source.chroma_db import _chroma_db_get_client


class ParserMdToChroma:
    def __init__(self, model: Any):
        self.config = model  # DataParserMdToChromaYaml
        self.chroma_client = _chroma_db_get_client()

        # 1. Берем первый конфиг назначения (т.к. это List)
        dest = self.config.destination[0]

        # 2. Поле embedding_model теперь на верхнем уровне в VectorStoreConfig
        model_name = dest.embedding_model or "all-MiniLM-L6-v2"

        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name
        )

    async def run(self):
        """Парсинг MD по заголовкам и загрузка в ChromaDB"""
        # Берем первые элементы из списков
        source = self.config.source[0]
        dest = self.config.destination[0]

        if not os.path.exists(source.file_path):
            print(f"Ошибка: Файл {source.file_path} не найден")
            return

        with open(source.file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # Настраиваем сплиттер (используем уровни из конфига)
        headers_to_split_on = [("#" * lvl, f"Header_{lvl}") for lvl in source.header_levels]

        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False  # Оставляем заголовки внутри текста для контекста
        )

        chunks = splitter.split_text(md_content)
        if not chunks: return

        collection = self.chroma_client.get_or_create_collection(
            name=dest.collection_name,
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": dest.distance_metric}
        )

        documents, metadatas, ids = [], [], []

        for chunk in chunks:
            header_metadata = chunk.metadata

            # Собираем метаданные
            final_meta = {}
            for field in dest.metadata_fields:
                if field == "source_file":
                    final_meta[field] = source.file_path
                else:
                    final_meta[field] = str(header_metadata.get(field, ""))

            # Используем document_template вместо document_content
            doc_text = self._apply_md_template(chunk.page_content, header_metadata, dest.document_template)

            documents.append(doc_text)
            metadatas.append(final_meta)
            ids.append(str(uuid.uuid4()))

        if documents:
            collection.add(documents=documents, metadatas=metadatas, ids=ids)
            print(f'✅ MD Parser: {len(documents)} блоков добавлено в {dest.collection_name}')

    def _apply_md_template(self, content: str, headers: Dict, template: str) -> str:
        """Безопасное заполнение шаблона из конфига"""
        if not template: return content
        try:
            # {content} и {Header_1} и т.д.
            return template.format(content=content, **headers)
        except Exception:
            return content