# Parser — YAML-драйверы загрузки данных

> Один YAML-файл описывает источник, тип и назначение; `data_parser_load()`
> по полю `type` строит нужный класс и запускает импорт.
> Код: `src/parser/data_parser.py`, подкаталоги `src/parser/*_to_*/`.

## 1. Модель

Парсер описывается YAML-файлом в `data_dir/<parser_dir>/`. Корневой файл
возвращается строкой, файл в подкаталоге — списком (структура папки —
описание группы). Формат:

```yaml
title: Название
type: md_to_qdrant        # какой класс строить
source: ...               # поля класса-источника
destination: ...          # поля класса-назначения
```

`data_parser_load(parser_path)` читает YAML, подмешивает `path` и `name`, и
диспатчит по `type`:

| `type` | Класс | Что делает |
|--------|-------|-----------|
| `html_to_json` | `ParserHtmlToJson` | crawl4ai: скреип страницы по CSS-схеме → JSON |
| `json_to_qdrant` | `ParserJsonToQdrant` | JSON → Qdrant (dense, SentenceTransformer) |
| `md_to_qdrant` | `ParserMdToQdrant` | Markdown по заголовкам → Qdrant (dense + sparse BM25) |
| `md_to_fact` | `ParserMdToFact` | `.md` по `##`-заголовкам → `MdEntry` (без векторной БД) |

Неизвестный `type` — `ValueError`, не молча пропуск.

## 2. Файлы

| Файл | Роль |
|------|------|
| `src/parser/data_parser.py` | `data_parser_dir()`, `data_parser_path_list()`, `data_parser_load()` |
| `src/parser/data_parser_model.py` | `DataParserYaml(path, name, title, type)` |
| `src/parser/html_to_json/` | `ParserHtmlToJson` + модели `Field/Schema/Target/SourceModel` |
| `src/parser/json_to_qdrant/` | `ParserJsonToQdrant` + `SourceModelQdrant/VectorSettings/DestinationModelQdrant` |
| `src/parser/md_to_qdrant/` | `ParserMdToQdrant` + `MdSourceConfig/VectorStoreConfig` |
| `src/parser/md_to_fact/` | `ParserMdToFact` + `MdEntry` |

## 3. ⚠ Подсистема без вызовов

`data_parser_load()` и все классы **не вызываются** из `src/`, `src/tool/`,
`src/cronjob/` — это задел на загрузку внешних данных (скреип → векторы,
markdown → факты). Ключ `parser_dir` в `.env` указывает каталог с YAML.

❌ Держать четыре почти одинаковых класса «на будущее» — каждый из них
несёт свою логику Qdrant/эмбеддингов и будет сгывать независимо.

✅ Подключить к роутеру/крону, либо сократить до реально нужных типов.

## Грабли

1. **Считать, что парсеры уже работают в проде** — §3, вызовов нет; это
   библиотека заготовки, а не активный пайплайн.
2. **Зависеть от `type` как от строки-магика** — §1, опечатка упадёт как
   `ValueError` только в момент `load`, а не при валидации схемы.
3. **Менять YAML в корне, ожидая групповую обработку** — §1, корневой файл
   читается как один, в подкаталог — как группа; раскладка = смысл.
