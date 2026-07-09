// Общий стейт страницы редактора workflow (/admin/workflow).
// Модули читают и пишут поля через объект state — переприсваивание
// чужих экспортов в ES-модулях запрещено, поэтому обёртка обязательна.

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
    ]
};

export const state = {
    allCurrentStepsData: [],     // шаги выбранного workflow (с metadata)
    allTargetSteps: [],          // id шагов, на которые есть переходы
    allWorkflowStepsType: {},    // справочник типов шагов по id
    allCurrentVariables: {},     // переменные выбранного workflow
    allAvailableTools: [],       // все инструменты (для виджетов и tool-переменных)
    allUsedVariables: [],        // имена переменных, используемых в шагах
};
