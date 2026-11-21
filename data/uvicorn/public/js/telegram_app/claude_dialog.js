/**
 * claude_dialog.js — кнопки ответа на вопрос Claude Code во вкладке Claude.
 *
 * Вопрос приходит обычным текстом: его собирает оболочка claude-shell
 * (`shell.py`, `_permission_notify`) и кладёт ответом в `ai_claude_session`.
 * Структуры рядом нет, поэтому разбираем этот текст — его формат наш и стабилен.
 * Видов два:
 *
 *   простой  — заголовок, вопрос, строки «1. Да», хвост «Ответь номером…».
 *              Ответ — одна цифра.
 *   сложный  — блоки «Вопрос N. …» (с пометкой «(можно несколько)» у
 *              мультивыбора), варианты с отступом «   1. …», хвост
 *              «Ответь номерами вариантов…». Ответ — «1: 2,3; 2: 1».
 *
 * Ответ уходит тем же путём, что и набранный руками: оболочка разбирает его
 * `_ask_answer_parse` и сама жмёт клавиши диалога (в мультивыборе — галочки,
 * переход и Submit). Отмена — слово «нет»: оболочка жмёт Esc.
 *
 * Не распознали текст — `claudeDialogParse` возвращает null, и пузырь остаётся
 * обычным текстом: ответить цифрой руками можно, как раньше.
 */

import { escapeHtml as esc } from './utils.js';

const CLAUDE_DIALOG_HEAD = '🔐 Claude ждёт ответа:';
const CLAUDE_DIALOG_TAIL_MULTI = 'Ответь номерами вариантов';
const CLAUDE_DIALOG_TAIL_SINGLE = 'Ответь номером';
const CLAUDE_DIALOG_CANCEL = 'нет';

const CLAUDE_DIALOG_QUESTION_RE = /^Вопрос (\d+)\.\s*(.*)$/;
const CLAUDE_DIALOG_OPTION_RE = /^\s*(\d+)\.\s+(.+)$/;
const CLAUDE_DIALOG_MULTI_MARK = ' (можно несколько)';
const CLAUDE_DIALOG_HIDDEN_MARK = '— не видно на экране';

/**
 * Разбор текста вопроса.
 *
 * @returns {null|{kind:'single', question:string, options:Array<{digit,label}>}
 *               |{kind:'multi', questions:Array<{index,title,multi,options}>}}
 */
export function claudeDialogParse(text) {
    const source = String(text || '');
    const start = source.indexOf(CLAUDE_DIALOG_HEAD);
    if (start < 0) return null;

    const lines = source.slice(start + CLAUDE_DIALOG_HEAD.length).split('\n');
    if (source.includes(CLAUDE_DIALOG_TAIL_MULTI)) return _parseMulti(lines);
    if (source.includes(CLAUDE_DIALOG_TAIL_SINGLE)) return _parseSingle(lines);
    return null;
}

/**
 * Рисует вопрос в пузыре вместо сырого текста.
 *
 * Нажатие на вариант только отмечает его: в одиночном выборе (радио) отметка
 * переезжает, в мультивыборе (галочки) копится. Уходит ответ кнопкой
 * «Отправить» — она загорается, когда отмечено хоть что-то.
 *
 * @param {HTMLElement} bubble — пузырь ответа Claude
 * @param {object} dialog — результат claudeDialogParse
 * @param {function(string, function):void} onAnswer — отправить строку ответа;
 *        второй довод — вызвать, если отправку отменили (кнопки снова живые)
 */
export function claudeDialogRender(bubble, dialog, onAnswer) {
    bubble.classList.add('claude-dialog');
    bubble.innerHTML = _html(dialog);
    bubble._claudeDialog = dialog;

    const submit = bubble.querySelector('[data-submit]');
    const send = (answer) => {
        if (!claudeDialogIsActive(bubble)) return;
        bubble.classList.add('claude-dialog-sent');
        onAnswer(answer, () => bubble.classList.remove('claude-dialog-sent'));
    };

    bubble.querySelectorAll('[data-q]').forEach(btn =>
        btn.addEventListener('click', () => {
            if (!claudeDialogIsActive(bubble)) return;
            const question = _questions(dialog)[Number(btn.dataset.q)];
            if (!question.multi) {
                bubble.querySelectorAll(`[data-q="${btn.dataset.q}"]`).forEach(other => {
                    if (other !== btn) other.classList.remove('picked');
                });
                btn.classList.add('picked');
            } else {
                btn.classList.toggle('picked');
            }
            submit.disabled = !_answer(bubble, dialog);
        }));
    submit.addEventListener('click', () => {
        const answer = _answer(bubble, dialog);
        if (answer) send(answer);
    });
    bubble.querySelector('[data-cancel]').addEventListener('click', () => send(CLAUDE_DIALOG_CANCEL));
}

/** Вопрос ещё открыт: кнопки жмутся. */
export function claudeDialogIsActive(bubble) {
    return bubble.classList.contains('claude-dialog')
        && !bubble.classList.contains('claude-dialog-closed')
        && !bubble.classList.contains('claude-dialog-sent');
}

/**
 * Открыть или закрыть вопрос. Закрытый остаётся на экране — по нему видно,
 * о чём спрашивали, — но кнопки не жмутся.
 */
