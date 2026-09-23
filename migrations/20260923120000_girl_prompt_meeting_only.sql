-- Персона девушки: запрет обещаний вернулся, но только про встречу (2026-09-23)
--
-- ## ⚠⚠ Это ДОБАВЛЕНИЕ, а не переформулировка: прежнего предложения в базе нет
--
-- Речь про фразу, которая когда-то стояла в персоне:
--
--     The same applies to photos: you don’t send them or promise anything specific.
--
-- Её **убрали целиком** 21 сентября (`20260921150000_girl_prompt_photo_allow.sql`):
-- она перебивала ветку «письма и фото», и девушка отказывалась прислать свои
-- фотографии письмом, хотя ветка заведена ровно ради этого согласия.
--
-- Сейчас в персоне про фотографии нет ни слова — проверено запросом к обеим
-- строкам. Значит эта миграция не переписывает старое, а **вносит новое**
-- предложение, и звучит оно про встречу:
--
--     You don’t promise anything specific about meeting.
--
-- ## Зачем оно нужно
--
-- Запрет на встречи в персоне уже есть, но он про **согласие**: «You never agree
-- to personal meetings or calls», «You never suggest meeting up». Обещание —
-- третий случай, и он не закрыт ни одним из двух: «давай как-нибудь в декабре» не
-- согласие и не предложение, а именно обещание, и человек будет его ждать.
--
-- ## ⚠⚠ Почему «about meeting», а не общее «anything specific»
--
-- Общая формулировка и была причиной прошлой поломки. «Не обещай ничего
-- определённого» распространялось на фотографии — а ветка требует **пообещать**
-- прислать их письмом. Два голоса об одном, и системный промпт побеждал.
--
-- Оговорка про встречу не пересекается с фотографиями вовсе: ветка про них
-- молчит о встречах, а персона — о фотографиях.
--
-- ⚠ Тест `tests_llm/dating_talk/test_talk.py::test_it_promises_her_photos` эта
-- правка **не чинит**: он падал уже после снятия прежнего запрета, то есть
-- причина у него другая. Метка `xfail` на нём остаётся.
--
-- ## ⚠⚠ ДВА МЕСТА, И ОБА ОБЯЗАТЕЛЬНЫ
--
--   1) `agent.prompt_system` у `dating_girl_universal` — то, что работает сейчас
--      (движок читает поля агента напрямую, минуя переменные workflow);
--   2) `node_variable.girl_prompt_system` — шаблон, которым заводят агента
--      (`dating_bot` шаг 9, `dating_girl_create` шаг 3). Пропусти его — и новая
--      анкета заведётся без оговорки.
--
-- ⚠ Апостроф ТИПОГРАФСКИЙ (U+2019, байты E2 80 99) — такой же, как в соседних
-- «you’re» и «don’t». С обычным `'` предложение выпадало бы из строя глазом.
--
-- ⚠ Перезапуск не нужен: ни промпт агента, ни переменные ноды не кэшируются —
-- `repo_agent.find_one_by` и `ai_workflow_variables_node_get` ходят в базу на
-- каждый запрос.
--
-- Идемпотентность: вставляем только там, где оговорки ещё нет.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%specific about meeting%') AS у_агента,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `name` = 'girl_prompt_system'
           AND `default` LIKE '%specific about meeting%') AS в_шаблоне,
       -- ⚠ Сверка, что прежнего запрета про фото вправду нет: будь он на месте,
       -- две оговорки об одном снова заспорили бы.
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%applies to photos%') AS старый_запрет;

-- ── 1. Промпт работающего агента ────────────────────────────────────────────
--
-- Встаёт после запрета на контакты и перед «But at the same time…»: там же, где
-- стояла снятая фраза, — то есть в абзаце про то, чего девушка не делает.
UPDATE `agent`
   SET `prompt_system` = REPLACE(`prompt_system`,
       'Do not sends any addresses, phones, social contacts for dating.',
       'Do not sends any addresses, phones, social contacts for dating. You don’t promise anything specific about meeting.')
 WHERE `prompt_system` LIKE '%social contacts for dating%'
   AND `prompt_system` NOT LIKE '%specific about meeting%';

-- ── 2. Шаблон, из которого заводят новых ────────────────────────────────────
UPDATE `node_variable`
   SET `default` = REPLACE(`default`,
       'Do not sends any addresses, phones, social contacts for dating.',
       'Do not sends any addresses, phones, social contacts for dating. You don’t promise anything specific about meeting.')
 WHERE `name` = 'girl_prompt_system'
   AND `default` LIKE '%social contacts for dating%'
   AND `default` NOT LIKE '%specific about meeting%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%specific about meeting%') AS у_агента,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `name` = 'girl_prompt_system'
           AND `default` LIKE '%specific about meeting%') AS в_шаблоне,
       -- ⚠ Соседние запреты целы: правка вставляет предложение, а не переписывает
       -- абзац.
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%social contacts for dating%') AS контакты_целы,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%never agree to personal meetings%') AS встречи_целы;
