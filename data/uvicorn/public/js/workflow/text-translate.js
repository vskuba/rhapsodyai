// Перевод выделенного куска промпта: три флага в большом окне текста.
//
// ## ⚠⚠⚠ Зачем
//
// Промпты написаны по-русски, и модель от этого хуже держит инструкцию: просят
// ответ по-английски — отвечает по-русски. Переписывать их на английский надо
// постепенно, кусками, с чтением глазами — отсюда и предмет: выделил абзац,
// нажал флаг, кусок заменился переводом. Не «перевести весь промпт кнопкой»:
// промпт на четыре тысячи знаков разом не проверить, а непроверенный перевод
// здесь дороже непереведённого.
//
// ## ⚠⚠⚠ Метки заслоняются от модели, и это не перестраховка
//
// В промпте живут `%имя%` и `[<if …>]` — их читает движок (`ai_workflow.py`).
// Переведи модель `%girl_name%` как `%имя_девушки%` или потеряй `[<endif>]` —
// workflow сломается **без единой ошибки**: метка не подставится, блок уедет в
// модель как есть. Ровно эта порода беды стоила трёх минут точности при поиске
// поломки инвайтов (`workflow_history.md`).
//
// У агента `translator` правила про метки **нет** (четыре правила: только
// перевод, сохранять стиль, не переводить имена собственные, уже на целевом —
// вернуть как есть). Исправлять чужой промпт нельзя — архитектуру workflow
// придумывает человек, — поэтому заслоняемся здесь: каждая метка заменяется
// на `⟦N⟧`, после перевода возвращается на место.
//
// ⚠⚠ И **сверяется**. Не вернулась хоть одна — текст не заменяется вовсе, и
// человеку говорится почему. Молчаливая подстановка покорёженного промпта —
// то единственное, чего эта кнопка делать не должна ни при каких условиях.

import {postData} from '../api.js';
import {showNotification} from '../notification.js';

// Языки раздела: флаг, код для ручки, подпись.
//
// ⚠ Порядок — английский первым: ради него всё и делается, остальные два нужны
// на обратную дорогу («что я тут написал?»).
const TRANSLATE_LANGS = [
    {code: 'en', flag: '🇬🇧', word: 'английский'},
    {code: 'uk', flag: '🇺🇦', word: 'украинский'},
    {code: 'ru', flag: '🇷🇺', word: 'русский'},
];

// Метки, которые модель видеть не должна: `[<if …>]`, `[<else>]`, `[<endif>]`,
// `%имя%` и `[[имя]]`.
//
// ⚠ Первые три и `%имя%` повторяют `HL_RE` из `text-modal.js` по составу, но
// **не делятся** с ним: тот разобран на части ради раскраски (открывающая метка
// ловится тремя группами), а здесь нужна метка целиком. Общая половина — сами
// формы меток, и меняются они вместе с движком, а не друг с другом.
//
// ## ⚠⚠ `[[имя]]` заслоняется, хотя наш движок его не читает
//
// Двойные скобки заняты дважды, и оба места живые (`ai_workflow.py`, шапка):
// `[[firstName]]` — переменная письма в DatingAi, `[[Создать проект]]` — чипса
// чата. Промпт инвайта прямо просит модель: «поставь метку `[[girl_name]]`».
// Переведи переводчик её в `[[имя_девушки]]` — подстановка в DatingAi молча
// перестанет находить имя, и человек получит письмо со скобками в тексте.
//
// ⚠ Заслоняется **только похожее на идентификатор**. `[[Создать проект]]` —
// подпись кнопки, её перевод осмыслен; `[[girl_name]]` — имя, по которому
// ищут, и его перевод всегда беда. Различить их можно ровно по виду.
const TRANSLATE_MARK_RE = new RegExp(
    '\\[<\\s*if\\s+(?:[^>\\[]|>(?!\\]))+?\\s*>\\]'
    + '|\\[<\\s*(?:else|endif)\\s*>\\]'
    + '|%[a-zA-Z_][a-zA-Z0-9_]*%'
    + '|\\[\\[[a-zA-Z_][a-zA-Z0-9_]*\\]\\]',
    'g');

