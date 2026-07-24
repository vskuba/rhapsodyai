export const state = {
    currentTab: 'events',
    currentPlanId: null,
    chatSessionUuid: null,
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
