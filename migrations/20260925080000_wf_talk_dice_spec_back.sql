-- Спецификация жребия возвращается в шаг жребия (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ: я сломал читаемость шага, борясь с литералом
--
-- Убирая приставку `_const_`, я вынес **всю спецификацию жребия** — 2494 знака с
-- осями, вариантами и весами — из шага «Жребий» в шаг «Ключи», переменной
-- `dice_spec`. Формально литерала не стало. По существу вышло хуже прежнего:
--
--     было:  «Жребий» → spec = _const_{варианты и веса прямо здесь}
--     стало: «Жребий» → spec = dice_spec       ← что бросаем, не видно
--            «Ключи»  → dice_spec = {2494 знака}  ← в чужом шаге, среди ключей пары
--
-- Открыв шаг жребия, человек больше не видит, **что** бросается: ни осей, ни
-- вариантов, ни весов. А открыв «Ключи» — находит там простыню JSON, к ключам пары
-- отношения не имеющую. Ровно та беда, от которой правило и заводилось: «откуда
-- значение» перестало быть видно на месте.
--
-- ## ⚠⚠ Почему здесь литерал — законный случай
--
-- Правило §3.0 запрещает **значение, которого нет ни в одном списке**, потому что
-- его не найти. Спецификация жребия — не значение, а **настройка самого шага**: она
-- описывает, что именно этот шаг делает, и место ей — в нём.
--
-- Разница с `limit: 20` и `kind: chat` существенная: те два вправду параметры, их
-- меняют, и переменная даёт им имя и описание. А осей жребия с весами не «передают
-- в инструмент» — ими шаг и является.
--
-- ⚠ Остальные шесть переменных остаются на месте (`talk_history_*`,
-- `talk_session_kind`): там литерал был вправду параметром.
--
-- ## Что делается
--
--     1. `spec` возвращается в шаг жребия — значением из `dice_spec`, байт в байт
--     2. запись `dice_spec` уходит из «Ключей»
--     3. переменная `dice_spec` снимается с workflow и из реестра
--
-- ⚠ Значение **копируется из «Ключей»**, а не набирается заново: 2494 знака с
-- кириллицей и метками вида `%dice_mail_name_percent%`, и одна опечатка меняет
-- поведение жребия молча.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @dice = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'dice' LIMIT 1);
SET @keys = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.variable_conversion[1].variable')) = 'girl_unique_id' LIMIT 1);

-- ⚠⚠ Место записи ищем, а не берём номером: `JSON_SEARCH` отдаёт **путь** (`$[7]`),
-- цифры из него вынимаются отдельно — склейка пути в `$.variable_conversion[$[7]]`
-- даёт «Invalid JSON path expression».
SET @slot = (SELECT REGEXP_REPLACE(JSON_UNQUOTE(JSON_SEARCH(
                      JSON_EXTRACT(`metadata`, '$.variable_conversion[*].variable'),
                      'one', 'dice_spec')), '[^0-9]', '')
               FROM `agent_workflow_step` WHERE `id` = @keys);

SET @spec = (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      CONCAT('$.variable_conversion[', @slot, '].text')))
               FROM `agent_workflow_step`
              WHERE `id` = @keys AND @slot IS NOT NULL AND @slot <> '');

SELECT 'ДО' AS этап,
       COALESCE(@slot, '—') AS место_в_ключах,
       LENGTH(COALESCE(@spec, '')) AS длина_спецификации,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.spec'))
          FROM `agent_workflow_step` WHERE `id` = @dice) AS сейчас_у_жребия;

-- ── 1. Спецификация возвращается в шаг жребия ───────────────────────────────
--
-- ⚠ Приставка `_const_` нужна: без неё движок пойдёт искать переменную с именем
-- «{"dice_mail_opening":…}» и передаст в инструмент `None`.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.inputs_map.spec',
                             CONCAT('_const_', @spec))
 WHERE `id` = @dice AND @dice IS NOT NULL
   AND @spec IS NOT NULL AND LENGTH(@spec) > 100;

-- ── 2. Запись уходит из «Ключей» ────────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REMOVE(`metadata`,
                      CONCAT('$.variable_conversion[', @slot, ']'))
 WHERE `id` = @keys AND @keys IS NOT NULL
   AND @slot IS NOT NULL AND @slot <> ''
   AND @spec IS NOT NULL AND LENGTH(@spec) > 100;

-- ── 3. Переменная снимается: она больше ничего не значит ────────────────────
--
-- ⚠ Сначала объявление у workflow, потом сама переменная — иначе объявление
-- осталось бы висеть на несуществующей строке.
DELETE x FROM `agent_workflow_variable_workflow` x
  JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
 WHERE x.`workflow_id` = @wf AND v.`name` = 'dice_spec';

-- ⚠⚠ Переменную удаляем только если её не читает никто другой: она общая на все
-- workflow, и у соседа могла бы быть своя нужда.
DELETE FROM `agent_workflow_variable`
 WHERE `name` = 'dice_spec'
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = `id`);

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Спецификация обязана быть у жребия и целиком: обрежься она, жребий
       -- бросал бы по обрывку JSON и молча брал первый вариант.
       (SELECT LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')))
          FROM `agent_workflow_step` WHERE `id` = @dice) AS длина_у_жребия,
       -- ⚠ В «Ключах» её больше нет — там остались ключи пары и параметры лент.
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.variable_conversion'))
          FROM `agent_workflow_step` WHERE `id` = @keys) AS записей_в_ключах,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `name` = 'dice_spec')
         AS переменная_осталась,
       -- ⚠ Шесть переменных лент и канала на месте: их правило не касается.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE x.`workflow_id` = @wf
           AND v.`name` IN ('talk_history_chat_kind', 'talk_history_chat_limit',
                            'talk_history_mail_kind', 'talk_history_mail_limit',
                            'talk_session_kind', 'girl_response_final'))
         AS переменных_лент;
