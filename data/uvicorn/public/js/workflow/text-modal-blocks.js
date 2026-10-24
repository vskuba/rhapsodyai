// Строй блоков промпта: кто кому пара и что осталось без пары.
//
// Подсветка красит метку за меткой и про соседей не знает: для неё
// `[<endif>]` — просто слово разметки, лишний он или нет. А лишний `[<endif>]`
// это не косметика. Движок **не сворачивает непонятое** (`workflow.md`,
// §«Что считается поломкой»): сломанный блок уезжает в модель словами, и в
// журнале при этом чисто — ни ошибки, ни следа. Увидеть такое можно только
// глазами, в редакторе, до сохранения.
//
// ⚠ Здесь считается **строй, а не смысл**. Истинность условия, приоритет
// связок, значения переменных — дело движка (`ai_workflow_condition_check`), и
// второй копии этих правил тут нет. Вопрос, на который отвечает этот файл,
// ровно один: у какой метки нет пары.

import {TEXT_MODAL_BAD_OP_RE, TEXT_MODAL_BLOCK_RE} from './text-modal-syntax.js';

// Какой закрывающей меткой закрывается какая открывающая.
const TEXT_MODAL_BLOCK_CLOSE = {if: 'endif', for: 'endfor'};


/** Разбирает строй блоков: пары и беспарные метки.
 *
 * @param {string} text Текст поля.
 * @returns {{broken: Set<number>, mates: Map<number, number[]>}}
 *     `broken` — индексы начал меток, у которых пары нет;
 *     `mates` — от индекса метки к индексам **всех** её родственниц
 *     (`[<if>]` ↔ `[<else>]` ↔ `[<endif>]` знают друг о друге).
 *
 * ⚠⚠ Беспарной метка считается в трёх случаях, и все три разные:
 *
 *     [<endif>] без открытого блока   — закрывать нечего
 *     [<endfor>] поверх [<if …>]      — закрывает не то, что открыто
 *     [<if …>] без [<endif>] до конца — блок не закрыт вовсе
 *
 * ⚠ Четвёртым идёт `&&` или `||` в условии: связок с такой записью у движка
 * нет, и блок целиком уедет в текст. Это примета, а не разбор — см.
 * `TEXT_MODAL_BAD_OP_RE`.
 */
export function textModalBlocksScan(text) {
    const source = String(text ?? '');
    const broken = new Set();
    const mates = new Map();
    const stack = [];

    for (const tag of source.matchAll(TEXT_MODAL_BLOCK_RE)) {
        const at = tag.index;
        const open = tag[1];
        const close = tag[2];

        if (open) {
            // ⚠ Негодная связка метит саму открывающую метку, но блока не
            // ломает: `[<endif>]` ниже по-прежнему её пара. Иначе одна опечатка
            // красила бы красным всё до конца текста.
            if (TEXT_MODAL_BAD_OP_RE.test(tag[0])) broken.add(at);

            stack.push({at, kind: open, family: [at]});
            continue;
        }

        const top = stack[stack.length - 1];

        if (!top) {
            // Закрывающая без открытой — закрывать нечего.
            broken.add(at);
            continue;
        }

        if (close === 'else') {
            // ⚠ `[<else>]` глубины не меняет и блока не закрывает: он остаётся
            // в семье и ждёт своего `[<endif>]` вместе с остальными.
            top.family.push(at);
            continue;
        }

        if (close !== TEXT_MODAL_BLOCK_CLOSE[top.kind]) {
            // `[<endfor>]` поверх `[<if …>]`: закрывает не то, что открыто.
            // ⚠ Стек не трогаем — открытый блок так и остался открытым, и о
            // нём будет сказано отдельно, в конце.
            broken.add(at);
            continue;
        }

        top.family.push(at);
        stack.pop();

        for (const one of top.family) mates.set(one, top.family);
    }

    // Что осталось открытым — не закрыто до конца текста. Вместе с ним беспарны
    // и его `[<else>]`: без `[<endif>]` они тоже никуда не ведут.
    for (const left of stack) {
        for (const one of left.family) broken.add(one);
    }

    return {broken, mates};
}


/** Родня метки, внутри которой стоит курсор; пусто — курсор не на метке.
 *
 * @param {string} text Текст поля.
 * @param {number} caret Положение курсора в тексте.
 * @param {Map<number, number[]>} mates Пары из `textModalBlocksScan`.
 * @returns {number[]} Индексы начал меток-родственниц, включая ту, что под
 *     курсором.
 *
 * ⚠ Курсор считается «на метке», когда он внутри неё **или вплотную к любому
 * её краю**: человек ставит курсор щелчком, и попасть строго внутрь `[<else>]`
 * мышью труднее, чем в его край.
 */
export function textModalBlocksAtCaret(text, caret, mates) {
    const source = String(text ?? '');
    const at = Number(caret);

    if (!Number.isFinite(at)) return [];

    for (const tag of source.matchAll(TEXT_MODAL_BLOCK_RE)) {
        if (at < tag.index || at > tag.index + tag[0].length) continue;

        return mates.get(tag.index) || [];
    }

    return [];
}
