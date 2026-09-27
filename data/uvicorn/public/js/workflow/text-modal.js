// Большой текст поля шага — в окне на весь экран, а не в узкой колонке.
//
// Промпты бывают на три-четыре тысячи знаков, а поле в колонке деталей шага высотой
// 170 пикселей: читать и править приходится прокруткой в семь строк. Иконка рядом с
// подписью поля открывает то же самое во весь экран.
//
// ⚠⚠ Окно **не заводит своего сохранения.** Оно пишет в исходную `textarea` и
// пинает её теми же событиями, которыми пользуется страница: `input` обновляет
// метаданные шага (`saveChanges` в `step-widgets.js`), `focusout` заводит отправку на
// сервер (делегирование на `#stepDetailsView` в `steps.js`). Своя отправка была бы
// второй дорогой к одному и тому же — и разошлась бы с первой на первой же правке.
//
// ⚠ Поэтому окно живёт в `document.body`, а не внутри колонки: делегирование ловит
// события **исходного** поля, и лишние всплытия из окна ему только мешали бы.

// Сколько места занимает окно. ⚠ Не 100%: рамка экрана нужна, чтобы «щёлкнуть в
// сторону» было куда — этим окно и закрывается.
const TEXT_MODAL_SIZE = '92vw';
const TEXT_MODAL_HEIGHT = '88vh';

// Цвет иконки и кнопки закрытия. ⚠ Одной константой: они про одно действие — «этот
// текст открывается большим», — и разойдись цвета, связь между ними читалась бы не
// сразу.
const TEXT_MODAL_COLOR = '#ea580c';

export function textModalIcon(textarea, title = '') {
    // Иконка открытия. ⚠ `type="button"`: поле шага лежит в форме, и кнопка по
    // умолчанию отправила бы её.
    const icon = document.createElement('button');
    icon.type = 'button';
    icon.title = 'Открыть в большом окне';
    icon.textContent = '⛶';
    // ⚠ Цветом, а не серым: рядом с подписью поля иконка должна быть заметна —
    // иначе о большом окне никто не узнает, а ради него всё и делалось.
    icon.style = `border: 1px solid ${TEXT_MODAL_COLOR}; background: #fff7ed;`
        + ` color: ${TEXT_MODAL_COLOR};`
        + ' border-radius: 4px; cursor: pointer; font-size: 12px; line-height: 1;'
        + ' padding: 3px 7px; font-weight: 700;';

    icon.onmouseenter = () => {
        icon.style.background = TEXT_MODAL_COLOR;
        icon.style.color = '#fff';
    };
    icon.onmouseleave = () => {
        icon.style.background = '#fff7ed';
        icon.style.color = TEXT_MODAL_COLOR;
    };

    icon.onclick = () => textModalOpen(textarea, title);

    return icon;
}

