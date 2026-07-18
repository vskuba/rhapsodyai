// Общий переключатель языков для форм с переводимыми полями (greeting, default переменных).
// Полоска-чипы с языками текущей ноды (настройка 'languages': нодовая перекрывает общую),
// первый язык активен по умолчанию. Дизайн един для всех страниц — стили инжектятся модулем.
//
// Формат хранения перевода: одно значение — обычная строка; несколько языков —
// JSON-словарь {"ru": "...", "en": "..."} (бэкенд резолвит его в активный язык ноды).

import {getData, postData} from '/static/js/api.js';
import {showNotification} from '/static/js/notification.js';

const STYLE_ID = 'lang-switcher-style';
const CSS = `
.lang-switcher {
    display: inline-flex;
    gap: 4px;
    padding: 3px;
    background: #eef2f7;
    border-radius: 6px;
}
.lang-switcher .lang-chip {
    border: none;
    background: transparent;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    color: #64748b;
    cursor: pointer;
    transition: all 0.15s;
}
.lang-switcher .lang-chip:hover {
    color: #3498db;
}
.lang-switcher .lang-chip.active {
    background: #fff;
    color: #3498db;
    box-shadow: 0 1px 2px rgba(0,0,0,0.12);
}
.lang-switcher .lang-translate-btn {
    border: none;
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    color: #27ae60;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
}
.lang-switcher .lang-translate-btn:hover:not(:disabled) {
    background: #eafaf1;
}
.lang-switcher .lang-translate-btn:disabled {
    opacity: 0.5;
    cursor: default;
}
`;

function styleInject() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
}

/**
 * Разбирает значение-перевод: если raw — JSON-словарь {"ru": "...", "en": "..."},
 * возвращает текст для lang (fallback — первый язык словаря). Обычные строки — как есть.
 * Для отображения переводимых значений вне полей формы (подсказки, списки).
 */
export function i18nTextResolve(raw, lang) {
    const text = String(raw ?? '').trim();
    if (!(text.startsWith('{') && text.endsWith('}'))) return raw ?? '';

    try {
        const data = JSON.parse(text);
        const isLangDict = data && typeof data === 'object' && !Array.isArray(data)
            && Object.keys(data).length > 0
            && Object.keys(data).every(k => /^[a-z]{2}(-[a-zA-Z]{2})?$/.test(k));
        if (!isLangDict) return raw ?? '';
        return data[lang] ?? Object.values(data)[0] ?? '';
    } catch (e) {
        return raw ?? '';
    }
}

/**
 * Языки ноды из настроек: нодовая запись 'languages' перекрывает общую. ['ru'] по умолчанию.
 */
export async function nodeLanguagesGet(nodeId) {
    try {
        const res = await getData('/setting/list');
        const rows = (res.result || []).filter(r => r.key === 'languages');
        const nodeRow = nodeId ? rows.find(r => String(r.node_id) === String(nodeId)) : null;
        const globalRow = rows.find(r => !r.node_id);
        const raw = (nodeRow || globalRow || {}).value || 'ru';
        const langs = raw.split(',').map(l => l.trim().toLowerCase()).filter(Boolean);
        return langs.length ? langs : ['ru'];
    } catch (e) {
        console.error('Не удалось загрузить языки ноды:', e);
        return ['ru'];
    }
}

/**
 * Создает переключатель в container. Возвращает api:
 *  - getLang() — активный язык
 *  - setLanguages(langs) — обновить набор (напр. при смене ноды), активным становится первый
 *  - fieldBind(el) — привязать input/textarea как переводимое поле
 *  - fieldLoad(el, raw) — загрузить значение поля (строка или JSON-словарь переводов)
 *  - fieldSerialize(el) — собрать значение поля для сохранения
 */
