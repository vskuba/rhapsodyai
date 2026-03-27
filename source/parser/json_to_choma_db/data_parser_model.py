from typing import List, Optional, Dict, Union, Any
from pydantic import Field
from pydantic.dataclasses import dataclass, rebuild_dataclass

from source.parser.data_parser_model import DataParserYaml


@dataclass
class SourceModelChroma:
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
class DestinationModelChroma:
    collection_name: str
    vector_settings: Optional[VectorSettings] = None
    document_content: Optional[str] = None
    metadata: Optional[List[str]] = None


@dataclass
class JsonSchemaModel:
    type: str = "object"


@dataclass
class DataParserJsonToChromaYaml(DataParserYaml):
    title: str
    type: str
    source: List[SourceModelChroma]
    destination: List[DestinationModelChroma]
    schemas: Dict[str, Union[JsonSchemaModel, Any]]


rebuild_dataclass(DataParserJsonToChromaYaml)