export function textModalOpen(textarea, title = '') {
    const back = document.createElement('div');
    back.style = 'position: fixed; inset: 0; background: rgba(15, 23, 42, .45);'
        + ' display: flex; align-items: center; justify-content: center;'
        + ' z-index: 9999;';

    const box = document.createElement('div');
    box.style = `width: ${TEXT_MODAL_SIZE}; height: ${TEXT_MODAL_HEIGHT};`
        + ' background: #fff; border-radius: 8px; padding: 14px;'
        + ' display: flex; flex-direction: column; gap: 10px;'
        + ' box-shadow: 0 18px 50px rgba(15, 23, 42, .35);';

    const head = document.createElement('div');
    head.style = 'display: flex; align-items: center; justify-content: space-between;'
        + ' gap: 10px; font-size: 13px; font-weight: 600; color: #4a5568;';

    const name = document.createElement('span');
    name.textContent = title || 'Текст поля';

    // ⚠⚠ **Кнопка, а не подсказка.** Сперва здесь стояли слова «щелчок вне окна или
    // Esc — закрыть и сохранить»: правда, но требует прочитать и поверить. Кнопка
    // отвечает на тот же вопрос действием, а два прежних пути никуда не делись —
    // щелчок в сторону и `Esc` закрывают так же и тем же кодом.
    const done = document.createElement('button');
    done.type = 'button';
    done.textContent = 'Закрыть и сохранить';
    done.style = `background: ${TEXT_MODAL_COLOR}; color: #fff; border: none;`
        + ' border-radius: 5px; cursor: pointer; font-size: 12px; font-weight: 600;'
        + ' padding: 7px 14px;';
    done.onmouseenter = () => { done.style.background = '#c2410c'; };
    done.onmouseleave = () => { done.style.background = TEXT_MODAL_COLOR; };

    head.appendChild(name);
    head.appendChild(done);

    // ── Поле: два слоя, совпадающие до пикселя ───────────────────────────────
    //
    // ⚠ Обёртка нужна, чтобы слои легли друг на друга (`position: absolute` по
    // `inset: 0`), и при этом тянулись по высоте окна вместе с ним.
    const field = document.createElement('div');
    field.style = 'position: relative; flex: 1 1 auto; min-height: 0;'
        + ' border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden;'
        + ' background: #fff;';

    // Нижний слой — цвета. ⚠ `aria-hidden`: для читающих с экрана это дубль того же
    // текста, который лежит в поле выше.
    const paint = document.createElement('pre');
    paint.setAttribute('aria-hidden', 'true');
    paint.style = `position: absolute; inset: 0; overflow: auto; ${HL_FONT}`
        + ' color: #1f2937; pointer-events: none;';

    // Верхний слой — настоящее поле. ⚠ Текст прозрачный, а курсор нет: набирают
    // здесь, а видят нижний слой.
    const big = document.createElement('textarea');
    big.value = textarea.value;
    big.spellcheck = false;
    big.style = `position: absolute; inset: 0; ${HL_FONT}`
        + ' width: 100%; height: 100%; resize: none; border: none; outline: none;'
        + ' background: transparent; color: transparent; caret-color: #111827;';

    // ⚠⚠ Прокрутка **ведомая**: скроллит человек поле, а `<pre>` лишь повторяет.
    // Своя прокрутка у нижнего слоя означала бы, что цвет отстаёт от буквы на
    // случайное число строк.
    const follow = () => {
        paint.scrollTop = big.scrollTop;
        paint.scrollLeft = big.scrollLeft;
    };

    const repaint = () => {
        paint.innerHTML = textModalHighlight(big.value);
        follow();
    };

    big.addEventListener('scroll', follow);
    big.addEventListener('input', repaint);

    field.appendChild(paint);
    field.appendChild(big);

    box.appendChild(head);
    box.appendChild(field);
    back.appendChild(box);
    document.body.appendChild(back);

    // ⚠⚠ Пишем в исходное поле **на каждый ввод**, а не при закрытии: страница
    // сохраняет шаг сама, и закройся окно нештатно (перезагрузка, промах по кнопке
    // браузера) — текст всё равно уже в метаданных.
    const mirror = () => {
        textarea.value = big.value;
        textarea.dispatchEvent(new Event('input', {bubbles: true}));
    };

    big.addEventListener('input', mirror);

    const close = () => {
        mirror();
        // ⚠ `focusout` — то самое событие, на котором страница отправляет шаг на
        // сервер. Всплывающее, иначе делегирование на колонку его не увидит.
        textarea.dispatchEvent(new FocusEvent('focusout', {bubbles: true}));

        document.removeEventListener('keydown', onKey);
        back.remove();
    };

    // ⚠ Щелчок **по подложке**, а не внутри окна: без проверки цели закрытие
    // срабатывало бы и на выделении текста мышью, стоило отпустить кнопку над
    // краем поля.
    back.addEventListener('mousedown', (e) => {
        if (e.target === back) close();
    });

    function onKey(e) {
        if (e.key === 'Escape') close();
    }

    document.addEventListener('keydown', onKey);

    // ⚠ Кнопка зовёт **то же** `close`, а не своё сохранение: три пути выхода —
    // кнопка, щелчок в сторону, `Esc`, — и разойдись они, один сохранял бы, а другой
    // нет. Заметить это можно было бы только потерянной правкой.
    done.onclick = close;

    repaint();

    big.focus();
    // Курсор в начало: текст читают с начала, а `focus()` ставит его в конец.
    big.setSelectionRange(0, 0);
    big.scrollTop = 0;
    follow();
}

