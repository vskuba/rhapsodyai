from dataclasses import dataclass
from typing import List, Optional, Dict, Union, Any
from pydantic import Field

from source.parser.data_parser_model import DataParserYaml


@dataclass
class FieldModel:
    name: str
    selector: str
    type: str
    attribute: Optional[str] = None
    mandatory: Optional[bool] = False
    fields: Optional[List['FieldModel']] = None


@dataclass
class SchemaModel:
    fields: List[FieldModel]


@dataclass
class TargetModel:
    url: str


@dataclass
class SourceModel:
    type: str
    targets: List[TargetModel]
    schema: str = Field(..., alias="schema")


@dataclass
class DestinationModel:
    file_name: str
    schema: str = Field(..., alias="schema")


@dataclass
class SourceSchemaModel:
    fields: List[FieldModel]


@dataclass
class DestinationSchemaModel:
    type: str = "object"
    required: Optional[List[str]] = None
    properties: Optional[Dict[str, Any]] = None

    # Разрешаем любые дополнительные поля JSON-схемы (items, additionalProperties и т.д.)
    model_config = {"extra": "allow"}


@dataclass
class DataParserHtmlToJsonYaml(DataParserYaml):
    source: List[SourceModel]
    destination: List[DestinationModel]
    schemas: Dict[str, Union[SourceSchemaModel, DestinationSchemaModel]]
