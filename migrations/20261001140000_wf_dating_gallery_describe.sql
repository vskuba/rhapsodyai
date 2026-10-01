-- Workflow `dating_gallery_describe`: что на фотографии девушки (2026-10-01)
--
-- ЗАЧЕМ. У панели DatingAi появилась вкладка «Галерея»: фотографии девушки с
-- Google Диска. У каждого снимка должны быть описание и теги — ими оператор
-- ищет нужный кадр, не открывая сорок плиток подряд. Пишет их vision-модель.
--
-- ⚠⚠ ПОЧЕМУ ИНСТРУМЕНТ, А НЕ ШАГ. Шага, передающего картинку модели, у движка
-- нет вовсе: `llm_to_image` — это **генерация** (текст → картинка), обратного
-- типа не существует. Приём изображения знает только реестр моделей (колонка
-- `input_type`), но до шагов это не доходит. Поэтому цепочка стоит на
-- `tool_invoke` с инструментом `vision_describe` — движок не тронут.
--
-- ⚠ ПОЧЕМУ ОДИН ШАГ, А НЕ ДВА. Судьи здесь нет намеренно, в отличие от инвайтов
-- и шаблонов писем. Там текст уходит полусотне живых людей без человеческого
-- взгляда, и брак портит весь пул. Здесь результат читает **оператор** в
-- карточке анкеты, он же и правит его руками — а правка сильнее разбора:
-- панель метит такую строку (`edited_at`) и больше её модели не отдаёт.
--
-- ⚠ ПОЧЕМУ ОТВЕТ ОТДАЁТСЯ СТРОКОЙ ИНСТРУМЕНТА, А НЕ СОБИРАЕТСЯ ШАБЛОНОМ.
-- Инструмент возвращает готовый `json`, и шаг выдачи просто его пересылает.
-- Собирай мы JSON шаблоном из отдельных переменных, первая же кавычка или
-- перенос строки в описании сломали бы разбор на стороне панели.
--
-- ЧТО ПРИХОДИТ ОТ ПАНЕЛИ. Переменная `image` — кадр как `data:`-URI, ужатый до
-- 800 пикселей по длинной стороне (~70 КБ base64). Больше незачем: модель всё
-- равно ужимает кадр, а переменная целиком ложится в трассу прогона.
--
-- Идемпотентность: всё вставляется по условию отсутствия.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow`
         WHERE `name` = 'dating_gallery_describe') AS workflow_есть,
       (SELECT COUNT(*) FROM `tool` WHERE `name` = 'vision_describe') AS инструмент_в_реестре;

-- ------------------------------------------- Сам workflow
INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`, `position`, `subflow`)
SELECT 2, 'dating_gallery_describe', 'Галерея: что на фото',
       'Описание и теги фотографии девушки с Google Диска. Для вкладки '
       '«Галерея» в карточке анкеты DatingAi',
       0, 0
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow`
                    WHERE `name` = 'dating_gallery_describe');

SET @wf = (SELECT `id` FROM `agent_workflow`
            WHERE `name` = 'dating_gallery_describe');

-- ------------------------------------------- Шаг 1: зрение
--
-- ⚠ `prompt` берётся переменной, а не зашит здесь. Просьба живёт в панели
-- (`src/dating/gallery_vision.py`): она знает, какие поля кладёт в колонки, и
-- менять их в двух местах значило бы однажды разойтись. Workflow отвечает за
-- дорогу, а не за то, о чём спрашивают.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Смотрим снимок', 0,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'vision_describe',
           'inputs_map', JSON_OBJECT('image', 'image', 'prompt', 'prompt')))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 0);

SET @look = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `position` = 0);

-- ------------------------------------------- Шаг 2: отдать ответ
--
-- ⚠⚠ Имя переменной несёт **номер шага** (`{tool}_{step_id}_result_{key}`) —
-- так движок делает её уникальной, чтобы повторные вызовы одного инструмента
-- не затирали друг друга. Номер известен только после вставки, поэтому имя
-- собирается здесь из `@look`, а не записано строкой.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 4, 'Ответ', 1,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'continue_workflow', false,
         'prompt_user', CONCAT('%vision_describe_', @look, '_result_json%'))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 1);

-- ------------------------------------------- Переменные входа
--
-- Объявляем обе: движок проверяет контракт входа, а необъявленная переменная
-- в промпте остаётся сырой меткой — её значок «дырка в переменной» и ловит.
INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @wf, 'image', 'input', '',
       'Кадр как data:-URI (data:image/jpeg;base64,...). Кладёт панель, ужав '
       'до 800 px по длинной стороне: больше незачем, а переменная целиком '
       'ложится в трассу прогона'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `workflow_id` = @wf AND `name` = 'image');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @wf, 'prompt', 'input', '',
       'О чём спрашиваем модель, с перечислением нужных полей. Живёт в панели '
       '(gallery_vision.py): она знает, какие поля кладёт в колонки'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `workflow_id` = @wf AND `name` = 'prompt');

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow`
         WHERE `name` = 'dating_gallery_describe') AS workflow_стало,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `workflow_id` = @wf) AS переменных;