// Чем заслоняется метка. ⚠ Угловые скобки `⟦⟧` — не буквы ни одного из трёх
// языков и не разметка: модели нечего в них «перевести». Латинские скобки
// (`[[1]]`) модель охотно переписывает под язык ответа.
const TRANSLATE_HOLD = (at) => `⟦${at}⟧`;

// Буквы, по которым узнаётся язык выделенного куска.
const TRANSLATE_UK_ONLY = /[іїєґІЇЄҐ]/;
const TRANSLATE_RU_RANGE = /[а-яёА-ЯЁ]/;


/**
 * Раздел перевода для большого окна текста: три флага.
 *
 * Ставится в шапку окна **перед** кнопкой «Закрыть и сохранить»: действие над
 * текстом должно стоять рядом с текстом, а не за кнопкой выхода.
 *
 * @param {HTMLTextAreaElement} big поле окна — из него берётся выделение, в
 *     него же возвращается перевод.
 * @param {Function} after зовётся после замены: окну надо перерисовать
 *     подсветку и отзеркалить текст в исходное поле.
 * @returns {HTMLElement} готовый раздел.
 */
export function textTranslateSection(big, after) {
    const box = document.createElement('div');
    box.className = 'text-translate';
    box.style = 'display: flex; align-items: center; gap: 4px;';

    const hint = document.createElement('span');
    hint.textContent = 'перевести выделенное:';
    hint.style = 'font-size: 11px; font-weight: 500; color: #94a3b8;';
    box.appendChild(hint);

    TRANSLATE_LANGS.forEach(lang => box.appendChild(_flag(big, lang, after)));

    return box;
}


/**
 * Заслонить метки: текст для модели и список снятого.
 *
 * ⚠ Экспортируется ради тестов: правило «метка до модели не доходит» — то
 * единственное, что здесь обязано держаться, и проверять его надо прямо.
 *
 * @returns {{text: string, marks: string[]}}
 */
export function textTranslateMask(text) {
    const marks = [];

    const masked = String(text ?? '').replace(TRANSLATE_MARK_RE, (found) => {
        marks.push(found);

        return TRANSLATE_HOLD(marks.length - 1);
    });

    return {text: masked, marks};
}


/**
 * Вернуть метки на место.
 *
 * ⚠⚠ Возвращает `null`, если хоть одна заслонка не доехала. Это **не** повод
 * подставить что-нибудь: промпт без метки тих и сломан, а промпт непереведённый
 * просто непереведён.
 *
 * ⚠ Пробелы внутри заслонки модель иногда добавляет (`⟦ 2 ⟧`) — их прощаем:
 * номер цел, значит цела и метка.
 *
 * @returns {string|null} текст с метками или `null`, если что-то потерялось.
 */
export function textTranslateUnmask(text, marks) {
    let out = String(text ?? '');

    for (let at = 0; at < marks.length; at++) {
        const hold = new RegExp(`⟦\\s*${at}\\s*⟧`, 'g');
        if (!hold.test(out)) return null;

        out = out.replace(hold, () => marks[at]);
    }

    return out;
}


/**
 * Годится ли ответ модели в замену выделенному.
 *
 * ## ⚠⚠⚠ Единственное место, где решается «писать или не писать»
 *
 * Правил два, и оба куплены живым прогоном.
 *
 * **Пустой ответ — отказ.** Кусок промпта с `[[girl_name]]` и `[<if …>]`,
 * отданный модели **без** заслонки, вернулся пустой строкой: не ошибкой, не
 * отказом — пустотой. Заслонка это чинит, но опустеть ответ может и по другой
 * причине, и тогда выделенный абзац просто **стёрся бы**. На тексте с метками
 * спасает второе правило, а на тексте без меток не спасало ничто:
 * `unmask('', [])` — законная пустая строка.
 *
 * **Потерянная метка — отказ.** Разбор в шапке модуля.
 *
 * @returns {{text: string}|{error: string}} текст к замене либо причина отказа.
 */
