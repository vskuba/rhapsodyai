import { postData, getData, putData } from './api.js';

// --- Константы и глобальные переменные модуля ---
export const inputTextarea = document.getElementById('inputText');
export const extractBtn = document.getElementById('extractBtn');
export const addToCollectionBtn = document.getElementById('addToCollectionBtn');

// Новые элементы для таблицы и пагинации
const collectionSelect = document.getElementById('collectionSelect');
const factTableBody = document.getElementById('factTableBody');
const factSearchInput = document.getElementById('factSearch');
const prevPageBtn = document.getElementById('prevPage');
const nextPageBtn = document.getElementById('nextPage');
const activeCollectionTitle = document.getElementById('activeCollectionTitle');

let mdEditor = null;
let selectedCollection = null;

// Состояние для таблицы фактов
let state = {
    currentPage: 1,
    limit: 20,
    query: ""
};

/**
 * Инициализация менеджера фактов
 */
export async function initFactManager(editorInstance) {
    mdEditor = editorInstance;
    await loadCollections();

    if (collectionSelect) {
        collectionSelect.onchange = (e) => {
            const colName = e.target.value;
            // Находим объект коллекции по имени для сохранения в state
            selectedCollection = state.allCollections.find(c => c.name === colName);
            state.currentPage = 1;
            loadFacts();

            if (activeCollectionTitle) {
                activeCollectionTitle.innerText = `Коллекция: ${collectionSelect.value}`;
            }
        };
    }

    // Привязываем события извлечения/сохранения
    if (extractBtn) extractBtn.onclick = extractFacts;
    if (addToCollectionBtn) addToCollectionBtn.onclick = saveToCollection;

    // Привязываем события поиска и пагинации
    if (factSearchInput) factSearchInput.oninput = debounce(handleSearch, 500);
    if (prevPageBtn) prevPageBtn.onclick = () => changePage(-1);
    if (nextPageBtn) nextPageBtn.onclick = () => changePage(1);
}

/**
 * Загрузка коллекций в левую колонку
 */
export async function loadCollections() {
    if (!collectionSelect) return;

    try {
        const data = await getData('/fact/collection/list');
        state.allCollections = data.result; // Сохраняем для поиска объектов

        collectionSelect.innerHTML = ''; // Очистка

        data.result.forEach((col, index) => {
            const colName = col.name || col;
            const option = new Option(colName, colName);
            collectionSelect.add(option);
        });

        // ПО УМОЛЧАНИЮ: Выбираем первую коллекцию
        if (data.result.length > 0) {
            selectedCollection = data.result[0];
            collectionSelect.value = selectedCollection.name || selectedCollection;

            if (activeCollectionTitle) {
                activeCollectionTitle.innerText = `Коллекция: ${collectionSelect.value}`;
            }

            // Сразу подгружаем факты
            loadFacts();
        }
    } catch (e) {
        console.error("Ошибка загрузки коллекций:", e);
        collectionSelect.innerHTML = '<option>Ошибка загрузки</option>';
    }
}

/**
 * Загрузка списка фактов для таблицы (с пагинацией и поиском)
 */
export async function loadFacts() {
    if (!selectedCollection || !factTableBody) return;

    const colName = selectedCollection.name || selectedCollection;
    const url = `/fact/collection/${colName}?page=${state.currentPage}&limit=${state.limit}&query=${state.query}`;

    try {
        const data = await getData(url);
        renderTable(data.result);
        renderPagination(data.pagination);
    } catch (err) {
        factTableBody.innerHTML = '<tr><td colspan="5" class="error">Ошибка загрузки данных</td></tr>';
    }
}

