// Вкладка «Чат»: разговоры пары (`companion_session`).
//
// Строка здесь — ОБМЕН: «он спросил — мы ответили», с временем каждой половины
// и отметкой доставки. Половина умеет пустовать: заговорили мы (инвайт,
// письмо) — нет вопроса; он написал дважды подряд или агент смолчал — нет
// ответа. Поэтому обмен рисуется одним блоком из двух половин, а не двумя
// сообщениями подряд: иначе пропажу половины не отличить от конца разговора.
//
// ⚠⚠ Разговор опознаётся ТРОЙКОЙ: наша сторона, собеседник, канал. Чат и
// почта одной пары — разные разговоры (разной длины, разного тона, часто
// разных дней), и в таблице они держатся врозь намеренно.
//
// ⚠ Неподтверждённый ответ здесь ВИДЕН — в отличие от ленты, которую получает
// агент (`companion_session_rows` его прячет: продолжать несказанное нельзя).
// «Что сочинили, но не отправили» и есть вопрос, с которым сюда приходят.

import {postData} from '../api.js';
import {htmlEscape, selectFill, selectValueRestore} from './util.js';

const CHAT_STORE_PREFIX = 'session_chat_';

// Номер последнего начатого запроса. Ответ не своего номера выбрасывается.
//
// ⚠⚠ Без него отборы разъезжаются на быстром клике. Поймано прогоном: канал
// сменили на «почту», следом доставку на «не доставлено» — и список разговоров
// остался от первого отбора, а лента открытого разговора пришла по второму.
// Человек видел «3 обмена в списке, 0 в ленте» и не мог понять, какой из двух
// отборов сейчас показан. Счётчик один на вкладку: смена разговора так же
// отменяет недоехавшую ленту предыдущего.
let chatRequest = 0;

// ULID — 26 знаков в алфавите Крокфорда (без I, L, O, U). У этого семейства
// ключей приставки нет вовсе, и узнаётся оно только по форме.
const CHAT_SOURCE_ULID = /^[0-9A-HJKMNP-TV-Z]{26}$/;

const el = {};
const state = {
    // Полная выборка разговоров: из неё строятся отборы сторон со счётчиками.
    // Перезаписывать её отфильтрованным результатом нельзя — тот же довод, что
    // на соседней вкладке.
    pairs: [],
    // Выбранный разговор тройкой — её же отправляем за обменами.
    current: null,
};

export async function sessionChatInit() {
    el.owner = document.getElementById('chatSessionOwner');
    el.companion = document.getElementById('chatSessionCompanion');
    el.kind = document.getElementById('chatSessionKind');
    el.delivered = document.getElementById('chatSessionDelivered');
    el.limit = document.getElementById('chatSessionLimit');
    el.list = document.getElementById('chatSessionSelect');
    el.title = document.getElementById('chatSessionTitle');
    el.stream = document.getElementById('chatSessionStream');

    try {
        await kindsLoad();
        await pairsLoadAll();
        filtersBind();
        await pairsLoad();
    } catch (e) {
        el.stream.innerHTML =
            `<div class="placeholder">Ошибка загрузки: ${htmlEscape(e.message)}</div>`;
    }
}

// ===================== Справочники и отборы =====================

async function kindsLoad() {
    const data = await fetch('/session/companion/kind/list').then(r => r.json());

    // «Все каналы» остаётся первым вариантом — он уже стоит в шаблоне.
    (data.result || []).forEach(kind => el.kind.add(new Option(kind, kind)));

    ['kind', 'delivered', 'limit'].forEach(name => {
        selectValueRestore(el[name], sessionStorage.getItem(CHAT_STORE_PREFIX + name));
    });
}

/** Полная выборка разговоров — только чтобы наполнить отборы сторон.
 *
 * ⚠ Запрос без отборов, отдельно от основного: списку в сайдбаре нужен отбор,
 * а отборам — все стороны. Собери их из отфильтрованного ответа, и выбранный
 * собеседник выкинул бы из списка всех остальных.
 *
 * ⚠ Второй запрос здесь не сокращают, в отличие от соседней вкладки: там
 * полная выдача — 780 КБ (строка на сессию, их тысячи), здесь — строка на
 * пару, двадцать килобайт. Платить за это ветвлением в двух местах дороже,
 * чем самим запросом.
 */