// ── Подсветка: метки переменных и условная разметка ──────────────────────────
//
// ⚠⚠⚠ **Слой под настоящей `textarea`, а не `contenteditable`.**
//
// «Простой WYSIWYG» просился сделать поле редактируемым `div`-ом с цветными
// `span`-ами. Так нельзя: браузер правит содержимое такого поля сам — вставка несёт
// чужую разметку, `Enter` кладёт `<div>` или `<br>`, `execCommand` переносит стили, —
// и текст перестаёт быть тем, что набрали. Для промпта это не косметика: `%var%` и
// `[<if x>]` читает движок (`ai_workflow.py`), и покорёженная метка не подставится,
// а сломанный блок уедет в модель как есть.
//
// Поэтому цвета рисует `<pre>` **позади** прозрачной `textarea`: набор, отмена,
// выделение, вставка и ввод с клавиатуры остаются родными, а значение полем и
// остаётся — байт в байт. Видно при этом то же, что и у «настоящего» редактора.
//
// ⚠ Слои обязаны совпадать до пикселя: один шрифт, один кегль, один межстрочный
// интервал, одни поля и один перенос (`white-space: pre-wrap`). Разойдись хоть одно —
// цвет уползёт от буквы, и это будет хуже, чем без подсветки.

// Что подсвечиваем. ⚠ Правила **те же**, что у движка, и это не совпадение:
// подсветка, знающая другой синтаксис, врала бы — показывала бы меткой то, что
// движок меткой не считает.
//
//     WORKFLOW_MARK_RE      = %([a-zA-Z_][a-zA-Z0-9_]*)%
//     WORKFLOW_IF_BLOCK_RE  = \[<if (!?)(\w+)>\] … [<else>] … [<endif>]
//
// ⚠ Порядок в чередовании важен: разметка блока идёт первой, иначе `%`-правило
// откусило бы кусок из `[<if …>]`, если там однажды окажется процент.
//
// ⚠⚠ Открывающая метка разбирается **на части**, а не берётся целиком:
//
//     [<if   !   talk_history_chat   >]
//     ────   ─   ────────────────    ──
//     разметка   имя переменной      разметка
//
// Иначе имя внутри `[<if …>]` красилось бы зелёным, а то же имя в тексте — синим, и
// глаз терял бы связь между условием и переменной, о которой оно. Отрицание `!`
// остаётся с разметкой: это синтаксис, а не часть имени.
const HL_RE = new RegExp(
    '(\\[<\\s*if\\s+)(!?)(\\w+)(\\s*>\\])'   // открывающая, по частям
    + '|(\\[<\\s*(?:else|endif)\\s*>\\])'          // [<else>] и [<endif>]
    + '|(%[a-zA-Z_][a-zA-Z0-9_]*%)',                       // метка в тексте
    'g');

// Цвета. Метка — синяя, разметка блока — зелёная и жирная: это разные вещи, и
// человек различает их до чтения. Фон бледный, чтобы текст читался поверх.
const HL_MARK = 'color: #1d4ed8; background: #eff6ff; border-radius: 3px;';
const HL_BLOCK = 'color: #047857; background: #ecfdf5; border-radius: 3px;'
    + ' font-weight: 700;';

// Оформление, общее обоим слоям. ⚠ Одной строкой на оба: две копии разъезжаются, и
// разъехавшись, сдвигают цвет относительно буквы.
const HL_FONT = 'font-family: ui-monospace, SFMono-Regular, Menlo, monospace;'
    + ' font-size: 13px; line-height: 1.55; white-space: pre-wrap;'
    + ' word-break: break-word; padding: 10px; margin: 0;'
    + ' box-sizing: border-box;';


export function textModalHighlight(text) {
    let out = '';
    let at = 0;

    for (const found of String(text ?? '').matchAll(HL_RE)) {
        out += _escape(text.slice(at, found.index));

        if (found[1]) {
            // Открывающая метка: разметка — своим цветом, имя — цветом переменной.
            out += _paint(HL_BLOCK, found[1] + found[2])
                + _paint(HL_MARK, found[3])
                + _paint(HL_BLOCK, found[4]);
        } else {
            out += _paint(found[5] ? HL_BLOCK : HL_MARK, found[0]);
        }

        at = found.index + found[0].length;
    }

    out += _escape(String(text ?? '').slice(at));

    // ⚠ Хвостовой перевод строки `<pre>` съедает, а `textarea` — нет: без этого
    // последняя пустая строка сдвигала бы слои друг относительно друга.
    return out + '\n';
}


function _paint(style, text) {
    return `<span style="${style}">${_escape(text)}</span>`;
}


function _escape(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}
