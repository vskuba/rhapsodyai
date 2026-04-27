import { postData, getData, putData } from './api.js';

// --- Константы и глобальные переменные модуля ---
export const collectionListContainer = document.getElementById('collectionList');
export const inputTextarea = document.getElementById('inputText');
export const extractBtn = document.getElementById('extractBtn');
export const addToCollectionBtn = document.getElementById('addToCollectionBtn');

let mdEditor = null; // Будет инициализировано через initFactManager
let selectedCollection = null;

/**
 * Инициализация менеджера фактов
 * @param {Object} editorInstance - экземпляр CodeMirror
 */
export async function initFactManager(editorInstance) {
    mdEditor = editorInstance;
    await loadCollections();

    // Привязываем события, если кнопки существуют
    if (extractBtn) extractBtn.onclick = extractFacts;
    if (addToCollectionBtn) addToCollectionBtn.onclick = saveToCollection;
}

/**
 * Загрузка коллекций в левую колонку
 */
export async function loadCollections() {
    if (!collectionListContainer) return;

    try {
        const data = await getData('/fact/collection/list');
        collectionListContainer.innerHTML = ''; // Очистка

        data.result.forEach(name => {
            const div = document.createElement('div');
            div.className = 'collection-item';
            div.textContent = name.name;
            div.onclick = () => {
                document.querySelectorAll('.collection-item').forEach(el => el.classList.remove('active'));
                div.classList.add('active');
                selectedCollection = name;
                if (addToCollectionBtn) addToCollectionBtn.disabled = false;
            };
            collectionListContainer.appendChild(div);
        });
    } catch (e) {
        console.error("Ошибка загрузки коллекций:", e);
    }
}

/**
 * Отправка текста на LLM для извлечения фактов
 */
export async function extractFacts() {
    const text = inputTextarea?.value;
    if (!text) return alert("Введите текст для анализа");

    extractBtn.disabled = true;
    const originalText = extractBtn.textContent;
    extractBtn.textContent = "⌛ Обработка...";

    try {
        // Эндпоинт должен возвращать { "md_result": "текст фактов..." }
        const res = await postData('/chat/ask', {
            question: text,
            user_id: 1,
            agent: 'fact_extractor'
        });
        if (mdEditor) {
            mdEditor.setValue(res.result || "");
        }
    } catch (e) {
        console.error("Ошибка LLM:", e);
        alert("Ошибка при извлечении фактов");
    } finally {
        extractBtn.disabled = false;
        extractBtn.textContent = originalText;
    }
}

/**
 * Сохранение результата в выбранную коллекцию
 */
export async function saveToCollection() {
    if (!selectedCollection || !mdEditor) return;

    const content = mdEditor.getValue();
    const originalText = addToCollectionBtn.textContent;

    addToCollectionBtn.disabled = true;
    addToCollectionBtn.textContent = "💾 Сохранение...";

    try {
        // Метод для добавления (append) фактов в существующий файл
        await putData(`/fact/collection/${selectedCollection.name}`, {
            content: content,
            collection_id: selectedCollection.id
        });
        alert(`Успешно добавлено в коллекцию: ${selectedCollection.name}`);
        mdEditor.setValue("");
    } catch (e) {
        console.error("Ошибка сохранения:", e);
        alert("Не удалось сохранить в коллекцию");
    } finally {
        addToCollectionBtn.disabled = false;
        addToCollectionBtn.textContent = originalText;
    }
}