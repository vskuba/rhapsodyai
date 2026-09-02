-- Теги проставляются и записям, лежавшим в журнале до появления колонки.
--
-- Зачем отдельно. Разметчик живёт в питоне (`browser_error_tag`) и работает на записи:
-- новая ошибка получает теги сразу, старые — никогда. А их в журнале восемь тысяч, и
-- фильтр по тегу, не находящий в них ничего, бесполезен ровно там, где нужен больше
-- всего: разбирают ведь накопившееся, а не то, что пришло минуту назад.
--
-- Правила те же, что в `BROWSER_ERROR_TAG_RULES`, но список подстрок короче: здесь
-- нужны те, что действительно встречаются в накопленном журнале, а не полный набор на
-- будущее. Полное соответствие двух списков не требуется и не проверяется — это разовый
-- разбор задним числом, а не второй разметчик.
--
-- Порядок тегов в строке совпадает с порядком в питоне: одинаковые ошибки должны давать
-- одинаковую строку, иначе рядом в журнале лежат `,auth,network,` и `,network,auth,` —
-- глазу это два разных вида.
--
-- Идемпотентность: размечаем только записи с пустыми тегами. Повторный прогон не тронет
-- ни размеченное этим файлом, ни то, что разметил питон при записи.
UPDATE `browser_error`
   SET `tags` = CONCAT(
        ',',
        CONCAT_WS(',',
            IF(LOWER(`message`) REGEXP 'нужен вход|не авторизован|авториз|доступ запрещ|unauthorized|forbidden|401|403',
               'auth', NULL),
            IF(LOWER(`message`) REGEXP 'таймаут|не дождал|истекло время|превышено время|timeout|timed out',
               'timeout', NULL),
            IF(LOWER(`message`) REGEXP 'сокет|соединение|не отвечает|оборвал|socket|connection|econnrefused|network',
               'network', NULL),
            IF(LOWER(`message`) REGEXP 'не найден|не найдена|не найдено|отсутствует|not found|404',
               'notfound', NULL),
            IF(LOWER(`message`) REGEXP 'селектор|элемент не|xpath|selector|locator',
               'selector', NULL),
            IF(LOWER(`message`) REGEXP 'не разобра|разбор|неверный формат|json|parse|invalid|decode',
               'data', NULL),
            IF(LOWER(`message`) REGEXP '500|502|503|504|internal server|bad gateway|ошибка сервера',
               'server', NULL),
            IF(LOWER(`message`) REGEXP 'упал|аварийно|закрылось|crash|target closed|session closed',
               'crash', NULL)),
        ',')
 WHERE `tags` = ''
   AND LOWER(`message`) REGEXP CONCAT(
        'нужен вход|не авторизован|авториз|доступ запрещ|unauthorized|forbidden|401|403',
        '|таймаут|не дождал|истекло время|превышено время|timeout|timed out',
        '|сокет|соединение|не отвечает|оборвал|socket|connection|econnrefused|network',
        '|не найден|не найдена|не найдено|отсутствует|not found|404',
        '|селектор|элемент не|xpath|selector|locator',
        '|не разобра|разбор|неверный формат|json|parse|invalid|decode',
        '|500|502|503|504|internal server|bad gateway|ошибка сервера',
        '|упал|аварийно|закрылось|crash|target closed|session closed');
