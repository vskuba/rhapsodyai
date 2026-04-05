from typing import List, Optional, Dict, Any
from pydantic import Field
from pydantic.dataclasses import dataclass, rebuild_dataclass
from source.parser.data_parser_model import DataParserYaml

@dataclass
class MdSourceConfig:
    file_path: str
    header_levels: List[int] = Field(default_factory=lambda: [1, 2, 3])

@dataclass
class VectorStoreConfig:
    collection_name: str
    embedding_model: str = "all-MiniLM-L6-v2"
    document_template: str = "{content}"
    metadata_fields: List[str] = Field(default_factory=list)

@dataclass
class DataParserMdToQdrantYaml(DataParserYaml):
    title: str
    type: str
    source: List[MdSourceConfig]
    destination: List[VectorStoreConfig]
    schemas: Optional[Dict[str, Any]] = None

rebuild_dataclass(MdSourceConfig)
rebuild_dataclass(VectorStoreConfig)
rebuild_dataclass(DataParserMdToQdrantYaml)