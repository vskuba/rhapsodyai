export const state = {
    currentTab: 'events',
    currentPlanId: null,
    currentTaskId: null,
    chatSessionUuid: null,
    // Вкладка задач: выбранный проект селектора ('' — все) и задача, у которой
    // открыта панель вопросов. Читаются tasks.js, живут здесь — вкладку перерисовывают
    // с разных сторон (список, панель, флажки), и поле у неё одно на всех.
    taskProjectId: '',
    taskCurrentQuestionId: null,
    eventsTimezone: '+0',
    pingFailCount: 0,
    claude: {
        sessionUuid: null,
        sessionLabel: '',
        sessionUnreachable: false,
        pollTimer: null,
        statusPollTimer: null,
        renderedUserIds: new Set(),
        renderedResponses: new Map(),
        pendingUserCount: 0,
        typingBubble: null,
    },
};
