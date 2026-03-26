import os
import yaml

from pathlib import Path
from source.config import config_get
from source.data.parser.data_parser_model import DataParserYaml
from source.data.parser.html_to_json.data_parser_model import DataParserHtmlYaml
from source.data.parser.json_to_choma_db.data_parser_model import DataParserChromaYaml


def data_parser_dir() -> str:
    return config_get('data_dir') + '/' + config_get('parser_dir')


def data_parser_list() -> list[str]:
    data_parser_dir_ = data_parser_dir()
    if not os.path.exists(data_parser_dir_):
        return []

    return [os.path.splitext(f)[0] for f in os.listdir(data_parser_dir_) if f.endswith('.yml')]


def data_parser_load(parser_name: str) -> DataParserYaml:
    """
    Загружает конкретный YAML конфиг по имени файла (без расширения).
    """
    # Формируем полный путь к файлу
    base_dir = data_parser_dir()
    file_path = Path(base_dir) / f"{parser_name}.yml"

    if not file_path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        # 1. Загружаем "сырой" YAML в словарь
        raw_config = yaml.safe_load(f)

        # 2. Валидируем и преобразуем в объект модели
        # Pydantic автоматически сопоставит 'schema' из YAML с 'schema_name' в модели благодаря alias

        parser_type = raw_config.get('type')
        raw_config['name'] = parser_name

        if parser_type == 'html_to_json':
            return DataParserHtmlYaml(**raw_config)

        if parser_type == 'json_to_chroma_db':
            return DataParserChromaYaml(**raw_config)

        raise ValueError(f"Can't find out model for type {parser_type}")