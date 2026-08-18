-- `project_task`.`pipeline_state` — новое значение `bugfixing`
--
-- Зачем вручную: `migrations/0001.sql` — схема для чистой установки, накопленную базу
-- он не догоняет. В файле значение уже описано; здесь то же самое для живой БД.
--
-- Зачем значение: багфиксер (роль `bugfixer`, агент `task_bug_fixer`) держит в нём
-- захваченный баг, пока чинит его. Своё состояние, а не `developing`: то бывает только
-- у подзадач плана, и карты возврата брошенной блокировки у корневых строк и подзадач
-- разные (`TASK_CLAIM_STATE_RECLAIM` против `TASK_CLAIM_SUBTASK_STATE_RECLAIM`).
--
-- Почему это обязательно, а не «желательно»: колонка — ENUM, и MySQL в нестрогом
-- режиме на неизвестное значение не ругается, а молча пишет пустую строку. Захват при
-- этом отрабатывает как удачный (rowcount = 1, человеческий статус меняется), но
-- строка залипает навсегда: реклейм ищет `bugfixing`, следующий тик — NULL или `new`,
-- и ни один из них пустую строку не видит. Баг остаётся в работе, которой никто не
-- делает, и вернуть его может только человек руками.
--
-- Порядок значений в списке менять нельзя: ENUM хранится числом, и перестановка
-- переписала бы состояния уже существующих строк. Новое значение только в конец.

USE `project`;

ALTER TABLE `project_task`
    MODIFY COLUMN `pipeline_state` ENUM('new','planning','plan_approval','reviewing','approved',
                                        'processing','testing','planned','developing','qa_pending',
                                        'failed_qa','blocked','done','failed','bugfixing')
        DEFAULT NULL;

-- Проверка: значение на месте, ни одна строка не потеряла состояние.
-- SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS
--  WHERE TABLE_SCHEMA = 'project' AND TABLE_NAME = 'project_task'
--    AND COLUMN_NAME = 'pipeline_state';
-- SELECT pipeline_state, COUNT(*) FROM project_task GROUP BY pipeline_state;