async function pairsLoadAll() {
    const data = await postData('/session/companion/list', {});

    state.pairs = data.result || [];

    sidesFill();
    selectValueRestore(el.owner, sessionStorage.getItem(`${CHAT_STORE_PREFIX}owner_id`));
    // Собеседники сужаются нашей стороной — перезаполняем после восстановления.
    companionFill();
    selectValueRestore(el.companion,
        sessionStorage.getItem(`${CHAT_STORE_PREFIX}companion_id`));
}

function sidesFill() {
    selectFill(el.owner, [
        {value: '', text: `Все (${countOf(state.pairs)} обменов)`},
        ...sideEntries(state.pairs, 'owner'),
    ]);
    companionFill();
}

function companionFill() {
    const ownerId = numberOf(el.owner.value);
    const scoped = ownerId
        ? state.pairs.filter(one => one.owner_id === ownerId)
        : state.pairs;

    selectFill(el.companion, [
        {value: '', text: `Все (${countOf(scoped)} обменов)`},
        ...sideEntries(scoped, 'companion'),
    ]);
}

function filtersBind() {
    el.owner.onchange = async () => {
        sessionStorage.setItem(`${CHAT_STORE_PREFIX}owner_id`, el.owner.value);
        companionFill();
        sessionStorage.setItem(`${CHAT_STORE_PREFIX}companion_id`, el.companion.value);
        await pairsLoad();
    };

    el.companion.onchange = async () => {
        sessionStorage.setItem(`${CHAT_STORE_PREFIX}companion_id`, el.companion.value);
        await pairsLoad();
    };

    // Канал и доставка отбирают и список разговоров, и обмены внутри: условие
    // одно и то же, и расходиться им незачем — «разговоров нет» и «в разговоре
    // нет обменов» иначе означали бы разные отборы.
    ['kind', 'delivered'].forEach(name => {
        el[name].onchange = async () => {
            sessionStorage.setItem(CHAT_STORE_PREFIX + name, el[name].value);
            await pairsLoad();
        };
    });

    el.limit.onchange = () => {
        sessionStorage.setItem(`${CHAT_STORE_PREFIX}limit`, el.limit.value);

        if (state.current) exchangesLoad(state.current);
    };

    el.list.onchange = () => {
        const pair = state.shown?.[el.list.selectedIndex];

        if (pair) exchangesLoad(pair);
    };
}

// ===================== Разговоры =====================

async function pairsLoad() {
    const request = ++chatRequest;

    el.list.innerHTML = '<option>Загрузка...</option>';

    const data = await postData('/session/companion/list', filtersValue());

    if (request !== chatRequest) return;

    const pairs = data.result || [];

    // Список разговоров держим рядом с `<select>`: разговор опознаётся тройкой,
    // а в `value` варианта влезает только строка. Строка-ключ («12:34:chat»)
    // работала бы, но её пришлось бы разбирать обратно — лишний формат на
    // ровном месте.
    state.shown = pairs;
    el.list.innerHTML = '';

    pairs.forEach(one => {
        // Строка списка отвечает на «кто с кем»: обе стороны, в том же порядке
        // и теми же именами, что в шапке ленты и в подписях половин обмена.
        //
        // ⚠ Длинная строка в `<select>` обрезается справа и БЕЗ многоточия —
        // то, что не влезло, выглядит как конец имени. Поэтому у списка свои
        // ширина и кегль (`css/session.css`), а полная подпись с ключами
        // сторон всегда есть подсказкой.
        const option = new Option(
            `${fmtTz(one.last_at)} ${sideLabel(one, 'owner')}`
            + ` → ${sideLabel(one, 'companion')}`
            + ` ${one.kind === 'mail' ? '✉' : '💬'}${one.exchange_count}`
            + `${one.undelivered_count > 0 ? ` ⏳${one.undelivered_count}` : ''}`,
            String(one.companion_id));

        option.title = pairTip(one);
        el.list.add(option);
    });

    if (!pairs.length) {
        state.current = null;
        el.title.textContent = 'Нет разговоров под этот отбор';
        el.stream.innerHTML = '<div class="placeholder">Нет разговоров</div>';

        return;
    }

    el.list.selectedIndex = 0;
    await exchangesLoad(pairs[0]);
}

// ===================== Лента обменов =====================

