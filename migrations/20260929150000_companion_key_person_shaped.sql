-- Ключ собеседника становится «номер + имя», как у девушки (2026-09-29)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Шаг «Переменные» у `dating_talk` клеит ключи обеих сторон **одной выкройкой**:
--
--     companion_unique_id = %companion_id%_%companion_name%
--     girl_unique_id      = %girl_id%_%girl_name%
--
-- У девушки выходило `643694_diana`, у собеседника — `10_dating_343_128282`.
-- Панель присылала в `companion_id` мёртвую константу `10` (номер единственной
-- общей записи `dating_person`, которую движок больше не резолвит: `remove_companion`,
-- `agent_session_companion_drop`), а в `companion_name` — **весь ключ целиком**, с
-- приставкой и сайтом, вместо имени. То есть половины склейки значили не то, что
-- у девушки: слева константа, справа ключ, а имени в ключе не было вовсе.
--
-- Это ровно та беда, которую эта же цепочка уже записала своими словами
-- (`…_wf_talk_companion_key`): «в „имени собеседника“ лежал ключ
-- `dating_343_128282`, и всякий, кто правил промпт, видел не то, что там на самом
-- деле». У девушки её починили (`…_wf_talk_girl_title`), у собеседника — нет.
--
-- Панель починена (`DatingAi/src/dating/companion_ref.py`): `companion_id` — номер
-- на сайте, `companion_name` — имя латиницей строчными той же функцией `agent_key`,
-- что собирает `girl_name`. Ключ стал `128282_gerard`.
--
-- ## ⚠⚠⚠ ЧТО ПОТЕРЯЕТСЯ БЕЗ ЭТОЙ МИГРАЦИИ
--
-- **Переписка.** `companion_session` находит пару через `companion.unique_id`
-- (`companion_session._companion_id`): не нашлось — `companion_create` заводит
-- **новую** запись. Со сменой ключа все накопленные разговоры остались бы висеть на
-- старых записях, а агент начал бы с чистого листа — «женщина, с которой он
-- переписывался, пишет ему как незнакомому», то есть в точности та беда, от которой
-- заводили `companion_session`.
--
-- На проде это 212 обменов на 80 парах, 47 записей собеседников.
--
-- ⚠ **Фактов это не касается:** коллекции `dating_companion` и `dating_talk` на проде
-- пусты (0 точек), а `dating_girl` ключуется девушкиным ключом, который не меняется.
-- Сиротить в Qdrant нечего — проверено переписью перед выкладкой.
--
-- ## ⚠⚠ Почему пары перечислены поимённо, а не считаются в SQL
--
-- Потому что `LOWER(REPLACE(TRIM(title), ' ', '_'))` — **не** то же, что `agent_key`.
-- На проде есть `René`: наш транслит даёт `ren` (всё, что не латиница и не цифра,
-- выбрасывается — ключ уезжает в `document_id` Qdrant), а SQL дал бы `rené`. Разойдись
-- миграция с кодом на одну эту строку, и переписка этой пары потерялась бы молча —
-- запись нашлась бы «не та», и агент завёл бы третью.
--
-- Поэтому пары посчитаны **самим кодом панели** и вписаны сюда значениями. Список
-- снят с прода 47 строками, все с непустым `title`, новые ключи различны — то
-- есть переименование ни во что не упирается.
--
-- ## Идемпотентность и порядок выкладки
--
-- Миграция переживает повторный прогон: второй раз строк со старым ключом уже нет.
-- Порядок выкладки она **не** диктует — если панель успела прислать новый ключ раньше
-- и запись под ним уже завелась, шаг 2 переносит обмены на неё, а пустую старую
-- убирает шаг 3. Поэтому «сосед раньше панели» желательно, но не обязательно.
--
-- ⚠ `dating_person` (id 10) остаётся в справочнике: сессий на нём нет (проверено), а
-- ссылаться на него после правки панели больше некому. Пусть лежит — удаление
-- ничего не чинит.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `companion`
         WHERE `unique_id` LIKE '10\_dating\_%') AS старых_ключей,
       (SELECT COUNT(*) FROM `companion_session` s
          JOIN `companion` c ON c.`id` = s.`companion_id`
         WHERE c.`unique_id` LIKE '10\_dating\_%') AS обменов_под_ними,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов_всего;

-- ── Пары «как было → как станет» ────────────────────────────────────────────
--
-- ⚠ Таблица обычная, а не временная: файл гонится не обязательно одним
-- подключением, и полагаться на живучесть временной таблицы незачем — цена
-- вопроса одна строка `DROP` в конце.
--
-- ⚠⚠ Страховка перед `DROP IF EXISTS`: имя помощника обязано быть свободно.
-- Окажись под ним настоящая таблица — `DROP IF EXISTS` снёс бы её молча, и
-- «помощник разовой миграции» стал бы самым дорогим запросом в файле. Оказаться
-- она там может ровно одним способом: прерванным прогоном этой же миграции, и
-- тогда снести её как раз правильно, — поэтому здесь отчёт, а не отказ.
SELECT IF(COUNT(*) = 0, 'имя свободно',
          'уже есть — прерванный прогон этой же миграции, сносим') AS помощник
  FROM `information_schema`.`TABLES`
 WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion_key_move';