export function claudeDialogSetClosed(bubble, closed) {
    bubble.classList.toggle('claude-dialog-closed', closed);
    bubble.querySelectorAll('button').forEach(btn => {
        if (btn.hasAttribute('data-submit')) {
            btn.disabled = closed || !_answer(bubble, bubble._claudeDialog);
        } else {
            btn.disabled = closed;
        }
    });
}

// ─── private ───────────────────────────────────────────────────────────────

function _parseSingle(lines) {
    // Снизу вверх: хвост с подсказкой, пустые строки, затем сплошной блок
    // вариантов. Всё, что выше блока, — текст вопроса (в нём самом могут
    // встретиться строки «1. …», поэтому сверху вниз искать нельзя).
    let end = lines.length - 1;
    while (end >= 0 && (!lines[end].trim() || lines[end].startsWith(CLAUDE_DIALOG_TAIL_SINGLE))) end--;

    const options = [];
    let i = end;
    for (; i >= 0; i--) {
        const match = lines[i].match(CLAUDE_DIALOG_OPTION_RE);
        if (!match) break;
        options.unshift({ digit: match[1], label: match[2].trim() });
    }
    if (!options.length) return null;

    return {
        kind: 'single',
        question: lines.slice(0, i + 1).join('\n').trim(),
        options,
    };
}

function _parseMulti(lines) {
    const questions = [];
    let current = null;
    for (const line of lines) {
        const head = line.match(CLAUDE_DIALOG_QUESTION_RE);
        if (head) {
            let title = head[2].trim();
            const multi = title.endsWith(CLAUDE_DIALOG_MULTI_MARK.trim());
            if (multi) title = title.slice(0, -CLAUDE_DIALOG_MULTI_MARK.trim().length).trim();
            current = {
                index: Number(head[1]),
                title,
                multi,
                hidden: title.startsWith(CLAUDE_DIALOG_HIDDEN_MARK),
                options: [],
            };
            questions.push(current);
            continue;
        }
        if (line.startsWith(CLAUDE_DIALOG_TAIL_MULTI)) break;
        const option = current && line.match(CLAUDE_DIALOG_OPTION_RE);
        if (option) current.options.push({ digit: option[1], label: option[2].trim() });
    }
    if (!questions.some(q => q.options.length)) return null;

    return { kind: 'multi', questions };
}

/** Вопросы для отрисовки: простой вид — это один вопрос с одиночным выбором. */
function _questions(dialog) {
    if (dialog.kind === 'multi') return dialog.questions;
    return [{ index: 1, title: dialog.question, multi: false, hidden: false, options: dialog.options }];
}

/**
 * Строка ответа в формате оболочки. Простой вид — голая цифра: так отвечают и
 * на диалоги разрешений, где «1: 2» оболочка приняла бы за отказ. Сложный —
 * «1: 2,3; 2: 1» с явными номерами вопросов; неотмеченный вопрос пропускается.
 */
function _answer(bubble, dialog) {
    if (!dialog) return '';
    const picked = (n) => [...bubble.querySelectorAll(`[data-q="${n}"].picked`)].map(b => b.dataset.digit);
    if (dialog.kind === 'single') return picked(0)[0] || '';

    const groups = [];
    dialog.questions.forEach((question, n) => {
        const digits = picked(n);
        if (digits.length) groups.push(`${question.index}: ${digits.join(',')}`);
    });
    return groups.join('; ');
}

function _html(dialog) {
    const questions = _questions(dialog);
    const blocks = questions.map((question, n) => {
        if (question.hidden || !question.options.length) {
            return '<div class="claude-dialog-block"><div class="claude-dialog-question">'
                + `${question.index}. Вопрос не виден на экране — останется без ответа</div></div>`;
        }
        const mark = question.multi
            ? '<span class="claude-dialog-mode">можно несколько</span>'
            : (questions.length > 1 ? '<span class="claude-dialog-mode">один вариант</span>' : '');
        const title = question.title
            ? `<div class="claude-dialog-question">${esc(question.title)} ${mark}</div>`
            : '';
        return '<div class="claude-dialog-block">' + title
            + '<div class="claude-dialog-options">'
            + question.options.map(o =>
                `<button type="button" class="claude-dialog-option ${question.multi ? 'multi' : 'single'}" `
                + `data-q="${n}" data-digit="${esc(o.digit)}">`
                + '<span class="claude-dialog-mark"></span>'
                + `<span class="claude-dialog-label">${esc(o.label)}</span></button>`).join('')
            + '</div></div>';
    }).join('');

    const hint = dialog.kind === 'multi' && questions.length > 1
        ? 'Вопрос можно пропустить — не отмечайте в нём ничего'
        : 'Или напишите текстом, что делать вместо этого';

    return '<div class="claude-dialog-head">🔐 Claude ждёт ответа</div>'
        + blocks
        + '<div class="claude-dialog-actions">'
        + '<button type="button" class="claude-dialog-submit" data-submit disabled>Отправить</button>'
        + '<button type="button" class="claude-dialog-cancel" data-cancel>Отменить</button>'
        + '</div>'
        + `<div class="claude-dialog-hint">${hint}</div>`;
}