function renderTable(facts) {
    if (!factTableBody) return;

    if (!facts || facts.length === 0) {
        factTableBody.innerHTML = '<tr><td colspan="5" class="placeholder">Ничего не найдено</td></tr>';
        return;
    }

    factTableBody.innerHTML = facts.map(f => `
        <tr>
            <td><div class="doc-name-cell" title="${f.document}">${f.document || '—'}</div></td>
            <td><div class="content-preview">${escapeHtml(f.content)}</div></td>
            <td><div class="content-preview">${escapeHtml(f.group_id)}</div></td>
            <td><div class="content-preview">${escapeHtml(f.category)}</div></td>
            <td>
                <div class="tags-container">
                    ${f.tags_list ? f.tags_list.split(',').map(tag =>
                    `<span class="tag-chip">${tag.trim()}</span>`
                ).join('') : '—'}
                </div>
            </td>
            <td>
                <span class="status-badge ${f.qdrant_synced ? 'synced' : 'pending'}">
                    ${f.qdrant_synced ? 'Синхрон.' : 'Ожидает'}
                </span>
            </td>
            <td>
                <div class="actions-cell">
                    <button class="btn-icon delete" onclick="deleteFact(${f.id})" title="Удалить">🗑️</button>
                </div>
            </td>
        </tr>
    `).join('');
}

function renderPagination(pg) {
    const info = document.getElementById('paginationInfo');
    if (info) info.innerText = `Стр. ${pg.current_page} из ${pg.total_pages}`;

    if (prevPageBtn) prevPageBtn.disabled = pg.current_page <= 1;
    if (nextPageBtn) nextPageBtn.disabled = pg.current_page >= pg.total_pages;
}

// --- Обработчики событий ---

function handleSearch(e) {
    state.query = e.target.value;
    state.currentPage = 1;
    loadFacts();
}

function changePage(delta) {
    state.currentPage += delta;
    loadFacts();
}

// --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

export async function extractFacts() {
    const text = inputTextarea?.value;
    if (!text) return alert("Введите текст для анализа");

    extractBtn.disabled = true;
    const originalText = extractBtn.textContent;
    extractBtn.textContent = "⌛ Обработка...";

    try {
        const res = await postData('/chat/ask', {
            question: text,
            user_id: 1,
            agent: 'fact_extractor'
        });
        if (mdEditor) mdEditor.setValue(res.result || "");
    } catch (e) {
        console.error("Ошибка LLM:", e);
        alert("Ошибка при извлечении фактов");
    } finally {
        extractBtn.disabled = false;
        extractBtn.textContent = originalText;
    }
}

export async function saveToCollection() {
    if (!selectedCollection || !mdEditor) return;

    const content = mdEditor.getValue();
    if (!content) return alert("Нет контента для сохранения");

    const colName = selectedCollection.name || selectedCollection;
    const originalText = addToCollectionBtn.textContent;

    addToCollectionBtn.disabled = true;
    addToCollectionBtn.textContent = "💾 Сохранение...";

    try {
        await putData(`/fact/collection/${colName}`, {
            content: content,
            collection_id: selectedCollection.id
        });
        alert(`Успешно добавлено в коллекцию: ${colName}`);
        mdEditor.setValue("");
        loadFacts(); // Перезагружаем таблицу, чтобы увидеть новый факт
    } catch (e) {
        console.error("Ошибка сохранения:", e);
        alert("Не удалось сохранить в коллекцию");
    } finally {
        addToCollectionBtn.disabled = false;
        addToCollectionBtn.textContent = originalText;
    }
}

function debounce(func, timeout = 300) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => { func.apply(this, args); }, timeout);
    };
}

function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

window.deleteFact = async function(factId) {
    if (!confirm(`Вы уверены, что хотите удалить факт #${factId}?`)) return;

    try {
        // Используем метод DELETE из вашего api.js (если есть) или стандартный fetch
        const response = await fetch(`/admin/fact/${factId}`, { method: 'DELETE' });
        const result = await response.json();

        if (result.status === 'success') {
            // Перезагружаем список, чтобы факт исчез из таблицы
            await loadFacts();
        } else {
            alert("Ошибка при удалении");
        }
    } catch (e) {
        console.error("Ошибка удаления:", e);
        alert("Не удалось связаться с сервером");
    }
};