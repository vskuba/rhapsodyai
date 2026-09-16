-- `dating_invite_write`: модель узнаёт время, дату, день недели и страну (2026-09-16)
--
-- ЧТО ПОКАЗАЛ ЖИВОЙ ПУЛ. Среди шаблонов на проде:
--
--     «My thoughts have turned sideways tonight, spinning loops of quiet…»
--
-- Модель писала «tonight», не зная, вечер сейчас или утро. Получатель читает
-- реплику в своё время, и «сегодня вечером» в девять утра выдаёт робота вернее
-- любой другой приметы: живой человек про время суток не ошибается.
--
-- ⚠ ТО ЖЕ САМОЕ ДАВНО СДЕЛАНО В ЧАТЕ. `dating_talk` (workflow 5) держит шаг
-- `datetime_current_get` и кладёт его ответ в промпт секцией «=== Текущее время
-- ===». Инструмент отдаёт готовую фразу по-русски:
--
--     Сегодня вторник, 16 сентября 2026 года, точное время по UTC+3: 18:30:00
--     (вечер).
--
-- То есть разом день недели, дату, время и словесное время суток — всё, о чём
-- просил заказчик. Повторяем **тот же приём тем же инструментом**: вторая
-- реализация времени разошлась бы с первой на первой же правке.
--
-- ⚠ ШАГ СТАВИМ ПЕРВЫМ, а черновик и остальные сдвигаются. Инструмент должен
-- отработать до того, как его ответ понадобится промпту; ссылки между шагами
-- идут по **id**, а не по позиции, так что сдвиг ничего не ломает.
--
-- ⚠ МЕТКА СОБИРАЕТСЯ ИЗ ID НОВОГО ШАГА (`datetime_current_get_<id>_result_str`) —
-- формат движка `{инструмент}_{шаг}_result_{ключ}`. Поэтому id берётся
-- `LAST_INSERT_ID()` после вставки, а не пишется руками: угадать его нельзя.
--
-- ЗАЧЕМ СТРАНА. Время без места половинчато: «у нас уже снег» в сентябре или
-- чужой праздник выдают так же, как перепутанный вечер. Страну передаёт панель
-- переменной `invite_country` — у неё это настройка сайта, потому что шаблон
-- один на всех девушек сайта и брать страну конкретной анкеты нельзя.
--
-- ⚠ СУДЬЯ ТОЖЕ ПОЛУЧАЕТ ВРЕМЯ, и это не лишнее. Он бракует шаблон по списку
-- правил; не зная, который час, он пропустил бы «tonight» утром — то есть ровно
-- ту беду, ради которой всё и делается.
--
-- ⚠ ЧАСОВОЙ ПОЯС ПРИХОДИТ СНАРУЖИ (`datetime_current_get_zone`, умолчание `+3`) —
-- той же переменной, что у чата. Панель передаёт свой часовой пояс, и разойтись
-- эти двое не могут.
--
-- Идемпотентность: шаг заводится по условию отсутствия, промпты переписываются
-- через REPLACE по якорю — повторный накат безопасен.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_write');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'datetime_current_get') AS шаг_времени,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ------------------------------------------- Освобождаем позицию 0
UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) s
                    WHERE s.`workflow_id` = @wf AND s.`title` = 'datetime_current_get');

-- ------------------------------------------- Сам шаг: инструмент времени
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'datetime_current_get', 0,
       JSON_OBJECT('tool_invoke',
                   JSON_OBJECT('tool_name', 'datetime_current_get',
                               'inputs_map', JSON_OBJECT('timezone', 'datetime_current_get_zone'),
                               'outputs_map', JSON_OBJECT('str', 'datetime_current_get_response')),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) s
                    WHERE s.`workflow_id` = @wf AND s.`title` = 'datetime_current_get');

-- Метка результата собирается из id шага — своего, только что заведённого, либо
-- уже стоявшего (повторный накат).
SET @now_mark = CONCAT('%datetime_current_get_',
                       (SELECT `id` FROM `agent_workflow_step`
                         WHERE `workflow_id` = @wf AND `title` = 'datetime_current_get'),
                       '_result_str%');

-- ------------------------------------------- Переменные
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'invite_country', 'workflow',
       'Откуда девушка: страна и при желании город. Настройка сайта у DatingAi', ''
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'invite_country');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('invite_country', 'datetime_current_get_zone')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ------------------------------------------- Черновик: время и страна в промпт
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(
           REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                   '=== Требуемый язык ответа (код) ===',
                   CONCAT('=== Сейчас у тебя ===\n', @now_mark, '\n\n',
                          '%if invite_country%=== Откуда ты ===\n%invite_country%\n\n%endif%',
                          '=== Требуемый язык ответа (код) ===')),
           CONCAT('10. Границы: без грубости'),
           CONCAT('10. ВРЕМЯ И МЕСТО названы выше — держись их. Пишешь про вечер ',
                  'утром или про выходной в среду — реплика выдаёт робота вернее ',
                  'всего остального: живой человек про время суток не ошибается. ',
                  'Упоминать время вовсе не обязательно; но если упоминаешь — ',
                  'только то, которое сейчас.\n',
                  '11. Границы: без грубости')))
 WHERE `workflow_id` = @wf AND `title` = 'Черновик инвайта';

-- ------------------------------------------- Судья: тоже знает, который час
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         -- ⚠ **Замены вложены, а не перечислены парами.** Два `path`/`value` на
         -- один и тот же путь в `JSON_SET` не складываются: побеждает последний,
         -- и первая правка пропала бы молча.
         REPLACE(
           REPLACE(
             REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                     '=== Что просили ===',
                     CONCAT('=== Сейчас у неё ===\n', @now_mark, '\n\n',
                            '%if invite_country%=== Откуда она ===\n%invite_country%\n\n%endif%',
                            '=== Что просили ===')),
             -- ⚠ Прежний девятый пункт (про повтор, миграция `20260916130000`)
             -- двигаем **до** вставки нового восьмого: иначе в списке окажется
             -- два «девятых». Номера тут не украшение — судья ссылается на них
             -- в `WHY`, и одинаковые сделали бы ответ неоднозначным.
             '9. Текст слишком похож на то, что уже писали раньше',
             '10. Текст слишком похож на то, что уже писали раньше'),
           '8. Текст пресный и не цепляет',
           CONCAT('8. Время или место названы неверно: «сегодня вечером» утром, ',
                  '«хороших выходных» в среду, чужой сезон или чужой праздник. ',
                  'Сверься с временем и страной выше — это брак, и заметный.\n',
                  '9. Текст пресный и не цепляет')))
 WHERE `workflow_id` = @wf AND `title` = 'Судья';

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап, @now_mark AS метка,
       (SELECT `position` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'datetime_current_get') AS позиция_времени,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%Сейчас у тебя%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Черновик инвайта') AS время_у_черновика,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%Сейчас у неё%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Судья') AS время_у_судьи;

SELECT `position`, `title` FROM `agent_workflow_step`
 WHERE `workflow_id` = @wf ORDER BY `position`;