async function exchangesLoad(pair) {
    const request = ++chatRequest;

    state.current = pair;
    el.title.textContent = `${sideLabel(pair, 'owner')} ↔ ${sideLabel(pair, 'companion')}`;
    el.stream.innerHTML = '<div class="placeholder">Загрузка...</div>';

    try {
        const data = await postData('/session/companion/messages', {
            owner_id: pair.owner_id,
            companion_id: pair.companion_id,
            // Канал берём у РАЗГОВОРА, а не у отбора: отбор может стоять на
            // «все каналы», но открытый разговор — всегда один канал, и
            // подмешать в него письма значило бы показать не ту переписку.
            kind: pair.kind,
            delivered: el.delivered.value,
            limit: parseInt(el.limit.value, 10),
        });

        if (request !== chatRequest) return;

        exchangesRender(pair, data.result || []);
    } catch (e) {
        el.stream.innerHTML =
            `<div class="placeholder">Ошибка загрузки: ${htmlEscape(e.message)}</div>`;
    }
}

function exchangesRender(pair, rows) {
    // Ключи сторон — подсказкой на заголовке: в строке они съели бы её целиком
    // (`966e95ea_Zinaida-Test`), а без них два разговора с одинаковыми именами
    // в шапке неразличимы.
    el.title.title = pairTip(pair);
    el.title.innerHTML =
        `${htmlEscape(sideLabel(pair, 'owner'))} ↔ ${htmlEscape(sideLabel(pair, 'companion'))}`
        + `<span class="detail-header-note">· ${htmlEscape(pair.kind)},`
        + ` показано ${rows.length} из ${pair.exchange_count} обменов</span>`;

    if (!rows.length) {
        el.stream.innerHTML = '<div class="placeholder">Нет обменов под этот отбор</div>';

        return;
    }

    el.stream.innerHTML = rows.map(row => exchangeHtml(pair, row)).join('');
}

function exchangeHtml(pair, row) {
    // Отметки доставки нет только у НАШЕЙ половины: его слова доставлены самим
    // фактом прихода. Поэтому чип считает ответ, а не строку, и у обмена без
    // ответа его нет вовсе.
    const answered = String(row.answer || '') !== '';
    const delivered = Boolean(row.delivered_at);

    // Отметки обмена едут в конец НАШЕЙ строки, а не в шапку.
    //
    // ⚠ Доставка — про наш ответ: его слова доставлены самим фактом прихода,
    // и у обмена без ответа чипа нет вовсе.
    //
    // ⚠ `source_uid` — ключ строки у источника, а не половины: он стоит и там,
    // где есть обе реплики, и там, где одна. Нашей строке он отдан потому, что
    // в двух третях строк (109 из 203 на установке) вопроса нет вовсе —
    // инвайты и письма, которые отправили мы, — и на половине собеседника чип
    // оказался бы рядом с прочерком.
    //
    // ⚠ В чипе доставки слово, а не время: само время стоит столбцом ПЕРЕД
    // репликой, и в чипе оно было бы вторым отпечатком того же значения.
    const marks = [
        answered ? (delivered
            ? '<span class="chip chip-delivered">✓ доставлено</span>'
            : '<span class="chip chip-undelivered">⏳ не доставлено</span>') : '',
        row.source_uid
            ? `<span class="chip chip-source" title="ключ у источника: ${htmlEscape(row.source_uid)}">`
              + `${htmlEscape(sourceLabel(row.source_uid))}</span>`
            : '',
    ].filter(Boolean).join('');

    // ⚠ Даты в шапке обмена нет. Она была `COALESCE(question_at, answer_at,
    // created_at)`, то есть всегда повторяла время одной из половин — те стоят
    // строкой ниже, своими столбцами. Строк, где обе половины без времени, не
    // бывает (инструмент не пишет обмен, у которого пусты обе), так что
    // прятать здесь нечего. `created_at` — когда строка легла в базу, а не
    // когда это сказали; у привезённых он на месяц позже разговора, поэтому
    // живёт подсказкой, а не строкой.
    return `
        <div class="chat-exchange">
            <div class="chips-container">
                <span class="chip chip-id" title="строка в базе с ${fmtTz(row.created_at)}">#${htmlEscape(row.id)}</span>
            </div>
            ${halfHtml({
                side: 'his',
                who: sideLabel(pair, 'companion'),
                text: row.question,
                // Его реплика доставлена самим фактом прихода, поэтому в левом
                // столбце стоит время, когда он её написал.
                timeBefore: row.question_at,
                timeBeforeHint: 'написано собеседником',
            })}
            ${halfHtml({
                side: 'ours',
                who: sideLabel(pair, 'owner'),
                text: row.answer,
                // ⚠⚠ Слева — ДОСТАВКА, справа — СОЧИНЕНИЕ. Левый столбец у
                // обеих половин отвечает на один вопрос: «когда это увидел
                // собеседник». Читая его сверху вниз, видишь разговор таким,
                // каким он был у него, — а не таким, в каком порядке мы
                // работали. Когда ответ был сочинён, вопрос отдельный, и он
                // уехал в хвост строки, к отметкам.
                timeBefore: row.delivered_at,
                timeBeforeHint: 'доставлено собеседнику',
                timeAfter: row.answer_at,
                timeAfterHint: 'ответ сочинён',
                undelivered: answered && !delivered,
                marks,
            })}
        </div>
    `;
}

