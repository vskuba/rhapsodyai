-- Сценарий «вход под анкетой» для Ladadate (2026-09-10)
--
-- ЗАЧЕМ. У сайта двенадцать сценариев, и каждый логинится сам, внутри себя. Из-за
-- этого письма и списки работают, а «войти и оставаться в сети» — нет: панель
-- ищет **отдельный** сценарий входа и не находит его. Круг расписания заходил
-- каждую минуту и каждую минуту писал в журнал «для сайта нет сценария входа» —
-- 162 записи за сутки у одной анкеты.
--
-- ⚠ ПОЧЕМУ СУЩЕСТВУЮЩИЕ НЕ ПОДОШЛИ, хотя вход в них есть. Панель узнаёт сценарий
-- входа **по именам подстановок**: годятся `login|username|email|user` и
-- `password|pass|pwd` (`rhapsody_api_scenario_login_find`). У здешних сценариев
-- они называются `profile_login` и `girl_password` — под правило не подходят, и
-- поиск честно отвечает «нет такого». Здесь имена ровно те, что панель подставит:
-- `{{login}}` и `{{password}}`.
--
-- ⚠ ВХОД ИДЁТ МОДАЛКОЙ НА ГЛАВНОЙ, А НЕ ФОРМОЙ `/signin`. Это уже выяснялось
-- разведкой при заведении сценария «анкета мужчины: карточка»: женскому кабинету
-- `/signin` отвечает «E-mail or password invalid». Поэтому шаги повторяют рабочий
-- сценарий 278 («избранные собеседники: список») — тот, которым сегодня получена
-- живая сессия: cookie сняты, страницы сайта под ними открываются.
--
-- ⚠ БАННЕР COOKIE НЕОБЯЗАТЕЛЕН. Он показывается один раз на профиль браузера, и
-- в переиспользованной вкладке его уже нет: обязательный шаг ронял бы вход через
-- раз, причём тем чаще, чем лучше работает пул.
--
-- ЧЕМ КОНЧАЕТСЯ. Заходом на `/chat` и ожиданием поля ввода `#user-message`. Это
-- не про чат, а про доказательство: страница отдаётся только вошедшему, и её
-- появление означает, что сессия настоящая. Гостя сайт молча уводит на `/signin`
-- — там этого поля нет. Та же страница потом служит присутствию (DatingAi,
-- настройка `heartbeat`), так что сценарий проверяет ровно то, чем будем жить.

SET @site = (SELECT `id` FROM `browser_site` WHERE `name` = 'Ladadate');

SELECT 'ДО' AS этап, @site AS сайт,
       (SELECT COUNT(*) FROM `browser_scenario`
         WHERE `name` = 'вход под анкетой') AS уже_есть;

INSERT INTO `browser_scenario` (`site_id`, `name`, `goal`, `start_url`, `steps`,
                                `variables`, `status`)
SELECT @site, 'вход под анкетой',
       'Войти на сайт под анкетой девушки и оставить живую сессию: по ней панель '
       'держит присутствие без браузера',
       '',
       CAST(JSON_ARRAY(
           JSON_OBJECT('action', 'goto', 'url', '{{login_url}}', 'selector', '',
                       'value', '', 'timeout_ms', 60000, 'optional', FALSE),
           JSON_OBJECT('action', 'wait_ms', 'url', '', 'selector', '',
                       'value', '4000', 'timeout_ms', 8000, 'optional', FALSE),
           -- Баннер cookie: в свежем профиле есть, в переиспользованном нет.
           JSON_OBJECT('action', 'click', 'url', '',
                       'selector', 'button.panel-cookie__button',
                       'value', '', 'timeout_ms', 8000, 'optional', TRUE),
           JSON_OBJECT('action', 'click', 'url', '',
                       'selector', 'button.header-auth__btn',
                       'value', '', 'timeout_ms', 30000, 'optional', FALSE),
           JSON_OBJECT('action', 'wait_ms', 'url', '', 'selector', '',
                       'value', '2500', 'timeout_ms', 8000, 'optional', FALSE),
           JSON_OBJECT('action', 'fill', 'url', '',
                       'selector', 'form:has(button.btn--blue) input[name=login]',
                       'value', '{{login}}', 'timeout_ms', 10000, 'optional', FALSE),
           JSON_OBJECT('action', 'fill', 'url', '',
                       'selector', 'form:has(button.btn--blue) input[name=password]',
                       'value', '{{password}}', 'timeout_ms', 10000, 'optional', FALSE),
           JSON_OBJECT('action', 'click', 'url', '',
                       'selector', 'form:has(button.btn--blue) button.btn--blue',
                       'value', '', 'timeout_ms', 45000, 'optional', FALSE),
           JSON_OBJECT('action', 'wait_ms', 'url', '', 'selector', '',
                       'value', '9000', 'timeout_ms', 15000, 'optional', FALSE),
           -- Доказательство входа: страница только для вошедших.
           JSON_OBJECT('action', 'goto', 'url', '{{login_url}}/chat', 'selector', '',
                       'value', '', 'timeout_ms', 60000, 'optional', FALSE),
           JSON_OBJECT('action', 'wait_for', 'url', '', 'selector', '#user-message',
                       'value', '', 'timeout_ms', 45000, 'optional', FALSE)
       ) AS JSON),
       CAST('{}' AS JSON), 'active'
 WHERE @site IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT `name` FROM `browser_scenario`) AS x
                    WHERE x.`name` = 'вход под анкетой');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `id` FROM `browser_scenario` WHERE `name` = 'вход под анкетой') AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario`
         WHERE `name` = 'вход под анкетой') AS шагов,
       -- Обе подстановки на месте — иначе панель сценарий не найдёт.
       (SELECT CAST(`steps` AS CHAR) LIKE '%{{login}}%' FROM `browser_scenario`
         WHERE `name` = 'вход под анкетой') AS есть_логин,
       (SELECT CAST(`steps` AS CHAR) LIKE '%{{password}}%' FROM `browser_scenario`
         WHERE `name` = 'вход под анкетой') AS есть_пароль;
