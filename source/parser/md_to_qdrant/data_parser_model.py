from typing import List
from pydantic.dataclasses import dataclass, rebuild_dataclass
from source.parser.data_parser_model import DataParserYaml


@dataclass
class MdSourceConfig:
    files_path: str
    languages: List[str]

@dataclass
class VectorStoreConfig:
    collection_name: str
    embedding_model: str
    document_template: str
    metadata_fields: List[str]

@dataclass
class DataParserMdToQdrantYaml(DataParserYaml):
    title: str
    type: str
    source: List[MdSourceConfig]
    destination: List[VectorStoreConfig]

rebuild_dataclass(MdSourceConfig)
rebuild_dataclass(VectorStoreConfig)
rebuild_dataclass(DataParserMdToQdrantYaml)