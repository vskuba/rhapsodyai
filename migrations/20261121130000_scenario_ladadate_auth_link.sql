-- Ladadate: кнопка «Sign in» стала ссылкой — сценарии входа ищут её по классу (2026-11-21)
--
-- ЗАЧЕМ. 20.11.2026 около 12:00 UTC сайт заменил `<button class="header-auth__btn">`
-- на `<a href="/signin" class="header-auth__btn" onclick="MicroModal.show('modal-login')">`.
-- Сценарии искали `button.header-auth__btn` и с этого часа падали на шаге
-- «открыть окно входа» у всех 21 анкеты: Timeout 30000ms, анкеты сутки вне сети.
--
-- ЧТО. Селектор — по классу без тега: `.header-auth__btn` находит и ссылку, и
-- прежнюю кнопку. Проверено браузером соседа: окно входа открывается, поля
-- `login`, `password` и кнопка `btn--blue` на месте и видимы.
--
-- ⚠ Повторный прогон безопасен: после замены условие `LIKE` не находит ничего.

SELECT 'ДО' AS этап, COUNT(*) AS сценариев FROM `browser_scenario`
 WHERE CAST(`steps` AS CHAR) LIKE '%button.header-auth\_\_btn%';

UPDATE `browser_scenario`
   SET `steps` = CAST(REPLACE(CAST(`steps` AS CHAR), '"button.header-auth__btn"', '".header-auth__btn"') AS JSON)
 WHERE CAST(`steps` AS CHAR) LIKE '%button.header-auth\_\_btn%';

SELECT 'ПОСЛЕ' AS этап, COUNT(*) AS сценариев FROM `browser_scenario`
 WHERE CAST(`steps` AS CHAR) LIKE '%.header-auth\_\_btn%';
