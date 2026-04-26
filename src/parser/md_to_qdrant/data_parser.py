import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple
from langchain_text_splitters import MarkdownHeaderTextSplitter
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_.qdrant_ import _qdrant_db_get_client
from src.parser.md_to_qdrant.data_parser_model import DataParserMdToQdrantYaml


class ParserMdToQdrant:
    def __init__(self, model: DataParserMdToQdrantYaml):
        self.config = model
        self.qdrant_client: AsyncQdrantClient = _qdrant_db_get_client()

    async def run(self):
        dest = self.config.destination[0]
        source_cfg = self.config.source[0]

        self.qdrant_client.set_model(dest.embedding_model)
        self.qdrant_client.set_sparse_model("Qdrant/bm25")

        all_documents: List[str] = []
        all_payloads: List[Dict[str, Any]] = []

        # 1. Итерация по языкам (папкам)
        base_dir = Path(source_cfg.files_path)

        for lang in source_cfg.languages:
            lang_path = base_dir / lang

            if not lang_path.exists():
                print(f"⚠️ Путь не найден: {lang_path}")
                continue

            # Сканируем только .md файлы
            for file_path in lang_path.glob("*.md"):
                docs, payloads = self._process_file(file_path, lang, dest)
                all_documents.extend(docs)
                all_payloads.extend(payloads)

        if not all_documents:
            print("❌ Нет данных для загрузки. Проверьте содержимое папок.")
            return

        # 2. Пересоздание коллекции (Full Reindex)
        if await self.qdrant_client.collection_exists(dest.collection_name):
            await self.qdrant_client.delete_collection(dest.collection_name)

        await self.qdrant_client.create_collection(
            collection_name=dest.collection_name,
            vectors_config=self.qdrant_client.get_fastembed_vector_params(),
            sparse_vectors_config=self.qdrant_client.get_fastembed_sparse_vector_params()
        )

        # 3. Индекс для полнотекстового поиска по полю 'content'
        await self.qdrant_client.create_payload_index(
            collection_name=dest.collection_name,
            field_name="content",
            field_schema=models.TextIndexParams(
                type=models.TextIndexType.TEXT,
                tokenizer=models.TokenizerType.WORD,
                lowercase=True,
            )
        )

        # 4. Загрузка данных
        await self.qdrant_client.add(
            collection_name=dest.collection_name,
            documents=all_documents,
            metadata=all_payloads,
            ids=[str(uuid.uuid4()) for _ in all_documents]
        )

        print(f"🚀 Успех! Коллекция '{dest.collection_name}' обновлена. Чанков: {len(all_documents)}")

    def _process_file(self, file_path: Path, lang: str, dest: Any) -> Tuple[List[str], List[Dict]]:
        with open(file_path, 'r', encoding='utf-8') as f:
            full_content = f.read()

        # Теперь мы не сплитим вручную по ===
        # MarkdownHeaderTextSplitter сам создаст чанки на основе ##
        headers_to_split_on = [("#", "Header_1"), ("##", "Header_2")]
        splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=True)

        docs, payloads = [], []

        # Передаем весь текст файла сразу
        chunks = splitter.split_text(full_content)

        for chunk in chunks:
            # Если чанк пустой (например, текст между # и ##), пропускаем
            if not chunk.page_content.strip():
                continue

            # 1. Извлекаем внутренние метаданные (group_id, tags) и тело текста
            internal_meta, content_body = self._extract_metadata_and_body(chunk.page_content)

            # 2. Формируем метаданные
            full_metadata = {**chunk.metadata, **internal_meta}
            full_metadata["language"] = lang
            full_metadata["source_file"] = file_path.name

            # Устанавливаем краткий заголовок для поля 'document'
            short_title = full_metadata.get("Header_2") or full_metadata.get("Header_1") or file_path.stem
            full_metadata["document"] = short_title.strip()

            # 3. Собираем текст по шаблону из YAML
            doc_text = self._apply_template(content_body, full_metadata, dest.document_template)

            # 4. Формируем итоговый payload
            payload = {field: full_metadata.get(field, "") for field in dest.metadata_fields}
            payload["content"] = doc_text

            docs.append(doc_text)
            payloads.append(payload)

        return docs, payloads

    def _apply_template(self, content_body: str, metadata: Dict, template: str) -> str:
        """Безопасно подставляет данные в шаблон, включая заголовки"""
        render_data = {
            "Header_1": metadata.get("Header_1", ""),
            "Header_2": metadata.get("Header_2", ""),
            "content_body": content_body
        }
        try:
            # Убираем лишние пробелы, если какого-то заголовка нет
            return template.format(**render_data).replace(" > \n", "\n").strip()
        except (KeyError, ValueError):
            return content_body

    def _extract_metadata_and_body(self, text: str) -> Tuple[Dict[str, Any], str]:
        """Извлекает блок 'ключ: значение' из текста над разделителем ---"""
        if "---" not in text:
            return {}, text.strip()

        header_part, body_part = text.split("---", 1)

        metadata = {}
        for line in header_part.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                clean_key = key.strip()
                clean_value = value.strip().strip("[]")  # Убираем скобки у тегов

                # Если это список (теги)
                if "," in clean_value:
                    metadata[clean_key] = [v.strip() for v in clean_value.split(",")]
                else:
                    metadata[clean_key] = clean_value

        return metadata, body_part.strip()