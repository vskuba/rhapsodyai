import {getData, postData, deleteData} from './api.js';
import {showNotification} from './notification.js';

export async function loadUserTokens(userId) {
    const tokensList = document.getElementById('tokensList');
    if (!tokensList) return;

    try {
        const response = await getData(`/user/${userId}/token`);
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
                <td style="font-family: monospace; letter-spacing: 0.5px; display: flex; align-items: center; gap: 8px;">
                    <span>${t.token}</span>
                    <button type="button" class="btn-token-copy" title="Копировать токен" style="background: transparent; border: none; cursor: pointer; font-size: 14px; padding: 2px; line-height: 1; transition: transform 0.1s; display: inline-flex; align-items: center;" onmouseover="this.style.transform='scale(1.2)'" onmouseout="this.style.transform='scale(1)'">📋</button>
                </td>
                <td style="text-align: right;">
                    <button type="button" class="btn-token-delete" data-id="${t.id}">Удалить</button>
                </td>
            `;
            
            tr.querySelector('.btn-token-copy').onclick = () => {
                navigator.clipboard.writeText(t.token).then(() => {
                    showNotification('Токен скопирован в буфер обмена!', 'success');
                }).catch(err => {
                    console.error('Ошибка копирования:', err);
                    showNotification('Не удалось скопировать токен', 'error');
                });
            };

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
            await deleteData(`/user/token/${tokenId}`);
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
            await postData(`/user/${userId}/token`, {});
            showNotification('Новый токен доступа успешно сгенерирован!', 'success');
            await loadUserTokens(userId);
        } catch (e) {
            console.error("Ошибка при генерации токена:", e);
            showNotification(`Ошибка при генерации: ${e.message}`, 'error');
        }
    };
}
