import os
import yaml

from pathlib import Path
from source.config import config_get
from source.parser.data_parser_model import DataParserYaml
from source.parser.html_to_json.data_parser_model import DataParserHtmlToJsonYaml
from source.parser.json_to_choma_db.data_parser_model import DataParserJsonToChromaYaml
from source.parser.md_to_choma_db.data_parser_model import DataParserMdToChromaYaml


def data_parser_dir() -> str:
    return config_get('data_dir') + '/' + config_get('parser_dir')


def data_parser_path_list() -> list[str | list[str]]:
    root_dir = data_parser_dir()
    if not os.path.exists(root_dir):
        return []

    result = []
    for root, dirs, files in os.walk(root_dir):
        # Получаем список .yml файлов (без расширения) с учетом пути от корня
        yml_files = []
        for f in sorted(files):
            if f.endswith('.yml'):
                # Важно: получаем путь вида 'folder/file' или просто 'file'
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, root_dir)
                name_without_ext = os.path.splitext(rel_path)[0]
                yml_files.append(name_without_ext)

        if yml_files:
            if root == root_dir:
                result.extend(yml_files)  # Файлы в корне — строками
            else:
                result.append(yml_files)  # Файлы в папках — списками
    return result


def data_parser_load(parser_path: str) -> DataParserYaml:
    """
    Загружает конкретный YAML конфиг по имени файла (без расширения).
    """
    # Формируем полный путь к файлу
    base_dir = data_parser_dir()
    file_path = Path(base_dir) / f"{parser_path}.yml"
    parser_name = parser_path.split('/')[-1]

    if not file_path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        # 1. Загружаем "сырой" YAML в словарь
        raw_config = yaml.safe_load(f)

        # 2. Валидируем и преобразуем в объект модели
        # Pydantic автоматически сопоставит 'schema' из YAML с 'schema_name' в модели благодаря alias

        parser_type = raw_config.get('type')
        raw_config['path'] = parser_path
        raw_config['name'] = parser_name

        if parser_type == 'html_to_json':
            return DataParserHtmlToJsonYaml(**raw_config)

        if parser_type == 'json_to_chroma_db':
            return DataParserJsonToChromaYaml(**raw_config)

        if parser_type == 'md_to_chroma_db':
            return DataParserMdToChromaYaml(**raw_config)

        raise ValueError(f"Can't find out model for type {parser_type}")