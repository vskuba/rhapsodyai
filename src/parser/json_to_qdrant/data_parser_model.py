from typing import List, Optional, Dict, Union, Any
from pydantic import Field
from pydantic.dataclasses import dataclass, rebuild_dataclass

from src.parser.data_parser_model import DataParserYaml


@dataclass
class SourceModelQdrant:
    file_name: str
    schema_name: str = Field(..., alias="schema")
    iterator_key: Optional[str] = None
    context_fields: List[str] = Field(default_factory=list)


@dataclass
class VectorSettings:
    embedding_model: str = "text-embedding-3-small"
    index_fields: List[str] = Field(default_factory=list)
    metadata_fields: List[str] = Field(default_factory=list)


@dataclass
class DestinationModelQdrant:
    collection_name: str
    vector_settings: Optional[VectorSettings] = None
    document_content: Optional[str] = None
    metadata: Optional[List[str]] = None


@dataclass
class JsonSchemaModel:
    type: str = "object"


@dataclass
class DataParserJsonToQdrantYaml(DataParserYaml):
    title: str
    type: str
    source: List[SourceModelQdrant]
    destination: List[DestinationModelQdrant]
    schemas: Dict[str, Union[JsonSchemaModel, Any]]


rebuild_dataclass(DataParserJsonToQdrantYaml)
