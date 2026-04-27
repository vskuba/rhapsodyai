import re
import aiofiles

from pathlib import Path
from src.parser.md_to_fact.data_parser_model import MdEntry


class ParserMdToFact:
    def __init__(self, path: Path = None):
        self.path = path

    async def parse(self) -> list[MdEntry]:
        """Парсит все файлы в папке self.path"""
        if not self.path:
            raise ValueError("Path is not set for folder parsing")

        all_entries = []
        md_files = [f for f in self.path.iterdir() if f.is_file() and f.suffix == '.md']

        for file_path in md_files:
            async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
                content = await f.read()

            # Используем новый метод для парсинга контента
            entries = await self._parse_content(content, filename=file_path.name)
            all_entries.extend(entries)

        return all_entries

    async def _parse_content(self, content: str, filename: str = "default.md") -> list[MdEntry]:
        """
        Парсит контент, разделяя его строго по заголовкам '##'.
        """
        # Используем Lookahead (?!), чтобы разделить текст перед каждой '##',
        # сохраняя сам заголовок внутри блока.
        blocks = re.split(r'\n+(?=##)', "\n" + content.strip())

        file_entries = []

        for block in blocks:
            block = block.strip()
            if not block or "##" not in block:
                continue

            # 1. Отделяем метаданные от основного текста по '---'
            parts = re.split(r'\n+---[ \t]*\n+', block, maxsplit=1)
            if len(parts) < 2:
                continue

            header_part, body_content = parts
            lines = header_part.splitlines()

            # 2. Извлекаем заголовок (title) и метаданные (key: value)
            title = ""
            metadata = {}
            for line in lines:
                if line.startswith('##'):
                    title = line.replace('##', '').strip()
                elif ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()

            # 3. Обработка тегов (строку "[a, b]" превращаем в список)
            tags_raw = metadata.get('tags', '[]').strip('[]')
            tags = [t.strip() for t in tags_raw.split(',') if t.strip()]

            # 4. Формируем объект записи
            file_entries.append(
                MdEntry(
                    filename=filename,
                    title=title,
                    group_id=metadata.get('group_id', ''),
                    category=metadata.get('category', ''),
                    language=metadata.get('language', ''),
                    tags=tags,
                    content=body_content.strip()
                )
            )

        return file_entries

    async def create(self, entry: MdEntry, target_dir: Path):
        """Сохранение модели в файл (без изменений)"""
        tags_str = ", ".join(entry.tags)
        md_block = (
            f"## {entry.title}\n"
            f"group_id: {entry.group_id}\n"
            f"category: {entry.category}\n"
            f"language: {entry.language}\n"
            f"tags: [{tags_str}]\n"
            f"---\n"
            f"{entry.content}\n"
        )

        file = target_dir / entry.filename
        file_exists = file.exists()

        async with aiofiles.open(file, mode='a', encoding='utf-8') as f:
            if file_exists:
                await f.write("\n===\n\n")
            await f.write(md_block)