/** Одна половина обмена: кто, когда увидел собеседник, что сказано, и хвост.
 *
 * Раскладка строки — `кто | время | реплика | время и отметки`:
 *
 *     Frank   17:03  Hi babe... i can kiss you all over
 *     Diana   17:09  smooth talker…                17:07  ✓ доставлено  panel
 *
 * ⚠⚠ **Левый столбец у обеих половин отвечает на один вопрос — «когда это
 * увидел собеседник».** У его реплики это время, когда он её написал (его
 * слова доставлены самим фактом прихода), у нашей — время доставки. Читая
 * столбец сверху вниз, видишь разговор таким, каким он был у собеседника, а
 * не таким, в каком порядке работали мы.
 *
 * ⚠ **Когда ответ был сочинён — отдельный вопрос, и он в хвосте строки.** Это
 * внутреннее время: между ним и доставкой стоит отправка, которая может
 * опоздать или не случиться вовсе. Поставь оба времени рядом слева — и они
 * читались бы как одно уточнённое, а не как два события.
 *
 * ⚠ Время, прижатое к правому краю реплики, уезжало бы у длинного письма то к
 * первой строке, то к последней — поэтому слева именно столбец, ровный на всю
 * ленту, а в хвосте стоит только то, что относится к строке целиком.
 *
 * ⚠ `who` — это заголовок записи `companion`, то есть данные из базы: без
 * экранирования имя с угловой скобкой разорвало бы ленту.
 *
 * ⚠ Имена сторон, а не «он»/«мы». В ленте для промпта наоборот — там роли
 * (`companion_session_history`), и причина там своя: имя собеседника приходит
 * не всегда, а роль не пустеет никогда. Человеку же лента показывается рядом
 * со списком разговоров, где стороны названы именами, — и «мы» в ней означало
 * бы разную персону в соседних строках списка.
 */
function halfHtml({side, who, text, timeBefore, timeBeforeHint = '',
                   timeAfter = null, timeAfterHint = '', undelivered = false,
                   marks = ''}) {
    // Пустая половина не выкидывается, а показывается прочерком: «он написал
    // дважды подряд» и «агент смолчал» — разные события, и обмен без половины
    // обязан отличаться от обмена, которого не было.
    const content = String(text || '') !== ''
        ? htmlEscape(text)
        : '<span class="chat-half-empty">— пусто —</span>';
    // ⚠ Два голых штампа в одной строке без подсказок не различить: оба
    // выглядят датой. Какой из них что — сказано наведением.
    const tail = [
        timeAfter
            ? `<span class="chat-half-time chat-half-time-tail"`
              + ` title="${htmlEscape(timeAfterHint)}">${fmtTz(timeAfter)}</span>`
            : '',
        marks,
    ].filter(Boolean).join('');

    return `
        <div class="chat-half chat-half-${side}${undelivered ? ' chat-half-undelivered' : ''}">
            <div class="chat-half-who" title="${htmlEscape(who)}">${htmlEscape(who)}</div>
            <div class="chat-half-time" title="${htmlEscape(timeBeforeHint)}">${
                timeBefore ? fmtTz(timeBefore) : ''}</div>
            <div class="chat-half-text">${content}</div>
            ${tail ? `<div class="chat-half-marks">${tail}</div>` : ''}
        </div>
    `;
}

// ===================== Мелочь =====================