export function langSwitcherCreate(container, languages = ['ru']) {
    styleInject();

    const bar = document.createElement('div');
    bar.className = 'lang-switcher';
    container.appendChild(bar);

    let langs = [];
    let active = 'ru';
    const fields = new Set();
    const changeListeners = new Set();
    // Последнее сфокусированное переводимое поле: кнопка перевода действует на него;
    // пока фокуса не было — переводятся все пустые поля формы
    let focusedField = null;

    function render() {
        bar.innerHTML = '';
        bar.style.display = langs.length > 1 ? '' : 'none';
        langs.forEach(lang => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'lang-chip' + (lang === active ? ' active' : '');
            chip.textContent = lang;
            chip.onclick = () => switchTo(lang);
            bar.appendChild(chip);
        });
        renderTranslateBtn();
    }

    // Кнопка автоперевода: действует на сфокусированное поле (клик мышкой в поле =
    // «это поле требует перевода»); пока фокуса не было — на все пустые поля формы.
    // Видна, когда у цели активный язык пуст, а в другом языке есть текст.
    function translateTargetsGet() {
        const candidates = (focusedField && fields.has(focusedField))
            ? [focusedField]
            : Array.from(fields);
        return candidates.filter(el => el.value.trim() === '');
    }

    function translateSourceGet(targets) {
        for (const lang of langs) {
            if (lang === active) continue;
            for (const el of targets) {
                if ((el._i18n.translations[lang] ?? '').trim() !== '') return lang;
            }
        }
        return null;
    }

    function renderTranslateBtn() {
        const old = bar.querySelector('.lang-translate-btn');
        if (old) old.remove();

        if (langs.length < 2) return;
        const targets = translateTargetsGet();
        const source = translateSourceGet(targets);
        if (!targets.length || !source) return;

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'lang-translate-btn';
        btn.textContent = `🌐 перевести с ${source}`;
        btn.title = (focusedField && fields.has(focusedField))
            ? `Автоперевод выбранного поля: ${source} → ${active}`
            : `Автоперевод пустых полей: ${source} → ${active}`;
        btn.onclick = () => translateFields(targets, source, btn);
        bar.appendChild(btn);
    }

    async function translateFields(targets, source, btn) {
        btn.disabled = true;
        btn.textContent = '🌐 перевожу...';
        try {
            for (const el of targets) {
                if (el.value.trim() !== '') continue; // ручной текст не перетираем
                const sourceText = el._i18n.translations[source] ?? '';
                if (sourceText.trim() === '') continue;

                const res = await postData('/translate', {
                    text: sourceText,
                    language_from: source,
                    language_to: active
                });
                el.value = res.result || '';
                el._i18n.translations[active] = el.value;
                el.dispatchEvent(new Event('input', {bubbles: true}));
            }
            showNotification(`Переведено: ${source} → ${active}`, 'success');
        } catch (e) {
            showNotification(`Ошибка перевода: ${e.message}`, 'error');
        } finally {
            renderTranslateBtn();
        }
    }

    function switchTo(lang) {
        if (lang === active) return;
        // Текущий текст полей — в словарь старого языка, показываем новый
        fields.forEach(el => {
            el._i18n.translations[active] = el.value;
            el.value = el._i18n.translations[lang] ?? '';
        });
        active = lang;
        render();
        changeListeners.forEach(cb => cb(active));
    }

    function setLanguages(newLangs) {
        langs = (newLangs && newLangs.length) ? newLangs : ['ru'];
        if (!langs.includes(active)) active = langs[0];
        render();
    }

    function fieldBind(el) {
        el._i18n = {translations: {}};
        fields.add(el);
        // Заполненность и фокус поля влияют на цель и видимость кнопки автоперевода
        el.addEventListener('input', renderTranslateBtn);
        el.addEventListener('focusin', () => {
            focusedField = el;
            renderTranslateBtn();
        });
    }

    function fieldLoad(el, raw) {
        if (!el._i18n) fieldBind(el);
        el._i18n.translations = {};

        let parsed = null;
        const text = String(raw ?? '').trim();
        if (text.startsWith('{') && text.endsWith('}')) {
            try {
                const data = JSON.parse(text);
                const isLangDict = data && typeof data === 'object' && !Array.isArray(data)
                    && Object.keys(data).length > 0
                    && Object.keys(data).every(k => /^[a-z]{2}(-[a-zA-Z]{2})?$/.test(k));
                if (isLangDict) parsed = data;
            } catch (e) { /* обычная строка */ }
        }

        if (parsed) {
            el._i18n.translations = parsed;
            el.value = parsed[active] ?? parsed[langs[0]] ?? Object.values(parsed)[0] ?? '';
        } else {
            // Простая строка = значение базового (первого) языка
            el._i18n.translations[langs[0]] = String(raw ?? '');
            el.value = active === langs[0] ? String(raw ?? '') : '';
        }

        renderTranslateBtn();
    }

    function fieldSerialize(el) {
        if (!el._i18n) return el.value;
        el._i18n.translations[active] = el.value;

        const filled = {};
        langs.forEach(lang => {
            const v = (el._i18n.translations[lang] ?? '').trim();
            if (v !== '') filled[lang] = el._i18n.translations[lang];
        });

        const keys = Object.keys(filled);
        if (keys.length === 0) return '';
        // Только базовый язык заполнен — храним обычной строкой (обратная совместимость)
        if (keys.length === 1 && keys[0] === langs[0]) return filled[keys[0]];
        return JSON.stringify(filled);
    }

    setLanguages(languages);

    return {
        getLang: () => active,
        setLanguages,
        fieldBind,
        fieldLoad,
        fieldSerialize,
        // Подписка на переключение языка (например, перерисовать подсказки)
        onChange: (cb) => changeListeners.add(cb),
    };
}