export function textTranslateAccept(result, marks) {
    const text = String(result ?? '');

    if (!text.trim()) {
        return {error: 'Перевод пришёл пустым — текст оставлен как был.'};
    }

    const back = textTranslateUnmask(text, marks);

    if (back === null) {
        return {error: `Перевод потерял метки (${marks.length} шт.) — текст `
            + 'оставлен как был. Выделите кусок поменьше или без меток.'};
    }

    return {text: back};
}


/**
 * Какой это язык — по буквам, а не по словарю.
 *
 * ⚠ Грубо и намеренно: ручка перевода требует язык источника, а человеку
 * спрашивать его незачем — он и так видит, что выделил. Ошибка различения
 * `ru`/`uk` стоит одного лишнего слова в промпте модели, не больше: правило 4
 * у переводчика — «уже на целевом языке верни как есть».
 */
export function textTranslateGuess(text) {
    const one = String(text ?? '');

    if (TRANSLATE_UK_ONLY.test(one)) return 'uk';
    if (TRANSLATE_RU_RANGE.test(one)) return 'ru';

    return 'en';
}


// ── Приватное ────────────────────────────────────────────────────────────────

function _flag(big, lang, after) {
    const btn = document.createElement('button');
    // ⚠ `type="button"`: окно живёт в `document.body`, но поле шага — в форме, и
    // кнопка по умолчанию отправила бы её.
    btn.type = 'button';
    btn.textContent = lang.flag;
    btn.title = `Перевести выделенное на ${lang.word}`;
    btn.style = 'border: 1px solid #cbd5e1; background: #fff; border-radius: 5px;'
        + ' cursor: pointer; font-size: 15px; line-height: 1; padding: 4px 7px;';

    btn.onmouseenter = () => { btn.style.background = '#f1f5f9'; };
    btn.onmouseleave = () => { btn.style.background = '#fff'; };

    btn.onclick = () => _translate(big, lang, btn, after);

    return btn;
}

async function _translate(big, lang, btn, after) {
    const from = big.selectionStart;
    const to = big.selectionEnd;
    const picked = big.value.slice(from, to);

    // ⚠ Выделения нет — говорим, а не переводим всё поле. «Нажал не подумав» на
    // промпте в четыре тысячи знаков стоило бы целого промпта.
    if (!picked.trim()) {
        showNotification('Выделите текст, который надо перевести', 'error');

        return;
    }

    const source = textTranslateGuess(picked);
    if (source === lang.code) {
        showNotification(`Выделенное и так на ${lang.word}`, 'info');

        return;
    }

    const {text, marks} = textTranslateMask(picked);

    const was = btn.textContent;
    btn.disabled = true;
    btn.textContent = '…';

    try {
        const answer = await postData('/translate', {
            text: text,
            language_from: source,
            language_to: lang.code,
        });

        const verdict = textTranslateAccept(answer.result, marks);

        if (verdict.error) {
            showNotification(verdict.error, 'error');

            return;
        }

        _replace(big, from, to, verdict.text, after);
        showNotification(`Переведено на ${lang.word}`, 'success');
    } catch (e) {
        showNotification(`Не перевелось: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = was;
    }
}

/**
 * Заменить выделенное переводом.
 *
 * ⚠⚠ Через `setRangeText`, а не склейкой `value`: та стирает историю отмены, и
 * `Ctrl+Z` после неудачного перевода не вернул бы прежний текст. Перевод —
 * ровно то действие, которое хочется отменить.
 *
 * ⚠ Выделение остаётся на новом куске: человек смотрит, что получилось, и
 * следующий флаг действует на тот же кусок, если перевод не понравился.
 */
function _replace(big, from, to, text, after) {
    big.focus();
    big.setRangeText(text, from, to, 'select');

    // ⚠ `input` руками: `setRangeText` события не шлёт, а на нём держится и
    // подсветка окна, и запись в метаданные шага.
    big.dispatchEvent(new Event('input', {bubbles: true}));

    if (after) after();
}
