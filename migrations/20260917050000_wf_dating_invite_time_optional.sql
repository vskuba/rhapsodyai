-- `dating_invite_write`: время показываем не всегда, а по жребию (2026-09-17)
--
-- ЧТО ПОКАЗАЛ ЖИВОЙ ПУЛ. После того как агент стал получать текущее время, он
-- принялся его поминать: **94 инвайта из 202 за сутки** содержали «tonight»,
-- «this Wednesday», «good morning». Почти каждый второй.
--
-- ⚠ ЭТО НЕ ОШИБКА МОДЕЛИ, А СЛЕДСТВИЕ ПОДСКАЗКИ. Дай ей сведение — она сочтёт
-- его нужным и вставит: то же самое было с именами («вставляй изредка» →
-- вставляет всегда) и с приёмом захода («будь разной» → три «you're trouble»
-- подряд). Просить «поминай время пореже» бессмысленно по той же причине:
-- частота у модели не считается, она стилистическая.
--
-- КАК ЛЕЧИТСЯ. Тем же приёмом, что и остальное: **жребий бросает панель**. В
-- одном инвайте из десяти (настройка `invite_time_percent`) время уезжает в
-- промпт, в остальных его там нет вовсе — и помянуть его модель не может.
--
-- ⚠ ВРЕМЯ НУЖНО ИМЕННО ТОГДА, КОГДА ЕГО ПОМИНАЮТ. Убрать совсем нельзя: «доброе
-- утро» в девять вечера выдаёт робота вернее всего остального, и ради этого
-- время и заводили. Речь о доле, а не о наличии.
--
-- ЧТО СТАВИМ. Обе секции — у черновика и у судьи — под условие `%if invite_time%`.
-- Флаг кладёт панель: непустая строка — показываем, пустая — нет.
--
-- ⚠ У СУДЬИ ТОЖЕ УСЛОВНО, И ЭТО ОБЯЗАТЕЛЬНО. Видь он время там, где черновик его
-- не видел, — забраковал бы текст за «неверное время», которого автор знать не
-- мог. Правка ушла бы в никуда: на второй заход время снова не пришло бы.
--
-- ⚠ САМ ШАГ `datetime_current_get` ОСТАЁТСЯ. Он дёшев (счёт в памяти, без сети), а
-- убрать его значило бы сломать метку в промпте: она собрана из его id.
--
-- Идемпотентность: условие ставится по якорю и только если его ещё нет
-- (`NOT LIKE '%invite_time%'`), повторный накат ничего не меняет.
--
-- ⚠⚠ ПОЧЕМУ ЗДЕСЬ НЕТ «СХЛОПЫВАНИЯ ДУБЛЕЙ». Прежняя миграция
-- (`20260916200000`) вставляла секцию времени без такой проверки, и накат руками
-- второй раз оставлял две секции подряд. Соблазн дописать сюда `REPLACE`,
-- убирающий повтор, велик — но он опасен ровно тем же: шаблон повтора совпадает
-- и с **единственной** секцией, если она стоит следом за другим `%endif%`.
-- Проверено на своей же машине: такая уборка съела секцию у судьи.
--
-- Дубль лечится не миграцией, а восстановлением промпта из рабочей базы — там он
-- верный, потому что накатчик дважды не накатывает.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_write');
SET @mark = CONCAT('%datetime_current_get_',
                   (SELECT `id` FROM `agent_workflow_step`
                     WHERE `workflow_id` = @wf AND `title` = 'datetime_current_get'),
                   '_result_str%');

SELECT 'ДО' AS этап, @wf AS workflow, @mark AS метка,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%invite_time%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Черновик инвайта') AS уже_условно;

-- ------------------------------------------- Переменная-флаг
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'invite_time', 'workflow',
       'Показывать ли текущее время в этом инвайте. Жребий бросает DatingAi', ''
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'invite_time');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'invite_time'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ------------------------------------------- Черновик: время под условием
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 CONCAT('=== Сейчас у тебя ===\n', @mark, '\n\n'),
                 CONCAT('%if invite_time%=== Сейчас у тебя ===\n', @mark,
                        '\n\n%endif%')))
 WHERE `workflow_id` = @wf AND `title` = 'Черновик инвайта'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) NOT LIKE '%invite_time%';

-- ⚠ Правило про время тоже под условие: без времени в промпте оно ссылается на
-- то, чего нет, и модель ищет несуществующую секцию.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '10. ВРЕМЯ И МЕСТО названы выше',
                 '10. %if invite_time%ВРЕМЯ и %endif%МЕСТО названо выше'))
 WHERE `workflow_id` = @wf AND `title` = 'Черновик инвайта'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%10. ВРЕМЯ И МЕСТО названы выше%';

-- ------------------------------------------- Судья: тем же условием
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 CONCAT('=== Сейчас у неё ===\n', @mark, '\n\n'),
                 CONCAT('%if invite_time%=== Сейчас у неё ===\n', @mark,
                        '\n\n%endif%')))
 WHERE `workflow_id` = @wf AND `title` = 'Судья'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) NOT LIKE '%invite_time%';

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%if invite_time%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Черновик инвайта') AS черновик_условно,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%if invite_time%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Судья') AS судья_условно,
       -- ⚠ Секция обязана быть **одна**: две читаются как второе задание.
       (SELECT (CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))) -
                CHAR_LENGTH(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                                    'Сейчас у тебя', ''))) / CHAR_LENGTH('Сейчас у тебя')
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Черновик инвайта') AS секций_времени;
