from dataclasses import dataclass


@dataclass
class DataParserYaml:
    path: str
    name: str
    title: str
    type: str
