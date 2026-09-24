-- Жребий письма: разнообразие задаёт шаг, а не уговоры модели (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Письма избранным вышли на одно лицо. Пять из восьми, снятых с прода подряд,
-- открываются одним оборотом:
--
--     I was sitting here with a cup of tea… and suddenly remembered
--     I was just sitting with my coffee in the evening, thinking about
--     I was drinking my evening tea in Kyiv and suddenly thought about
--
-- Это структура **единственного примера** в конце промпта. Образец работает
-- выкройкой, хотя рядом и написано «показывает ФОРМАТ, а не длину».
--
-- ⚠⚠ **Просить модель «быть разной» бесполезно** — закон, измеренный трижды:
-- три шаблона инвайтов из трёх начинались с «you're trouble»; вилка «от абзаца
-- до трёх» дала девять писем из двенадцати ровно в три абзаца. Выбирать обязан
-- кто-то снаружи модели.
--
-- ## ⚠ Жребий тут был и потерялся
--
-- До переезда писем на `dating_talk` его бросала панель: три настройки сайта
-- живы в реестре DatingAi и сегодня — `favorite_mail_name_percent` (10),
-- `_question_percent` (25), `_story_percent` (40). Переезд унёс код, а настройки
-- остались: `percent_share` в `favorite_mail.py` **импортирован и ни разу не
-- вызван**. То есть ручки на странице сайта крутятся, ни на что не влияя.
--
-- Доли ниже — те самые, и восемь тем рассказа взяты из `FAVORITE_MAIL_STORIES`
-- слово в слово. Это возврат прежнего поведения, а не новое.
--
-- ## Как устроено
--
-- Шаг `dice` бросает жребий и кладёт по переменной на ось. Промпты веток письма
-- читают их готовыми — выбора модели нигде нет.
--
-- ⚠ **Имена с приставкой `dice_`** — соглашение проекта. Встретив в промпте
-- `%dice_mail_story%`, человек сразу знает: значение не прислали снаружи и не
-- придумала модель, его бросил шаг жребия, и настроено оно там. Без приставки
-- переменная неотличима от входящей, и искать её начинают в панели.
--
-- ⚠⚠ У `dice_mail_story` доли дают **40, а не 100**, и это намеренно: в остальных
-- 60% переменная приходит пустой, `%if dice_mail_story%` читает это как «рассказа не
-- надо», и абзац из промпта исчезает. Так доля рассказа задаётся одним числом
-- вместо варианта-пустышки «не рассказывай о себе» — а запрет в промпте модель
-- ещё и выполняет хуже, чем отсутствие просьбы.
--
-- ## ⚠ Почему доли числами, а не метками настроек
--
-- Инструмент умеет брать долю из переменной (`"%имя%"`), и для посайтовых
-- настроек это верный путь. Но пара «да/нет» так не выражается: доли обязаны
-- укладываться в сотню, а `{вопрос: %percent%, без вопроса: 75}` при настройке
-- 40 даёт 115 — и заход упадёт. Нужна либо вторая метка с дополнением, либо
-- право задать один вариант и оставить остальное недобору. Решение за человеком,
-- пока — числа, равные нынешним умолчаниям.
--
-- ## ⚠ Чего эта миграция не делает
--
-- Не трогает судью (шаг «Валидация ответа»). Он жребия не видит и, переписывая
-- черновик, просит «письмо от абзаца до трёх» — ту самую вилку. Пока он правит
-- редко, разнообразие держится; сделается это отдельно и осознанно.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @tool = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'tool_invoke');
SET @dice = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` = 'Жребий письма' LIMIT 1);

-- ⚠ Место жребия — **перед развилкой**: `transitions_before` шага «Ответ в чат»
-- разводит четыре ветки, и бросок обязан случиться раньше. Номер снимаем до
-- сдвига: в одном `UPDATE` читать ту же таблицу MySQL не даёт.
SET @at = (SELECT `position` FROM `agent_workflow_step`
            WHERE `workflow_id` = @wf AND `title` = 'Ответ в чат' LIMIT 1);

SELECT 'ДО' AS этап, @at AS место_жребия,
       COALESCE(@dice, 0) AS шаг_уже_есть,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf)
         AS шагов;

-- ── Переменные жребия ───────────────────────────────────────────────────────
--
-- ⚠ Тип `workflow`, а не `input`: их кладёт шаг внутри прогона, снаружи их не
-- присылают. Умолчание — пустая строка: `%if%` читает её как ложь, а `NULL`
-- приехал бы в промпт словом «None».
--
-- ⚠⚠ Объявление нужно не движку (он положит значение и без него), а **человеку**:
-- необъявленной переменной нет в списке редактора, и промпт ссылался бы на то,
-- чего в списке не видно. Заодно `%if dice_mail_story%` осмыслен и до броска.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_opening', 'workflow', '', 'Зачин письма. Жребий шага «Жребий письма»'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_opening');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_name', 'workflow', '', 'Звать ли собеседника по имени. Жребий шага'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_name');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_question', 'workflow', '', 'Чем кончить письмо. Жребий шага'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_question');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_story', 'workflow', '',
       'Тема рассказа о себе; пусто — рассказа нет. Жребий шага' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_story');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('dice_mail_opening', 'dice_mail_name', 'dice_mail_question', 'dice_mail_story')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = @wf);

-- ── Место под шаг ───────────────────────────────────────────────────────────
--
-- ⚠⚠ Сдвиг идёт **только когда шага ещё нет**: без этой оговорки второй прогон
-- раздвинул бы позиции снова, и жребий отстал бы от развилки на шаг.
UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= @at AND @dice IS NULL;

-- ── Сам шаг ─────────────────────────────────────────────────────────────────
--
-- ⚠ Описание жребия уходит литералом `_const_` — движок так и отличает
-- постоянное значение от имени переменной (`ai_framework_manager`).
--
-- ⚠⚠ Строкой целиком, **без промежуточной `@переменной`**. Ровно на ней сегодня
-- сломались три ветки: `SET @json = (SELECT JSON_EXTRACT(…))` свернул массив в
-- текст, потому что пользовательская переменная MySQL не держит тип JSON.
-- Здесь нужна именно строка, но привычку заводить не будем.
--
-- ⚠ Выходы зовутся теми же именами, что переменные: иначе в промпте пришлось бы
-- писать `%dice_<шаг>_result_<имя>%`, где номер шага свой у каждой базы — та
-- самая ссылка, что ведёт в пустоту после переноса.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'Жребий письма', @at,
       JSON_OBJECT(
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'dice',
           'inputs_map', JSON_OBJECT('spec', '_const_{"dice_mail_opening": {"начни с того, чем она была занята, когда вспомнила о нём": 20, "начни сразу с мысли или вопроса — без предисловия о себе": 20, "начни с того, что рассказывал он, и вернись к этому": 20, "начни с короткой новости о себе, будто с порога": 20, "начни с наблюдения о нём — что ей в нём показалось": 20}, "dice_mail_name": {"назови его по имени один раз, в первой фразе": 10, "по имени не обращайся вовсе": 90}, "dice_mail_question": {"закончи письмо вопросом к нему": 25, "закончи письмо утверждением, признанием или рассказом — без вопроса": 75}, "dice_mail_story": {"как прошёл её день — обычные мелочи, без событий": 5, "забавный случай, который приключился с ней на днях": 5, "чего ей хочется: желание, мечта, то, о чём думает перед сном": 5, "случай из жизни, который она запомнила надолго": 5, "её опыт общения с мужчинами: что нравится, что отталкивает": 5, "её привычка или маленькая странность, о которой мало кто знает": 5, "что она делала на выходных или собирается делать": 5, "место, куда ей хочется съездить, и почему именно туда": 5}}'),
           'outputs_map', JSON_OBJECT('dice_mail_opening', 'dice_mail_opening',
                                      'dice_mail_name', 'dice_mail_name',
                                      'dice_mail_question', 'dice_mail_question',
                                      'dice_mail_story', 'dice_mail_story')),
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY())
 WHERE @at IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT 1) AS x
                    WHERE EXISTS (SELECT 1 FROM `agent_workflow_step`
                                   WHERE `workflow_id` = @wf
                                     AND `title` = 'Жребий письма'));

-- ── Промпт «Письмо первым»: все четыре оси ──────────────────────────────────
--
-- ⚠ Правим `REPLACE`-ом по якорю, а не переписываем промпт целиком: так правка
-- видна в diff строкой, а не шестью килобайтами, и повтор её не задваивает —
-- якоря после первого прогона уже нет.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '=== Important information about final response ===',
                 '=== Жребий этого письма ===
⚠ Это не пожелания, а заказ: что выпало, то и делай.
- Зачин: %dice_mail_opening%
- Обращение: %dice_mail_name%
- Концовка: %dice_mail_question%
%if dice_mail_story%- Расскажи о себе. Тема: %dice_mail_story%. Это то, чем письмо отличается от реплики в чате: в нём есть место для жизни.
%endif%
=== Important information about final response ==='))
 WHERE `workflow_id` = @wf AND `title` = 'Письмо первым'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%dice_mail_opening%';

-- ── Промпт «Ответ на письмо»: три оси ───────────────────────────────────────
--
-- ⚠ Зачина здесь нет намеренно: он **ответ**, и начало ему задаёт письмо
-- собеседника, а не жребий. Навязанный зачин увёл бы от того, что он написал, —
-- ровно от того, ради чего человек и открыл почту.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '=== Important information about final response ===',
                 '=== Жребий этого письма ===
⚠ Это не пожелания, а заказ: что выпало, то и делай.
- Обращение: %dice_mail_name%
- Концовка: %dice_mail_question%
%if dice_mail_story%- Расскажи о себе. Тема: %dice_mail_story%. Ответить на его письмо — не значит говорить только о нём.
%endif%
=== Important information about final response ==='))
 WHERE `workflow_id` = @wf AND `title` = 'Ответ на письмо'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%dice_mail_question%';

-- ── Образец больше не задаёт зачин ──────────────────────────────────────────
--
-- ⚠⚠ Это и есть корень одинаковости. Пока в промпте один пример, модель берёт
-- из него не формат, а выкройку — оговорка «показывает ФОРМАТ» её не
-- останавливает, потому что спорит с самим примером, а не убирает его.
-- Жребий даёт зачин прямым указанием; здесь остаётся сказать, что заданное
-- важнее образца.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '⚠ Образец ниже показывает ФОРМАТ ответа, а не длину письма: сколько в нём',
                 '⚠⚠ С образца ниже берут ТОЛЬКО формат JSON. Ни зачина, ни длины,
ни хода мысли с него брать нельзя: они заданы выше, и заданное важнее
образца. Сколько в письме'))
 WHERE `workflow_id` = @wf
   AND `title` IN ('Письмо первым', 'Ответ на письмо');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `position` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Жребий письма') AS место,
       (SELECT `position` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Ответ в чат') AS развилка_после,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
         WHERE s.`workflow_id` = @wf
           AND s.`title` IN ('Письмо первым', 'Ответ на письмо')
           AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`, '$.prompt_user'))
               LIKE '%dice_mail_story%') AS веток_с_жребием,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
         GROUP BY `position` HAVING COUNT(*) > 1 LIMIT 1) AS позиции_столкнулись;
