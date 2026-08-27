-- Шаги workflow зовут инструменты `design_*` по новым именам.
--
-- Что случилось. Подзадача 1626 добавила функциям инструментов префикс namespace:
-- `ui_components_list_get` → `design_ui_components_list_get`, `ui_component_db_get` →
-- `design_ui_component_db_get` (и ещё семь, которые из шагов не зовут). Реестр `tool`
-- пересобирается из кода при каждом старте (`ai_tool_sync`), поэтому новые имена туда
-- приезжают сами. А шаги workflow держат имя инструмента строкой в
-- `metadata.tool_invoke.tool_name`, и их не правит никто.
--
-- Чем это грозит. Шаг зовёт имя, которого в реестре больше нет: инструмент не находится,
-- и падает не одна функция, а весь прогон workflow. Задеты три шага в трёх workflow —
-- 36 `planning_ux_spec` (шаг 316), 39 `planning_page_generator` (313) и
-- 40 `planning_prototype_block_render` (311). Это ровно тот случай, о котором
-- предупреждает `docs-common/tool_rules.md`: правка кода обратима, правка базы — нет.
--
-- Остальные семь переименованных инструментов (`design_ui_components_sync_from_doc`,
-- `design_wireframe_page_extract`, `tables_mysql_find` и прочие) из шагов не зовутся —
-- сверено запросом по `$.tool_invoke.tool_name` на всех workflow. Трогать их не нужно.
--
-- Идемпотентность. `REPLACE` ищет старое имя вместе с кавычками и ключом: на базе, где
-- имя уже новое, совпадения нет и файл ничего не меняет. Кавычки в шаблоне обязательны —
-- без них `ui_component_db_get` совпал бы и внутри `design_ui_component_db_get`,
-- и повторный прогон дал бы `design_design_ui_component_db_get`.
--
-- Точечный `REPLACE`, а не `JSON_SET`: последний пересобрал бы весь документ и переписал
-- порядок ключей и отступы у шага целиком. Здесь меняется ровно одна строка.

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(`metadata`,
    '"tool_name": "ui_components_list_get"',
    '"tool_name": "design_ui_components_list_get"')
WHERE `metadata` LIKE '%"tool_name": "ui_components_list_get"%';

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(`metadata`,
    '"tool_name": "ui_component_db_get"',
    '"tool_name": "design_ui_component_db_get"')
WHERE `metadata` LIKE '%"tool_name": "ui_component_db_get"%';
