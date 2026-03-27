import json
import os
from dataclasses import asdict

from typing import List, Dict, Any
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, BrowserConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

from source.parser.html_to_json.data_parser_model import DataParserHtmlToJsonYaml


class ParserHtmlToJson:
    def __init__(self, model: DataParserHtmlToJsonYaml):
        self.config = asdict(model) if not isinstance(model, dict) else model
        self.results = []

    async def run(self):
        for source in self.config.get('source', []):
            if source['type'] == 'crawl4ai':
                schema_name = source.get('schema')
                schemas = self.config.get('schemas', {})
                source_schema = schemas.get(schema_name)

                if not source_schema:
                    print(f"Schema {schema_name} not found!")
                    continue

                for target in source.get('targets', []):
                    url = target.get('url')

                    print(f"Scraping from: {url}")

                    data = await self._crawl_source(url, source_schema)

                    if isinstance(data, list) and len(data) > 0:
                        self.results.extend(data)
                    elif isinstance(data, dict):
                        self.results.append(data)

        # 2. Сохранение в файлы (destination)
        for dest in self.config.get('destination', []):
            if self.config.get('type') == 'html_to_json' and dest['file_name']:
                self._save_to_json(dest)

    async def _crawl_source(self, url: str, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
        clean_schema = self._remove_none(schema)

        extraction_data = {
            "baseSelector": clean_schema.get("baseSelector", "body"),
            "fields": clean_schema.get("fields", [])
        }

        # Динамический выбор селектора для ожидания (первое поле в списке)
        wait_selector = "body"
        fields_list = extraction_data.get("fields", [])
        if fields_list and len(fields_list) > 0:
            wait_selector = fields_list[0].get("selector", "body")

        extraction_strategy = JsonCssExtractionStrategy(extraction_data)

        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=extraction_strategy,
            js_code="window.scrollTo(0, document.body.scrollHeight);",
            wait_for=f"css:{wait_selector}",
            wait_until="networkidle"
        )

        browser_config = BrowserConfig(
            headless=True,
            browser_type="chromium",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

            if result.success:
                content = result.extracted_content
                data = json.loads(content) if isinstance(content, str) else content
                return self._clean_strings(data)
            else:
                print(f"Error crawling {url}: {result.error_message}")
                return []

    def _remove_none(self, obj):
        """Удаляет ключи с None из словаря рекурсивно."""
        if isinstance(obj, dict):
            return {k: self._remove_none(v) for k, v in obj.items() if v is not None}
        elif isinstance(obj, list):
            return [self._remove_none(v) for v in obj if v is not None]
        return obj

    def _clean_strings(self, obj):
        """Рекурсивно очищает все строковые поля от NBSP и пробелов."""
        if isinstance(obj, dict):
            return {k: self._clean_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_strings(i) for i in obj]
        elif isinstance(obj, str):
            return obj.replace('\xa0', ' ').strip()
        return obj

    def _save_to_json(self, dest_config: Dict[str, Any]):
        """Сохраняет результаты в файл."""
        file_path = os.path.join(dest_config['file_name'])
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Сохраняем весь список накопленных категорий
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        print(f"Successfully saved to {file_path}")