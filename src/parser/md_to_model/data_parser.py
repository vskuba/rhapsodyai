import re
from pathlib import Path
import aiofiles
from src.parser.md_to_model.data_parser_model import MdEntry


class ParserMdToModel:
    def __init__(self, path: Path):
        self.path = path

    async def parse(self) -> list[MdEntry]:
        all_entries = []

        # Получаем список всех .md файлов в папке
        md_files = [f for f in self.path.iterdir() if f.is_file() and f.suffix == '.md']

        for file_path in md_files:
            entries = await self._parse_file(file_path)
            all_entries.extend(entries)

        return all_entries

    async def create(self, entry: MdEntry, target_dir: Path):
        """
        Сохраняет модель MdEntry в файл в формате Markdown.
        Если файл уже существует, добавляет блок в конец через разделитель ===.
        """
        # Формируем строковое представление блока
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

        # Проверяем, существует ли файл, чтобы понять, нужен ли разделитель
        file = target_dir / entry.filename
        file_exists = file.exists()

        async with aiofiles.open(file, mode='a', encoding='utf-8') as f:
            if file_exists:
                # Если файл не пустой, добавляем разделитель перед новым блоком
                await f.write("\n===\n\n")
            await f.write(md_block)

    async def _parse_file(self, file_path: Path) -> list[MdEntry]:
        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            content = await f.read()

        # Разделяем на блоки по '==='
        blocks = re.split(r'\n+===[ \t]*\n+', content)
        file_entries = []

        for block in blocks:
            block = block.strip()
            if not block or "##" not in block:
                continue

            # Отделяем метаданные от текста по '---'
            try:
                header_part, body_content = re.split(r'\n+---[ \t]*\n+', block, maxsplit=1)
            except ValueError:
                continue

            lines = header_part.splitlines()

            # Ищем заголовок (первая строка, начинающаяся с ##)
            title = ""
            metadata_lines = []
            for line in lines:
                if line.startswith('##'):
                    title = line.replace('##', '').strip()
                elif ':' in line:
                    metadata_lines.append(line)

            # Парсим метаданные в словарь
            metadata = {}
            for line in metadata_lines:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip()

            # Превращаем строку тегов "[а, б]" в список
            tags_raw = metadata.get('tags', '[]').strip('[]')
            tags = [t.strip() for t in tags_raw.split(',') if t.strip()]

            file_entries.append(
                MdEntry(
                    filename=file_path.name,
                    title=title,
                    group_id=metadata.get('group_id', ''),
                    category=metadata.get('category', ''),
                    language=metadata.get('language', ''),
                    tags=tags,
                    content=body_content.strip()
                )
            )

        return file_entries
