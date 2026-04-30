import {postData} from './api.js';

export const sessionList = document.getElementById('sessionList');
export const messagesContainer = document.getElementById('messagesContainer');
export const agentFilter = document.getElementById('agentFilter');
export const userFilter = document.getElementById('userFilter');

export async function loadSessions() {
    sessionList.innerHTML = 'Загрузка...';
    const data = await postData('/session/list', {
        agent_name: agentFilter.value,
        user_id: userFilter.value ? parseInt(userFilter.value) : null
    });

    sessionList.innerHTML = '';
    data.result.forEach((s, index) => {
        const div = document.createElement('div');
        div.className = 'session-item';

        // Форматирование UUID (первые 6 символов)
        const shortUuid = s.session_uuid.substring(0, 12) + '...';

        div.innerHTML = `
            <div class="session-item-header">
                <span class="session-short-uuid">${shortUuid}</span>
                <span class="session-msg-count">💬 ${s.msg_count}</span>
            </div>
        `;

        div.onclick = () => loadSessionDetails(s.session_uuid, div);
        sessionList.appendChild(div);

        if (index === 0) {
            loadSessionDetails(s.session_uuid, div);
        }
    });
}

export async function initFilters() {
    try {
        // 1. Загрузка агентов
        const agentData = await (await fetch('/agent/list')).json();
        if (agentData.result && agentData.result.length > 0) {
            agentFilter.innerHTML = ''; // Очищаем заглушку
            agentData.result.forEach(name => {
                agentFilter.add(new Option(name, name));
            });
            agentFilter.selectedIndex = 0;
        }

        // 2. Загрузка пользователей
        const userData = await (await fetch('/user/list')).json();
        if (userData.result && userData.result.length > 0) {
            userFilter.innerHTML = ''; // Очищаем заглушку
            userData.result.forEach(user => {
                const label = user.name || `User ${user.id}`;
                userFilter.add(new Option(label, user.id));
            });
            userFilter.selectedIndex = 0;
        }

        // СЛУШАТЕЛИ: чтобы при смене в Блоке 1 обновлялся Блок 2
        agentFilter.onchange = loadSessions;
        userFilter.onchange = loadSessions;

        // Сразу загружаем список после инициализации фильтров
        await loadSessions();

    } catch (e) {
        console.error("Ошибка инициализации:", e);
    }
}

export async function loadSessionDetails(uuid, element) {
    document.querySelectorAll('.session-item').forEach(i => i.classList.remove('active'));
    element.classList.add('active');

    document.getElementById('activeSessionTitle').innerText = "Сессия: " + uuid;
    messagesContainer.innerHTML = 'Загрузка...';

    try {
        const data = await postData('/session/messages', {
            session_uuid: uuid
        });

        messagesContainer.innerHTML = '';
        data.result.forEach(m => {
            const msgDiv = document.createElement('div');
            msgDiv.className = 'admin-msg-box';

            const roleClass = `role-${m.role}`;
            // Форматируем время создания сообщения (согласно структуре БД)
            const time = m.created_at ? new Date(m.created_at).toLocaleTimeString() : '';

            msgDiv.innerHTML = `
                <div class="chips-container">
                    <span class="chip ${roleClass}">${m.role}</span>
                    <span class="chip chip-kind">${m.kind_type}</span>
                    ${m.token ? `<span class="chip chip-token">Токены: ${m.token}</span>` : ''}
                    <span class="chip-date">${time}</span>
                </div>
                <div class="admin-msg-content">${m.content || ''}</div>
            `;
            messagesContainer.appendChild(msgDiv);
        });

        messagesContainer.scrollTop = 0;
    } catch (e) {
        console.error("Ошибка загрузки полной истории:", e);
        messagesContainer.innerHTML = '<div style="color:red">Ошибка загрузки данных</div>';
    }
}