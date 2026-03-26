import json
import uuid

from typing import Any, Dict
from chromadb.utils import embedding_functions

from source.chroma_db import _chroma_db_get_client


class ParserChroma:
    def __init__(self, model: Any):
        self.config = model
        self.chroma_client = _chroma_db_get_client()

        v_settings = self.config.destination[0].vector_settings
        model_name = v_settings.embedding_model if v_settings else "all-MiniLM-L6-v2"

        # Локальная модель вместо OpenAI
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name
        )

    async def run(self):
        """Абсолютно универсальный запуск без привязки к Soko"""

        for source in self.config.source:
            with open(source.file_name, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            dest = self.config.destination[0]
            collection = self.chroma_client.get_or_create_collection(
                name=dest.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"created_by": "parser"}
            )

            # Читаем настройки из YAML
            it_key = getattr(source, 'iterator_key', None)
            ctx_fields = getattr(source, 'context_fields', [])
            meta_fields = dest.metadata
            content_tpl = dest.document_content

            documents, metadatas, ids = [], [], []

            # Если данные — список категорий (как у нас)
            for entry in raw_data:
                # 1. Извлекаем контекст (например, имя категории)
                context = {f: entry.get(f, "") for f in ctx_fields}

                # 2. Получаем вложенные объекты по ключу из YAML (items)
                items = entry.get(it_key, [entry]) if it_key else [entry]
                if not isinstance(items, list): items = [items]

                for item in items:
                    # Сливаем данные объекта и контекста
                    full_data = {**item, **context}

                    # 3. Собираем текст по шаблону "field1 + field2"
                    doc_text = self._apply_template(full_data, content_tpl)

                    # 4. Собираем метаданные по списку
                    meta = {f: str(full_data.get(f, "")) for f in meta_fields}

                    documents.append(doc_text)
                    metadatas.append(meta)
                    ids.append(str(uuid.uuid4()))

            # Пакетная загрузка в Chroma
            if documents:
                collection.add(documents=documents, metadatas=metadatas, ids=ids)

    def _apply_template(self, data: Dict, template: str) -> str:
        """Динамическая сборка контента по шаблону из YAML"""
        if not template: return str(data)
        parts = [p.strip().strip("'").strip('"') for p in template.split('+')]
        return " ".join([str(data.get(p, p)) for p in parts if p])
