import { getData } from './api.js';

export const userSelect = document.getElementById('userSelect');

export async function loadUsers() {
    try {
        const data = await getData('/user/list');
        userSelect.innerHTML = '';
        data.result.forEach(user => {
            const option = document.createElement('option');
            option.value = user.id;
            option.textContent = user.username;
            userSelect.appendChild(option);
        });
        if (data.result.length > 0) userSelect.selectedIndex = 0;
    } catch (e) {
        console.error("Ошибка загрузки пользователей:", e);
    }
}