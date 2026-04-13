import json
import uuid
from typing import Dict, Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from sentence_transformers import SentenceTransformer
from qdrant_.qdrant_ import _qdrant_db_get_client


class ParserJsonToQdrant:
    def __init__(self, config: Any):
        self.config = config
        self.client: AsyncQdrantClient = _qdrant_db_get_client()

        # Инициализируем модель эмбеддингов локально
        # Совет: если парсер запускается часто, лучше вынести модель в синглтон
        v_settings = self.config.destination[0].vector_settings
        model_name = v_settings.embedding_model if v_settings else "all-MiniLM-L6-v2"
        self.encoder = SentenceTransformer(model_name)

    async def run(self):
        """Универсальный импорт в Qdrant на основе YAML конфига"""

        for source in self.config.source:
            with open(source.file_name, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            dest = self.config.destination[0]
            vector_size = self.encoder.get_sentence_embedding_dimension()

            # 1. Добавляем await для асинхронных методов клиента
            if not await self.client.collection_exists(dest.collection_name):
                await self.client.create_collection(
                    collection_name=dest.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
                )

            it_key = source.iterator_key
            ctx_fields = source.context_fields
            meta_fields = dest.metadata
            content_tpl = dest.document_content

            points = []

            for entry in raw_data:
                context = {f: entry.get(f, "") for f in ctx_fields}
                items = entry.get(it_key, [entry]) if it_key else [entry]
                if not isinstance(items, list): items = [items]

                for item in items:
                    full_data = {**item, **context}
                    doc_text = self._apply_template(full_data, content_tpl)

                    # Кодирование текста в вектор
                    vector = self.encoder.encode(doc_text).tolist()

                    payload = {f: full_data.get(f, "") for f in meta_fields}
                    payload["document_content"] = doc_text

                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=vector,
                            payload=payload
                        )
                    )

            # 2. Добавляем await для загрузки данных
            if points:
                await self.client.upsert(
                    collection_name=dest.collection_name,
                    points=points
                )
                print(f'✅ Qdrant: Collection {dest.collection_name} synced. Added {len(points)} points.')

    def _apply_template(self, data: Dict, template: str) -> str:
        if not template: return str(data)
        parts = [p.strip().strip("'").strip('"') for p in template.split('+')]
        return " ".join([str(data.get(p, p)) for p in parts if p])