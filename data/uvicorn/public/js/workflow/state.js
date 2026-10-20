// Общий стейт страницы редактора workflow (/admin/workflow).
// Модули читают и пишут поля через объект state — переприсваивание
// чужих экспортов в ES-модулях запрещено, поэтому обёртка обязательна.

// Операторы условия в порядке показа. Один список на переходы шага
// (`steps.js`) и на условие выхода из `repeat` (`step-widgets.js`).
//
// ⚠⚠ Лежат здесь, а не в `steps.js`: тот импортирует `step-widgets.js`, и
// обратный импорт замкнул бы круг — тем же приёмом, что события документа
// ниже по файлу. Двумя копиями списка жить нельзя: оператор появился бы в
// одном месте и пропал в другом, а заметно это стало бы уже в редакторе.
//
// ⚠ Значения обязаны совпадать с теми, что понимает движок
// (`ai_workflow_variable_compare`): редактор пишет их в метаданные как есть.
export const WORKFLOW_CONDITION_OPERATORS = ['==', '!=', '>', '<', '>=', '<=',
    'contains', 'not_contains', 'regex', 'exists', 'empty', 'not_empty'];

// Операторы, которым поле «Значение» не нужно: они спрашивают про саму
// переменную, а не сравнивают её с чем-то.
export const WORKFLOW_OPERATORS_WITHOUT_VALUE = ['exists', 'empty', 'not_empty'];

// Схемы динамических полей формы шага по типам шагов
export const WORKFLOW_STEP_CONFIG = {
    'llm_to_json': [ // ID типа "Инструменты"
        {
            key: 'llm_to_json_variable',
            type: 'widget_json_variable',
        },
        {
            key: 'prompt_user',
            label: 'User prompt',
            type: 'textarea',
            placeholder: '',
            value: '%prompt_user%'
        },
        {
            key: 'chunk_variable',
            label: 'MapReduce: переменная с большим текстом (необязательно)',
            type: 'variable_select',
            placeholder: '-- Не использовать MapReduce --'
        },
        {
            key: 'thinking_enable',
            label: 'Thinking enable',
            type: 'checkbox',
        }
    ],
    'tool_invoke': [ // ID типа "Инструменты"
        {
            key: 'tool_invoke',
            type: 'widget_tool_invoke',
        },
    ],
    'return_response_llm': [ // ID типа "Вернуть ответ"
        {
            key: 'prompt_user',
            label: 'User prompt',
            type: 'textarea',
            placeholder: ''
        }
    ],
    'return_response_text': [ // ID типа "Вернуть ответ"
        {
            key: 'prompt_user',
            label: 'User prompt',
            type: 'textarea',
            placeholder: ''
        },
        {
            key: 'continue_workflow',
            label: 'Продолжить workflow',
            type: 'checkbox',
            placeholder: ''
        }
    ],
    'variable_conversion': [ // ID типа "Вернуть ответ"
        {
            key: 'variable_conversion',
            type: 'widget_variable_conversion',
        }
    ],
    'workflow_invoke': [ // Вызов вложенного workflow (sub-workflow)
        {
            key: 'workflow_invoke',
            type: 'widget_workflow_invoke',
        }
    ],
    // Тема и действие: отсев тем по меткам в тексте истории, вопросы — в subflow.
    'topic_action': [
        {
            key: 'topic_action',
            type: 'widget_topic_action',
        }
    ],
    'llm_to_image': [ // Генерация изображения через LLM
        {
            key: 'prompt_user',
            label: 'Промпт для генерации изображения',
            type: 'textarea',
            placeholder: 'Опишите изображение...',
        },
        {
            key: 'llm_to_image',
            type: 'widget_llm_to_image',
        }
    ],
};

export const state = {
    allCurrentStepsData: [],     // шаги выбранного workflow (с metadata)
    allTargetSteps: [],          // id шагов, на которые есть переходы
    allWorkflowStepsType: {},    // справочник типов шагов по id
    allCurrentVariables: {},     // переменные выбранного workflow
    inputVarPicked: null,        // выбранная входящая переменная: список
                                 // перечитывается после каждого
                                 // сохранения, и без памяти о выборе
                                 // человека выбрасывало бы из формы,
                                 // которую он правит
    inputVarPending: [],         // ⚠⚠⚠ Заведённые кнопкой, но ещё не уехавшие
                                 // в базу входящие переменные. Держать их в
                                 // DOM нельзя: список перерисовывается от
                                 // чужих событий (переименовал соседнюю —
                                 // `renderInputVariables` чистит контейнер
                                 // целиком), и несохранённая исчезала вместе
                                 // с разметкой — молча, вместе с набранным
                                 // именем
    inputVarPendingFor: null,    // чей это список: номер workflow. Переход к
                                 // другому очищает очередь — иначе чужая
                                 // недоделанная уехала бы в него по первому
                                 // «Сохранить»
    allAvailableTools: [],       // все инструменты (для виджетов и tool-переменных)
    allUsedVariables: [],        // имена переменных, используемых в шагах
    allWorkflows: [],            // все workflow (для виджета workflow_invoke и имен sub-workflow)
};
