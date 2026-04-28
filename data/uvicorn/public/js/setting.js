import {postData} from './api.js';

export async function saveUserSetting(key, value, userId) {
    if (!userId || userId === 'loading') return;

    try {
        const result = await postData(`/setting/${key}/user/${userId}`, {
            value: value
        });
        return result.result;
    } catch (e) {
        console.error(`Ошибка при сохранении настройки ${key}:`, e);
        return false;
    }
}

export async function loadAndApplySetting(key, userId) {
    if (!userId || userId === 'loading') return;

    try {
        const response = await fetch(`/setting/${key}/user/${userId}`);
        const data = await response.json();

        if (data.result && data.result !== 'null') {
            return data.result;
        }
    } catch (e) {
        console.error(`Ошибка при загрузке настройки ${key}:`, e);
    }
    return null;
}