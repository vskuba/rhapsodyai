from enum import Enum


class AuthPermission(str, Enum):
    # User permissions
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"

    # Agent permissions
    AGENT_VIEW = "agent:view"
    AGENT_CREATE = "agent:create"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"

    # Role permissions
    ROLE_VIEW = "role:view"
    ROLE_CREATE = "role:create"
    ROLE_UPDATE = "role:update"
    ROLE_DELETE = "role:delete"

    # Workflow permissions
    WORKFLOW_VIEW = "workflow:view"
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_UPDATE = "workflow:update"
    WORKFLOW_DELETE = "workflow:delete"

    # Workflow variable permissions
    WORKFLOW_VARIABLE_VIEW = "workflow_variable:view"
    WORKFLOW_VARIABLE_CREATE = "workflow_variable:create"
    WORKFLOW_VARIABLE_UPDATE = "workflow_variable:update"
    WORKFLOW_VARIABLE_DELETE = "workflow_variable:delete"

    # Ветки разговора и темы внутри них — вкладка «Branch»
    WORKFLOW_TOPIC_VIEW = "workflow_topic:view"
    WORKFLOW_TOPIC_CREATE = "workflow_topic:create"
    WORKFLOW_TOPIC_UPDATE = "workflow_topic:update"
    WORKFLOW_TOPIC_DELETE = "workflow_topic:delete"

    # Workflow trace permissions
    WORKFLOW_TRACE_VIEW = "workflow_trace:view"
    WORKFLOW_TRACE_DELETE = "workflow_trace:delete"
    WORKFLOW_TRACE_REPLAY = "workflow_trace:replay"
    WORKFLOW_TRACE_STOP = "workflow_trace:stop"

    # Журнал ошибок установки — страница «Журнал» (/admin/journal)
    JOURNAL_VIEW = "journal:view"
    JOURNAL_DELETE = "journal:delete"

    # E2E-проверки интерфейса — страница «Тесты → E2E» (/admin/e2e).
    #
    # ⚠ `E2E_RUN` отдельно от `E2E_VIEW`: смотреть вчерашний прогон — чтение, а
    # кнопка «Прогнать сейчас» поднимает браузер и ходит по страницам панели от
    # имени установки. Разные по цене действия одним правом не раздают.
    E2E_VIEW = "e2e:view"
    E2E_RUN = "e2e:run"
    E2E_DELETE = "e2e:delete"

    # Планировщик Cronicle — страница «Настройки → Cronicle» (/admin/cronicle).
    #
    # ⚠ Включатель отдельным правом от чтения, и разница тут по существу.
    # Смотреть расписание — значит знать, что на установке происходит ночью;
    # выключить событие — значит сделать так, чтобы оно не произошло, и узнают
    # об этом не сразу, а по не случившейся работе.
    CRONICLE_VIEW = "cronicle:view"
    CRONICLE_UPDATE = "cronicle:update"

    # Node permissions
    NODE_VIEW = "node:view"
    NODE_CREATE = "node:create"
    NODE_UPDATE = "node:update"
    NODE_DELETE = "node:delete"

    # Tool permissions
    TOOL_VIEW = "tool:view"
    TOOL_CREATE = "tool:create"
    TOOL_UPDATE = "tool:update"
    TOOL_DELETE = "tool:delete"
    TOOL_TEST = "tool:test"

    # LLM permissions
    LLM_VIEW = "llm:view"
    LLM_CREATE = "llm:create"
    LLM_UPDATE = "llm:update"
    LLM_DELETE = "llm:delete"

    # Fact permissions
    FACT_VIEW = "fact:view"
    FACT_CREATE = "fact:create"
    FACT_UPDATE = "fact:update"
    FACT_DELETE = "fact:delete"

    # Fact Collection permissions
    FACT_COLLECTION_VIEW = "fact_collection:view"
    FACT_COLLECTION_CREATE = "fact_collection:create"
    FACT_COLLECTION_UPDATE = "fact_collection:update"
    FACT_COLLECTION_DELETE = "fact_collection:delete"

    # Plan permissions
    PLAN_VIEW = "plan:view"
    PLAN_CREATE = "plan:create"
    PLAN_UPDATE = "plan:update"
    PLAN_DELETE = "plan:delete"

    # Session permissions
    SESSION_VIEW = "session:view"
    SESSION_DELETE = "session:delete"

    # Убрать из обмена наш ответ — вкладка «Чат» страницы `/admin/session`.
    # Реплика собеседника при этом остаётся: удаляется половина строки, а не
    # строка (`session_companion.py`, шапка).
    #
    # ⚠⚠ Право своё, а не `session:delete`, и это не формальность. То чистит
    # `agent_session` — журнал вызовов модели, который можно вымести целиком без
    # последствий. Здесь удаляется **память агента**: строка `companion_session`
    # едет в промпт лентой `companion_session_history`, и выдав это право вместе
    # с уборкой журнала, мы отдали бы заодно возможность менять то, что агент
    # помнит о человеке.
    SESSION_COMPANION_DELETE = "session_companion:delete"

    # Записать обмен в память агента извне: три точки `/chat/message/*`
    # (`delivered`, `incoming`, `put`), которыми DatingAi кладёт в
    # `companion_session` реплики — доставленную, принятую и отправленную мимо
    # прогона.
    #
    # ⚠⚠ Право своё, по тому же доводу, что у соседа сверху: это **запись в
    # память агента**, она едет в промпт лентой `companion_session_history`.
    # Прежде три точки стояли под `AuthChecker([])` — то есть писать в память
    # мог всякий вошедший, включая анонимного гостя с `/auth/guest`.
    #
    # ⚠ Не `chat:ask`: то право есть у гостя и у людей панели, а эти три точки
    # нужны одной служебной учётке соседа. Сложи их в одно право — и гость,
    # которому нужен разговор, получил бы заодно запись в чужую память.
    SESSION_COMPANION_WRITE = "session_companion:write"

    # Setting permissions
    SETTING_VIEW = "setting:view"
    SETTING_UPDATE = "setting:update"

    # Planning permissions
    PLANNING_VIEW = "planning:view"
    PLANNING_CREATE = "planning:create"
    PLANNING_UPDATE = "planning:update"
    PLANNING_DELETE = "planning:delete"

    # Browser permissions
    #
    # Контейнер-браузер — общий инструмент: закладки сайтов, сценарии, живые сессии
    # Chromium и запись действий. Права свои по той же причине, что и у знакомств:
    # `planning:*` смешивал в одно право планирование проектов, анкеты и чужие
    # браузерные сессии, и служебной учётке приходилось выдавать всё разом.
    BROWSER_VIEW = "browser:view"
    BROWSER_CREATE = "browser:create"
    # Показ секретных переменных сайта сырыми — право отдельное от `browser:view`
    # намеренно. `browser:view` есть у `dating_service`, а это автоматика соседнего
    # проекта: ей нужны закладки с `presence`, но не пароли от чужих кабинетов.
    # Отдай мы расшифровку по `browser:view` — учётка, которой правит не человек, а
    # код, получила бы доступ ко всем паролям установки разом.
    #
    # Список переменных с закрытыми значениями (`•••`) при этом отдаётся по
    # `browser:view`: знать, что у сайта есть пароль, и знать сам пароль — разные вещи.
    BROWSER_SECRET_VIEW = "browser:secret"

    # Реестр прокси: получить адреса выходов вместе с паролями каналов.
    #
    # Право своё, а не `browser:secret`, и разница тут по существу. `browser:secret`
    # открывает пароли **чужих кабинетов** — все секретные переменные всех сайтов
    # установки; его у `dating_service` нет намеренно. Прокси же — не чужой секрет,
    # а рабочий инструмент соседа: без адреса с паролем он не сможет ни войти на
    # сайт своим HTTP, ни держать присутствие, ни поднять вебсокет с того же IP,
    # с которого вошёл браузер.
    #
    # Управление реестром (завести, править, удалить, проверить) под это право
    # **не** попадает — оно за `browser:create`, то есть за человеком.
    BROWSER_PROXY_USE = "browser:proxy"

    # Расшифровка речи — общий инструмент, как и браузер: модель Whisper живёт
    # здесь, а голос присылают соседние проекты. Право своё, а не `agent:*`:
    # расшифровка агентов не трогает, и служебной учётке соседа незачем получать
    # доступ к агентам ради одного микрофона.
    STT_CREATE = "stt:create"

    # Разговор с агентом: спросить (`/chat/ask`), прочитать свою переписку
    # (`/chat/messages`), надиктовать голосом (`/chat/voice`), узнать агентов
    # дела (`/detective/case_agents`).
    #
    # ⚠⚠ Право заведено ради **гостя**. Четыре эти точки стояли под
    # `AuthChecker([])` — «вошёл, и ладно», — а войти умеет кто угодно через
    # публичный `POST /auth/guest`. Вместе с ними тот же пустой список открывал
    # гостю ещё семь: `/translate` (жжёт LLM за наши деньги), `/companion` и
    # `/companion/list` (справочник собеседников, чтение и запись),
    # `/agent/list`, три `/chat/message/*`. Разделить их можно было только
    # назвав то, что игре правда нужно, — вот оно.
    #
    # ⚠ Право широкое по выдаче и узкое по смыслу: его имеют люди панели
    # (голосовой ввод на `/admin/*`, окно чата), `dating_service` и гость. У
    # гостя оно **единственное**, и этим список его возможностей исчерпан.
    CHAT_ASK = "chat:ask"

    # Перевод текста «вне ноды» (`POST /translate`): агент ищется по имени
    # `translator`. Зовут переключатель языка и подсказки на страницах панели
    # (`lang_switcher.js`, `workflow/text-translate.js`, `workflow/topic.js`) и
    # DatingAi.
    #
    # ⚠ Право заведено потому, что точка **тратит деньги**: каждый вызов — это
    # поход в модель. Под `AuthChecker([])` её мог дёргать любой вошедший,
    # включая анонимного гостя, сколько угодно раз.
    TRANSLATE_CREATE = "translate:create"

    # Войти в саму панель: все страницы `/admin/*` и корень `/`.
    # Проверяется один раз, в `dashboard_require_auth`; что человек увидит
    # внутри — решают права по темам (`workflow:view`, `setting:view`, …).
    #
    # ⚠⚠ Нужно отдельное право, потому что «вошёл» и «работает здесь» —
    # разные вещи. Сессию заводит и публичный `POST /auth/guest`, и гость
    # получал все 36 страниц панели по 120 КБ разметки. Проверять «есть ли
    # вообще хоть какое-нибудь право» не годится: у гостя есть `chat:ask`, он
    # ему правда нужен — и такая проверка пропустила бы его обратно (так и
    # вышло с первого раза).
    #
    # ⚠ Служебным учёткам соседей (`blog_service`, `dating_service`) право не
    # выдано намеренно: они ходят по токену из кода, браузером в панель не
    # заходят, и страницы им не нужны.
    PANEL_VIEW = "panel:view"

    # Queue permissions
    QUEUE_VIEW = "queue:view"

    # GX10 permissions
    #
    # Отдельная машина с локальными LLM (llama.cpp) и ComfyUI: вкладка LLM → GX10.
    # View — читать статус сервисов и память, control — start/stop/restart/enable/disable.
    # Роль admin и qa получают оба права автоматически (полный набор).
    GX10_VIEW = "gx10:view"
    GX10_CONTROL = "gx10:control"

    # Design permissions
    DESIGN_VIEW = "design:view"
    DESIGN_CREATE = "design:create"
    DESIGN_UPDATE = "design:update"
    DESIGN_DELETE = "design:delete"

    # Project permissions
    PROJECT_VIEW = "project:view"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"