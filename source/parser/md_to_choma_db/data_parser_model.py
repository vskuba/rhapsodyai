from typing import List, Optional, Dict, Any, Literal
from pydantic import Field
from pydantic.dataclasses import dataclass, rebuild_dataclass
from source.parser.data_parser_model import DataParserYaml

@dataclass
class MdSourceConfig:
    """Настройки чтения и сегментации Markdown файла."""
    file_path: str
    # Стратегия разбивки: по заголовкам, по размеру чанка или по параграфам
    split_strategy: Literal["markdown_header", "recursive_character", "paragraph"] = "markdown_header"
    # Максимальный размер одного текстового блока (если стратегия позволяет)
    chunk_size: int = 1000
    chunk_overlap: int = 100
    # Добавлять ли путь к файлу в метаданные каждого чанка автоматически
    add_source_to_metadata: bool = True
    # Уровни заголовков для разделения (например, [1, 2, 3] для #, ##, ###)
    header_levels: List[int] = Field(default_factory=lambda: [1, 2, 3])

@dataclass
class VectorStoreConfig:
    """Параметры коллекции в ChromaDB."""
    collection_name: str
    embedding_model: str = "text-embedding-3-small"  # Поле прямо здесь!
    document_template: str = "{content}"
    metadata_fields: List[str] = Field(default_factory=list)
    distance_metric: str = "cosine"

@dataclass
class DataParserMdToChromaYaml(DataParserYaml):
    """Корневая модель для MD -> ChromaDB парсера."""
    title: str
    type: str
    source: List[MdSourceConfig]
    destination: List[VectorStoreConfig]
    schemas: Optional[Dict[str, Any]] = None

# Пересборка для поддержки вложенности и корректной валидации типов
rebuild_dataclass(MdSourceConfig)
rebuild_dataclass(VectorStoreConfig)
rebuild_dataclass(DataParserMdToChromaYaml)