function filtersValue() {
    return {
        owner_id: numberOf(el.owner.value) || null,
        companion_id: numberOf(el.companion.value) || null,
        kind: el.kind.value,
        delivered: el.delivered.value,
    };
}

/** Варианты отбора стороны: «имя (сколько обменов)», по названию. */
function sideEntries(pairs, side) {
    const counts = {};
    const titles = {};
    const keys = {};

    pairs.forEach(one => {
        const id = one[`${side}_id`];

        counts[id] = (counts[id] || 0) + Number(one.exchange_count || 0);
        titles[id] = sideLabel(one, side);
        keys[id] = one[`${side}_unique_id`];
    });

    return Object.keys(counts)
        .map(id => ({
            value: id,
            text: `${titles[id]} (${counts[id]})`,
            // ⚠ Ключ подсказкой: заголовков-близнецов в справочнике хватает
            // (пять записей «Zinaida-Test»), и без него варианты отбора
            // неразличимы — выбрал один, а показался разговор другого.
            title: keys[id],
        }))
        .sort((a, b) => a.text.localeCompare(b.text));
}

/** Подсказка разговора: имена, КЛЮЧИ обеих сторон, канал и счётчики.
 *
 * ⚠⚠ Ключи здесь обязательны. Заголовок записи `companion` не уникален: на
 * установке пять разных записей с заголовком «Zinaida-Test» (их оставляют
 * прогоны тестов), и в списке они выглядят пятью одинаковыми строками.
 * Различает их только `unique_id` — он и есть то, по чему разговор находят в
 * базе.
 */
function pairTip(pair) {
    return [
        `Наша сторона: ${sideLabel(pair, 'owner')} [${pair.owner_unique_id}]`,
        `Собеседник: ${sideLabel(pair, 'companion')} [${pair.companion_unique_id}]`,
        `Канал: ${pair.kind}`,
        `Обменов: ${pair.exchange_count}`
        + `, его реплик: ${pair.question_count}`
        + `, наших ответов: ${pair.answer_count}`,
        `Не доставлено: ${pair.undelivered_count}`,
    ].join('\n');
}

/** Откуда приехала реплика — одним словом, без номера у источника.
 *
 * `source_uid` отвечает на два разных вопроса сразу: «какой дорогой это
 * привезли» (приставка) и «какая там строка» (номер). В ленте нужен только
 * первый: номер `52447706` ничего не говорит глазу, а место занимает. Полный
 * ключ остаётся подсказкой — по нему строку находят у соседа.
 *
 *     panel:52447706                      → panel
 *     favorite_mail:498                   → favorite_mail
 *     mail_in:3                           → mail_in
 *     invite-40-362943-20260924134617     → invite
 *     01M2AKYHGDE84WV430KEM8YTZP          → socket
 *
 * ⚠ Приставки у ключа нет только у одного семейства — ULID кадра вебсокета, и
 * это **не** «неизвестно»: именно так DatingAi и зовёт этот источник
 * (`dating_message.source` = `socket` против `panel`). Отдать его в «прочее»
 * значило бы спрятать самое многочисленное семейство ленты.
 *
 * ⚠ Незнакомая форма показывается КАК ЕСТЬ, а не прячется: ключ приходит от
 * соседнего проекта, у него свои правки, и новое семейство должно быть видно
 * сразу, а не через месяц по жалобе.
 */
function sourceLabel(sourceUid) {
    const value = String(sourceUid || '').trim();

    if (!value) return '';

    if (CHAT_SOURCE_ULID.test(value)) return 'socket';

    return value.split(/[:\-]/)[0] || value;
}

/** Как называть сторону: заголовок, иначе ключ записи.
 *
 * ⚠ Ключ — это `{номер}_{имя}` (`128282_gerard`), а заголовок — имя человека.
 * Пустой заголовок бывает: у трети людей в ленте имя нелатинское или его нет,
 * и тогда ключ — единственное, чем строку можно опознать.
 */
function sideLabel(pair, side) {
    return pair[`${side}_title`] || pair[`${side}_unique_id`]
        || `#${pair[`${side}_id`]}`;
}

function countOf(pairs) {
    return pairs.reduce((sum, one) => sum + Number(one.exchange_count || 0), 0);
}

function numberOf(value) {
    const number = parseInt(value, 10);

    return isNaN(number) ? 0 : number;
}