DROP TABLE IF EXISTS `companion_key_move`;

CREATE TABLE `companion_key_move` (
  `old_key` varchar(190) NOT NULL,
  `new_key` varchar(190) NOT NULL,
  PRIMARY KEY (`old_key`),
  UNIQUE KEY `uq_companion_key_move_new` (`new_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='Разовая: перевод ключей собеседников в вид «номер + имя»';

-- ⚠ Точка с запятой — отдельной строкой: у каждой пары справа `--` с именем, и
-- припиши её к последней строке, она уехала бы в комментарий (как и запятые).
INSERT INTO `companion_key_move` (`old_key`, `new_key`) VALUES
  ('10_dating_343_329110', '329110_brian_ritter'),  -- Brian Ritter
  ('10_dating_343_587317', '587317_victor'),  -- Victor
  ('10_dating_343_362943', '362943_frank'),  -- Frank
  ('10_dating_343_343150', '343150_gary_kerns'),  -- Gary Kerns
  ('10_dating_343_128282', '128282_gerard'),  -- Gerard
  ('10_dating_343_100753', '100753_mark_liu'),  -- Mark Liu
  ('10_dating_343_849892', '849892_john'),  -- John
  ('10_dating_343_421674', '421674_christopher'),  -- Christopher
  ('10_dating_343_566216', '566216_greg'),  -- Greg
  ('10_dating_343_604366', '604366_henry'),  -- Henry
  ('10_dating_343_555464', '555464_r'),  -- R
  ('10_dating_343_790088', '790088_claude'),  -- Claude
  ('10_dating_343_300288', '300288_mohamad'),  -- Mohamad
  ('10_dating_343_169410', '169410_zahir'),  -- Zahir
  ('10_dating_343_768039', '768039_joel'),  -- Joel
  ('10_dating_343_608433', '608433_michael'),  -- Michael
  ('10_dating_343_934399', '934399_manoel_pedroza'),  -- Manoel Pedroza
  ('10_dating_343_549126', '549126_mark'),  -- Mark
  ('10_dating_343_473269', '473269_patrick'),  -- Patrick
  ('10_dating_343_225245', '225245_edward_brooks'),  -- Edward Brooks
  ('10_dating_343_501093', '501093_mike'),  -- Mike
  ('10_dating_343_283278', '283278_waltertrollip'),  -- Waltertrollip
  ('10_dating_343_204343', '204343_gary_jensen'),  -- Gary Jensen
  ('10_dating_343_350638', '350638_kari'),  -- Kari
  ('10_dating_343_208206', '208206_stein_nordhagen'),  -- Stein Nordhagen
  ('10_dating_343_635295', '635295_ren'),  -- René
  ('10_dating_343_102770', '102770_wolfgang'),  -- Wolfgang
  ('10_dating_343_869661', '869661_michael_davies'),  -- Michael Davies
  ('10_dating_343_729071', '729071_wittels'),  -- Wittels
  ('10_dating_343_284196', '284196_bauer_franz'),  -- Bauer Franz
  ('10_dating_343_514296', '514296_richie'),  -- Richie
  ('10_dating_343_102921', '102921_simon'),  -- Simon
  ('10_dating_343_506561', '506561_don'),  -- Don
  ('10_dating_343_812886', '812886_vincent_pitchen'),  -- Vincent Pitchen
  ('10_dating_343_625499', '625499_angelas'),  -- Angelas
  ('10_dating_343_876369', '876369_toni'),  -- Toni
  ('10_dating_343_103771', '103771_randyl'),  -- Randyl
  ('10_dating_343_198770', '198770_ivor'),  -- Ivor
  ('10_dating_343_148876', '148876_tarmo'),  -- Tarmo
  ('10_dating_343_880212', '880212_robert'),  -- Robert
  ('10_dating_343_997573', '997573_marc'),  -- Marc
  ('10_dating_343_967696', '967696_michael'),  -- Michael
  ('10_dating_343_326531', '326531_martin'),  -- Martin
  ('10_dating_343_158678', '158678_marco'),  -- Marco
  ('10_dating_343_102022', '102022_roger_awah'),  -- Roger Awah
  ('10_dating_343_616312', '616312_jorge'),  -- Jorge
  ('10_dating_343_260381', '260381_skyswiss')  -- Skyswiss
;

-- ── 1. Переименование: новый ключ свободен ──────────────────────────────────
--
-- ⚠ Анти-джойн, а не подзапрос: MySQL не даёт читать в подзапросе ту таблицу,
-- которую правит этот же `UPDATE`.
UPDATE `companion` c
  JOIN `companion_key_move` m ON m.`old_key` = c.`unique_id`
  LEFT JOIN `companion` taken ON taken.`unique_id` = m.`new_key`
   SET c.`unique_id` = m.`new_key`
 WHERE taken.`id` IS NULL;

-- ── 2. Слияние: под новым ключом уже завелась запись ────────────────────────
--
-- ⚠⚠ Обмены переносим **до** удаления: связь `companion_session` → `companion`
-- стоит с `ON DELETE CASCADE`, и снеси мы старую запись первой, переписка уехала
-- бы вместе с ней — тихо и безвозвратно.
UPDATE `companion_session` s
  JOIN `companion` old ON old.`id` = s.`companion_id`
  JOIN `companion_key_move` m ON m.`old_key` = old.`unique_id`
  JOIN `companion` fresh ON fresh.`unique_id` = m.`new_key`
   SET s.`companion_id` = fresh.`id`;

-- ⚠ И нашу сторону тем же приёмом. Сейчас владельцами стоят только девушки
-- (проверено: 0 сессий с владельцем-собеседником), но правило «ключ переехал»
-- обязано быть одним на оба столбца — иначе половина обменов осталась бы висеть
-- на записи, которую шаг 3 сочтёт пустой.
UPDATE `companion_session` s
  JOIN `companion` old ON old.`id` = s.`owner_id`
  JOIN `companion_key_move` m ON m.`old_key` = old.`unique_id`
  JOIN `companion` fresh ON fresh.`unique_id` = m.`new_key`
   SET s.`owner_id` = fresh.`id`;

-- ── 3. Пустые старые записи убрать ──────────────────────────────────────────
--
-- ⚠ Только те, на которых **не осталось** обменов: условие здесь не украшение, а
-- предохранитель против каскада.
DELETE old FROM `companion` old
  JOIN `companion_key_move` m ON m.`old_key` = old.`unique_id`
 WHERE NOT EXISTS (SELECT 1 FROM `companion_session` s
                    WHERE s.`companion_id` = old.`id` OR s.`owner_id` = old.`id`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion`
         WHERE `unique_id` LIKE '10\_dating\_%') AS старых_осталось,
       (SELECT COUNT(*) FROM `companion` c
          JOIN `companion_key_move` m ON m.`new_key` = c.`unique_id`) AS переехало,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов_всего,
       -- ⚠⚠ Главная примета: обмены обязаны остаться достижимы по НОВОМУ ключу.
       -- Столько же, сколько было под старым, — значит ничего не потерялось.
       (SELECT COUNT(*) FROM `companion_session` s
          JOIN `companion` c ON c.`id` = s.`companion_id`
          JOIN `companion_key_move` m ON m.`new_key` = c.`unique_id`)
         AS обменов_по_новому,
       (SELECT COUNT(*) FROM `companion_session` s
         WHERE NOT EXISTS (SELECT 1 FROM `companion` c WHERE c.`id` = s.`companion_id`))
         AS обменов_осиротело;

-- ⚠ Показываем десяток переехавших: ключ обязан читаться человеком.
SELECT c.`id`, m.`old_key`, c.`unique_id` AS новый_ключ, c.`title`
  FROM `companion` c JOIN `companion_key_move` m ON m.`new_key` = c.`unique_id`
 ORDER BY c.`id` LIMIT 10;

-- ── ⚠⚠⚠ Отставшие: завелись после того, как список был снят ─────────────────
--
-- Список пар снят с прода заранее, а чат в это время работает: собеседник, впервые
-- написавший между снятием и выкладкой, получит старый ключ, которого в списке нет.
-- Переписки у такого ровно один-два обмена, но потерять и их незачем.
--
-- ⚠ Сами их не переименовываем, и это осознанно. Повторить `agent_key` выражением
-- SQL можно **только** для латиницы: кириллицу он переводит по таблице
-- (`Євген` → `yevhen`), а `REGEXP_REPLACE` её просто выбросил бы — ключ вышел бы
-- другим, и перенос увёл бы переписку в третью запись. Отличить один случай от
-- другого в SQL можно, но цена ошибки здесь — молча разошедшиеся ключи, а цена
-- отчёта — одна строка глазами.
--
-- Поэтому: показываем. Не пусто — пересобрать миграцию генератором на свежем
-- срезе (`tool_/…/make_migration.py`) и применить ещё раз.
SELECT 'отставшие' AS проверка, COUNT(*) AS сколько,
       COALESCE(GROUP_CONCAT(CONCAT(`unique_id`, ' («', `title`, '»)')
                             ORDER BY `id` SEPARATOR '; '), '—') AS какие
  FROM `companion` WHERE `unique_id` LIKE '10\_dating\_%';

DROP TABLE `companion_key_move`;
