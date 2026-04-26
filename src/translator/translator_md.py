import os
from dataclasses import dataclass

from config.config import config_get


@dataclass
class TranslatorMd:
    project_name: str
    language: str


def translator_md_dir() -> str:
    return config_get('data_dir') + '/' + config_get('MD_DIR')


def translator_md_list() -> list[TranslatorMd]:
    """
    Возвращает список объектов MdTranslator, сканируя подпапки.
    """
    base_dir = translator_md_dir()
    results = []

    if not os.path.exists(base_dir):
        return []

    for project_name in os.listdir(base_dir):
        project_path = os.path.join(base_dir, project_name)

        if os.path.isdir(project_path):
            for lang_name in os.listdir(project_path):
                lang_path = os.path.join(project_path, lang_name)

                if os.path.isdir(lang_path):
                    results.append(TranslatorMd(
                        project_name=project_name,
                        language=lang_name
                    ))

    return sorted(results, key=lambda x: (x.project_name, x.language))