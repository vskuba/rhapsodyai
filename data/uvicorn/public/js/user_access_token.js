import {getData, postData, deleteData} from './api.js';
import {showNotification} from './notification.js';

export async function loadUserTokens(userId) {
    const tokensList = document.getElementById('tokensList');
    if (!tokensList) return;

    try {
        const response = await getData(`/api/users/${userId}/token`);
        tokensList.innerHTML = '';

        const tokens = response.result || [];
        if (tokens.length === 0) {
            tokensList.innerHTML = `
                <tr>
                    <td colspan="2" style="text-align: center; color: #999; padding: 20px;">Нет активных токенов</td>
                </tr>
            `;
            return;
        }

        tokens.forEach(t => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-family: monospace; letter-spacing: 0.5px;">
                    <span title="Значение токена видно только при выдаче">…${t.tail || ''}</span>
                    ${t.note ? `<span style="font-family: inherit; color: #666; margin-left: 8px;">${t.note}</span>` : ''}
                </td>
                <td style="text-align: right;">
                    <button type="button" class="btn-token-delete" data-id="${t.id}">Удалить</button>
                </td>
            `;
            
            tr.querySelector('.btn-token-delete').onclick = () => deleteToken(t.id, userId);
            
            tokensList.appendChild(tr);
        });
    } catch (e) {
        console.error("Ошибка загрузки токенов:", e);
    }
}

export async function deleteToken(tokenId, userId) {
    if (confirm('Вы уверены, что хотите удалить этот токен доступа?')) {
        try {
            await deleteData(`/api/users/token/${tokenId}`);
            showNotification('Токен успешно удален', 'success');
            await loadUserTokens(userId);
        } catch (e) {
            console.error("Ошибка при удалении токена:", e);
            showNotification(`Ошибка: ${e.message}`, 'error');
        }
    }
}

export function initTokenGeneration(generateBtn, getUserIdFn) {
    if (!generateBtn) return;
    
    generateBtn.onclick = async () => {
        const userId = getUserIdFn();
        if (!userId) return;

        try {
            // ⚠⚠ Значение приходит **только здесь** и больше нигде: в списке
            // остаются пометка и хвост. Поэтому показываем его сразу и даём
            // скопировать — второго случая не будет, потерянный токен отзывают
            // и выдают новый.
            const made = await postData(`/api/users/${userId}/token`, {});
            const value = made && made.result && made.result.token;
            if (value) {
                try {
                    await navigator.clipboard.writeText(value);
                    showNotification(`Токен выдан и скопирован: ${value}`, 'success');
                } catch {
                    showNotification(`Токен выдан (скопируйте сейчас): ${value}`, 'success');
                }
            } else {
                showNotification('Новый токен доступа выдан', 'success');
            }
            await loadUserTokens(userId);
        } catch (e) {
            console.error("Ошибка при генерации токена:", e);
            showNotification(`Ошибка при генерации: ${e.message}`, 'error');
        }
    };
}
