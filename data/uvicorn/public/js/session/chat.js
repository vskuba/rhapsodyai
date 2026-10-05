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

import {deleteData, postData} from '../api.js';
import {showNotification} from '/static/js/notification.js';
import {filterLoad, filterSave, htmlEscape, labelClip, numberOf, selectFill,
        selectValueRestore, stampList, sumOf} from './util.js';

// Приставка ключей отбора этой вкладки. Соседняя держит свои под своей
// (`session_agent_`): отборы у вкладок разные, и общий ключ `limit` означал бы
// «поменял предел обменов — поехал предел сессий».
//
// ⚠ Хранилище при этом долгое (`localStorage`, см. `filterSave`): отбор живёт
// столько же, сколько запомненная подвкладка, — иначе страница открывается там,
// где её оставили, но с чужим отбором.
const CHAT_STORE_PREFIX = 'chat_';

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

// Сколько знаков ключа стороны влезает в строку списка рядом с датой, стрелкой
// и счётчиком. Посчитано по ширине поля (`css/session.css`): шире — обрежет сам
// `<select>`, и пропадёт хвост строки, а не ключ.
//
// ⚠ Режется ХВОСТ ключа, то есть имя, а номер остаётся: `283331_dwight_car…`.
// Это та половина, ради которой ключ в списке и стоит, — имя целиком видно в
// шапке открытого разговора и в подсказке.
const CHAT_KEY_MAX = 18;

const el = {};
const state = {
    // Полная выборка разговоров: из неё строятся отборы сторон со счётчиками.
    // Перезаписывать её отфильтрованным результатом нельзя — тот же довод, что
    // на соседней вкладке.
    pairs: [],
    // Выбранный разговор тройкой — её же отправляем за обменами.
    current: null,
    // Показанные обмены как пришли с сервера. Нужны окну подтверждения: оно
    // показывает текст обеих половин, а в разметке он уже экранирован и обрезан
    // стилями — вытаскивать его обратно из DOM значило бы разбирать то, что сами
    // же собрали.
    rows: [],
    // Номер обмена, про который открыто окно. Пока оно закрыто — null.
    removing: null,
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
    el.modal = document.getElementById('chatDeleteModal');
    el.modalPreview = document.getElementById('chatDeletePreview');
    el.modalCancel = document.getElementById('chatDeleteCancel');
    el.modalConfirm = document.getElementById('chatDeleteConfirm');

    try {
        await kindsLoad();
        await pairsLoadAll();
        filtersBind();
        removeBind();
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
        selectValueRestore(el[name], filterLoad(CHAT_STORE_PREFIX + name));
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
    selectValueRestore(el.owner, filterLoad(`${CHAT_STORE_PREFIX}owner_id`));
    // Собеседники сужаются нашей стороной — перезаполняем после восстановления.
    companionFill();
    selectValueRestore(el.companion,
        filterLoad(`${CHAT_STORE_PREFIX}companion_id`));
}

function sidesFill() {
    selectFill(el.owner, [
        {value: '', text: `Все (${sumOf(state.pairs, 'exchange_count')} обменов)`},
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
        {value: '', text: `Все (${sumOf(scoped, 'exchange_count')} обменов)`},
        ...sideEntries(scoped, 'companion'),
    ]);
}

function filtersBind() {
    el.owner.onchange = async () => {
        filterSave(`${CHAT_STORE_PREFIX}owner_id`, el.owner.value);
        companionFill();
        filterSave(`${CHAT_STORE_PREFIX}companion_id`, el.companion.value);
        await pairsLoad();
    };

    el.companion.onchange = async () => {
        filterSave(`${CHAT_STORE_PREFIX}companion_id`, el.companion.value);
        await pairsLoad();
    };

    // Канал и доставка отбирают и список разговоров, и обмены внутри: условие
    // одно и то же, и расходиться им незачем — «разговоров нет» и «в разговоре
    // нет обменов» иначе означали бы разные отборы.
    ['kind', 'delivered'].forEach(name => {
        el[name].onchange = async () => {
            filterSave(CHAT_STORE_PREFIX + name, el[name].value);
            await pairsLoad();
        };
    });

    el.limit.onchange = () => {
        filterSave(`${CHAT_STORE_PREFIX}limit`, el.limit.value);

        if (state.current) exchangesLoad(state.current);
    };

    el.list.onchange = () => {
        const pair = state.shown?.[el.list.selectedIndex];

        if (pair) exchangesLoad(pair);
    };
}

// ===================== Разговоры =====================

/** Список разговоров под текущий отбор.
 *
 * `keep` — тройка разговора, который надо оставить открытым. Не передали —
 * берётся запомненный (`pairRemembered`), то есть тот, который был открыт в
 * прошлый раз. Не нашёлся под текущим отбором — открывается верхний, самый
 * свежий.
 *
 * ## ⚠⚠ Открывается запомненный, а не верхний, и это правка поведения
 *
 * Раньше «верхний» открывался при каждой смене отбора, по доводу «верхний и
 * означает самый свежий под новым условием». Довод верен для списка и неверен
 * для ленты: отбор меняют, чтобы посмотреть **на этот же разговор** другим
 * срезом — сменил доставку на «Доставлен», и вместо своей переписки получаешь
 * чужую, самую свежую на установке. Правило теперь одно на все поводы: открыт
 * тот, на кого смотрели, пока он есть под отбором.
 *
 * ⚠ Разговор, из которого удалили последний обмен, из списка исчезает — тогда
 * `keep` не находится, и открывается верхний. Это честнее, чем держать пустую
 * шапку разговора, которого больше нет. Тем же путём работает «запомненного
 * больше нет под этим отбором».
 */
async function pairsLoad(keep = null) {
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
        // Строка списка отвечает на «кто с кем» — КЛЮЧАМИ обеих сторон, а не
        // именами.
        //
        // ⚠⚠ Имена не уникальны: двух Diana и двух Elena в списке не
        // различить никак, а они разные люди. Ключ несёт номер анкеты, и он
        // единственное, что в строке списка отвечает на «которая из них».
        // Имя при этом не теряется: оно стоит в ключе и целиком — в шапке
        // открытого разговора и в подсказке.
        //
        // ⚠ Длинная строка в `<select>` обрезается справа и БЕЗ многоточия —
        // то, что не влезло, выглядит как конец ключа. Поэтому обе стороны
        // режутся явно (`labelClip`), а целиком ключи есть подсказкой.
        const option = new Option(
            `${stampList(one.last_at)} ${labelClip(one.owner_unique_id, CHAT_KEY_MAX)}`
            + ` → ${labelClip(one.companion_unique_id, CHAT_KEY_MAX)}`
            + ` ${one.kind === 'mail' ? '✉' : '💬'}${one.exchange_count}`
            + `${one.undelivered_count > 0 ? ` ⏳${one.undelivered_count}` : ''}`,
            String(one.companion_id));

        option.title = pairTip(one);
        el.list.add(option);
    });

    if (!pairs.length) {
        state.current = null;
        state.rows = [];
        el.title.textContent = 'Нет разговоров под этот отбор';
        el.stream.innerHTML = '<div class="placeholder">Нет разговоров</div>';

        return;
    }

    const wanted = keep || pairRemembered();
    const kept = wanted ? pairs.findIndex(one => pairSame(one, wanted)) : -1;

    el.list.selectedIndex = kept >= 0 ? kept : 0;
    await exchangesLoad(pairs[el.list.selectedIndex]);
}

/** Один ли это разговор. Тройка целиком: пара без канала — два разговора. */
function pairSame(one, other) {
    return one.owner_id === other.owner_id
        && one.companion_id === other.companion_id
        && one.kind === other.kind;
}

/** Запомнить открытый разговор — чтобы следующий заход начался с него.
 *
 * ## ⚠⚠ Запоминается ТРОЙКА, а не номер варианта в списке
 *
 * В `value` варианта лежит `companion_id` — он не опознаёт разговор: у одной
 * пары чат и почта это два разных разговора, и выбор по одному номеру открывал
 * бы то одну переписку, то другую. Номер варианта (`selectedIndex`) не годится
 * тем же образом, только хуже: список упорядочен по свежести, и к следующему
 * заходу под третьей строкой стоит уже другой разговор.
 *
 * ⚠ JSON, а не своя строка-ключ («12:34:chat»): её пришлось бы разбирать
 * обратно — лишний формат на ровном месте. Тот же довод, по которому список
 * разговоров держится рядом с `<select>`, а не в его `value`.
 *
 * ## ⚠⚠ Зовётся из `exchangesLoad` — там, где разговор ОТКРЫВАЕТСЯ
 *
 * Не из `el.list.onchange`, хотя соблазн был. Разговор открывается не только
 * щелчком: его открывает заход на страницу, смена отбора, возврат после
 * удаления обмена. Пиши память по щелчку — и «запомнено» разошлось бы с тем,
 * что на экране, причём молча. Одна дверь: запомнено ровно то, что показано.
 */
function pairRemember(pair) {
    filterSave(`${CHAT_STORE_PREFIX}talk`, JSON.stringify({
        owner_id: pair.owner_id,
        companion_id: pair.companion_id,
        kind: pair.kind,
    }));
}

/** Запомненный разговор тройкой или `null`.
 *
 * ⚠ Разбор под `try`: значение читается на КАЖДОМ заходе, и порченый ключ (чужая
 * правка в консоли, оборванная запись) ронял бы завод вкладки целиком — страница
 * показывала бы «Ошибка загрузки» до тех пор, пока человек сам не вычистит
 * хранилище. Не разобралось — считаем, что не запомнено.
 *
 * ⚠ Проверять, что такой разговор ещё существует, здесь не надо: искать его
 * всё равно `pairsLoad` — в списке под текущим отбором, а не в базе.
 */
function pairRemembered() {
    try {
        const saved = JSON.parse(filterLoad(`${CHAT_STORE_PREFIX}talk`) || 'null');

        return saved && typeof saved === 'object' ? saved : null;
    } catch {
        return null;
    }
}

// ===================== Лента обменов =====================

async function exchangesLoad(pair) {
    const request = ++chatRequest;

    state.current = pair;
    // Память разговора идёт рядом с `state.current` и по тому же поводу: это
    // «какой разговор открыт», только переживающее перезагрузку. Разойдись они
    // — и запомнилось бы не то, что показано (разбор — у `pairRemember`).
    pairRemember(pair);
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
    state.rows = rows;

    // Ключи сторон — подсказкой на заголовке: в строке они съели бы её целиком
    // (`966e95ea_Zinaida-Test`), а без них два разговора с одинаковыми именами
    // в шапке неразличимы.

    // Сколько убранных ответов в показанном. Считается по ленте, а не берётся у
    // разговора: `deleted_count` относится ко всему разговору, а здесь ответ на
    // «сколько из того, что передо мной», и под `limit`-ом эти числа расходятся.
    //
    // ⚠⚠ Число нужно потому, что пометка «было удалено» тихая: она светло-серая
    // и стоит ровно на месте реплики, и в ленте на пятьдесят обменов её не
    // видно, пока не прокрутишь всё. С отбором «Доставлен» это и есть ответ на
    // «сколько доставленного мы убрали» — вопрос, из-за которого отметку
    // перестали прятать из отбора.
    const removed = rows.filter(one => one.answer_deleted_at).length;

    el.title.title = pairTip(pair);
    el.title.innerHTML =
        `${htmlEscape(sideFull(pair, 'owner'))} ↔ ${htmlEscape(sideFull(pair, 'companion'))}`
        + `<span class="detail-header-note">· ${htmlEscape(pair.kind)},`
        + ` показано ${rows.length} из ${pair.exchange_count} обменов`
        + `${removed ? `, убрано ответов: ${removed}` : ''}</span>`;

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
    //
    // ⚠⚠ Чип удаления стоит здесь же, в хвосте НАШЕЙ строки, и это не вопрос
    // вкуса: убирается наш ответ, а не обмен. Поставь его в шапку строки — и он
    // читался бы как «снести запись», то есть вместе с его репликой, которая
    // настоящая и мешать не может. У обмена без нашего ответа чипа нет вовсе:
    // убирать там нечего.
    const marks = [
        answered ? (delivered
            ? '<span class="chip chip-delivered">✓ доставлено</span>'
            : '<span class="chip chip-undelivered">⏳ не доставлено</span>') : '',
        row.source_uid
            ? `<span class="chip chip-source" title="ключ у источника: ${htmlEscape(row.source_uid)}">`
              + `${htmlEscape(sourceLabel(row.source_uid))}</span>`
            : '',
        answered
            ? `<button type="button" class="chip chip-delete" data-answer-delete="${htmlEscape(row.id)}"`
              + ' title="Убрать наш ответ; реплика собеседника останется">🗑 удалить</button>'
            : '',
    ].filter(Boolean).join('');

    // ⚠ Даты в шапке обмена нет. Она была `COALESCE(question_at, answer_at,
    // created_at)`, то есть всегда повторяла время одной из половин — те стоят
    // строкой ниже, своими столбцами. Строк, где обе половины без времени, не
    // бывает (инструмент не пишет обмен, у которого пусты обе), так что
    // прятать здесь нечего. `created_at` — когда строка легла в базу, а не
    // когда это сказали; у привезённых он на месяц позже разговора, поэтому
    // живёт подсказкой, а не строкой.
    // Шапка строки отвечает на «что это за строка»: её номер и канал. Канал
    // стоит здесь, а не в хвосте с доставкой: тот хвост — про наш ответ
    // (сочинён, доставлен, каким путём приехал, убрать), а канал — свойство
    // обмена целиком, как и номер.
    //
    // ⚠ Канал виден, хотя в открытом разговоре он один и тот же у всех строк:
    // разговор опознаётся тройкой, и чат с почтой одной пары лежат врозь. Чип
    // отвечает на «а это сейчас какая из двух переписок» не глядя в сайдбар.
    return `
        <div class="chat-exchange">
            <div class="chips-container">
                <span class="chip chip-id" title="строка в базе с ${fmtTz(row.created_at)}">#${htmlEscape(row.id)}</span>
                <span class="chip chip-channel chip-channel-${htmlEscape(row.kind)}"
                      title="канал разговора">${row.kind === 'mail' ? '✉' : '💬'} ${htmlEscape(row.kind)}</span>
            </div>
            ${String(row.question || '') === '' ? '' : halfHtml({
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
                // Убранный ответ приходит отдельными полями: в `answer` его
                // нет, иначе он снова считался бы сказанным (чип доставки, чип
                // удаления, счётчик ответов).
                deletedText: row.answer_deleted_text,
                deletedAt: row.answer_deleted_at,
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
                   marks = '', deletedText = '', deletedAt = null}) {
    // ⚠ Пустая НАША половина остаётся прочерком, а его — не рисуется вовсе
    // (решает `exchangeHtml`). Разница в том, что каждая из них значит.
    //
    //     его половина пуста    заговорили мы: инвайт, письмо, инициатива.
    //                           Таких строк две трети, и прочерк в каждой —
    //                           просто столбец пустых клеток.
    //     наша половина пуста   агент СМОЛЧАЛ на сказанное. Это решение, и
    //                           видеть его надо: лента без прочерка выглядит
    //                           так, будто разговор на этом кончился сам.
    //     ответ убран           третий случай, и он НЕ «нет ответа»: ответ был
    //                           и был доставлен, его убрали мы. Пометка своя, а
    //                           текст — в подсказке: правку делает человек и
    //                           имеет право посмотреть, что именно убрал.
    const content = deletedAt
        ? deletedHtml(deletedText, deletedAt, timeBefore)
        : (String(text || '') !== ''
            ? htmlEscape(text)
            : '<span class="chat-half-empty">— нет ответа —</span>');
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

/** Место убранного ответа: пометка в ленте, текст — подсказкой.
 *
 * ⚠⚠ Текст живёт в `title`, а не в ленте. Смысл правки в том, чтобы убранный
 * ответ не мешал читать разговор: выведи его светло-серым прямо в строку — и он
 * продолжит мозолить глаза, то есть делать ровно то, из-за чего его и убрали.
 * Наведение — осознанное действие, им и спрашивают «а что там было».
 *
 * ⚠ В подсказку идёт и время: «убрано вчера» и «убрано минуту назад» — разные
 * ответы на вопрос «это я сейчас нажал или оно давно так?».
 *
 * ⚠⚠ Второй строкой подсказки стоит ДОСТАВКА, и она не украшение. Обмен с
 * убранным ответом остаётся в выдаче отбора «Доставлен» — отметка о доставке
 * это запись о случившемся: собеседник ответ получил, а убрали мы его из
 * памяти агента, а не с его экрана. Чипа «✓ доставлено» у пометки нет
 * (считается по `answer`, а тот пуст), и без этой строки страница не отвечала
 * бы, почему строка в отборе оказалась. Доставки не было — строки нет вовсе:
 * «не доставлено» у убранного читалось бы как упрёк.
 *
 * ⚠ Текст приходит из базы и попадает в атрибут — экранируем тем же
 * `htmlEscape`, что и остальное: кавычка в ответе разорвала бы разметку.
 */
function deletedHtml(text, deletedAt, deliveredAt) {
    const said = String(text || '');
    const hint = [
        `Убрано ${fmtTz(deletedAt)}`,
        deliveredAt ? `Было доставлено ${fmtTz(deliveredAt)}` : '',
        said ? `Текст ответа:\n\n${said}` : '',
    ].filter(Boolean).join('\n');

    return `<span class="chat-half-deleted" title="${htmlEscape(hint)}">`
        + 'было удалено</span>';
}

// ===================== Удаление нашего ответа =====================
//
// ⚠⚠ Убирается НАША ПОЛОВИНА обмена, а не строка и не разговор. Строка здесь —
// обмен: его реплика и наш ответ лежат в колонках одной записи. Ошибочно
// доставленным бывает наш ответ, а его слова настоящие, и сносить запись
// целиком значило бы стирать заодно их. Поэтому чистится `answer` — и обмен
// становится «он написал, мы смолчали», случай, который лента рисует прочерком.
//
// ⚠ Кнопки «очистить переписку» здесь нет и не будет: разговор — это память
// агента, из него собирается лента для промпта (`companion_session_history`), и
// без неё агент заговорит с человеком как с незнакомым. Чип — про обратное:
// ответ, доставленный по ошибке, ту же ленту ПОРТИТ, и дальше каждый ответ
// модели опирается и на него.
//
// ⚠ Окно подтверждения, а не `confirm()` соседней вкладки. `confirm()` умеет
// показать только строку текста — человек подтверждал бы удаление «обмена #512»,
// не видя, что в нём написано. Решение здесь принимается по тексту: в окне обе
// половины, и видно, какая из них уйдёт, а какая останется.

function removeBind() {
    // ⚠ Слушатель на ленте, а не на чипах: лента перерисовывается целиком на
    // каждую загрузку, и обработчики на кнопках пришлось бы развешивать заново
    // после каждого запроса — ровно тот случай, когда одна забытая перерисовка
    // даёт «кнопка не нажимается» без единой ошибки в консоли.
    el.stream.addEventListener('click', event => {
        const chip = event.target.closest('[data-answer-delete]');

        if (chip) removeAsk(Number(chip.dataset.answerDelete));
    });

    el.modalCancel.onclick = removeClose;
    el.modalConfirm.onclick = removeRun;

    // Щелчок по затемнению — отмена; по самому окну — нет. Слушаем `mousedown`:
    // выделение текста обмена мышью кончается отпусканием кнопки за окном, и на
    // `click` такое движение закрывало бы окно посреди чтения.
    el.modal.addEventListener('mousedown', event => {
        if (event.target === el.modal) removeClose();
    });

    // Esc закрывает окно. Обработчик живёт на документе и не снимается:
    // панели обеих вкладок лежат в одном документе, и ловить нечего, пока
    // `state.removing` пуст.
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && state.removing !== null) removeClose();
    });
}

/** Спросить про удаление: показать обмен целиком и ждать решения. */
function removeAsk(id) {
    const row = state.rows.find(one => Number(one.id) === id);

    // Строки нет в показанном — лента успела перезагрузиться под другим
    // отбором. Молча ничего не делаем: спрашивать про исчезнувшее не о чем.
    if (!row) return;

    state.removing = id;
    el.modalPreview.innerHTML = removePreview(row);
    el.modal.hidden = false;
    // Фокус — на отмене. Окно открылось по разрушающему действию, и случайный
    // Enter обязан означать «нет».
    el.modalCancel.focus();
}

/** Обмен в окне: шапка строки и обе половины целиком.
 *
 * ⚠⚠ Половины помечены словами «останется» и «уйдёт». Без пометок окно
 * показывало бы просто две реплики, и вопрос «а его слова тоже пропадут?» —
 * ровно тот, на который окно обязано отвечать до нажатия, — остался бы без
 * ответа.
 *
 * ⚠ Текст НЕ обрезается, в отличие от ленты: письмо в десяток строк тем и
 * опасно, что первая его строка выглядит безобидно. Решают по тексту — значит
 * текст должен быть весь; длинное окно прокручивается.
 */
function removePreview(row) {
    const pair = state.current;
    const delivered = Boolean(row.delivered_at);

    const halves = [
        String(row.question || '') === '' ? '' : removePreviewRow(
            sideLabel(pair, 'companion'), row.question, 'останется'),
        removePreviewRow(sideLabel(pair, 'owner'), row.answer, 'уйдёт'),
    ].filter(Boolean).join('');

    return `
        <div class="modal-preview-head">
            <span class="chip chip-id">#${htmlEscape(row.id)}</span>
            <span class="chip chip-channel chip-channel-${htmlEscape(row.kind)}">${
                row.kind === 'mail' ? '✉' : '💬'} ${htmlEscape(row.kind)}</span>
            ${delivered
                ? '<span class="chip chip-delivered">✓ доставлено</span>'
                : '<span class="chip chip-undelivered">⏳ не доставлено</span>'}
        </div>
        ${halves}
    `;
}

function removePreviewRow(who, text, fate) {
    return `
        <div class="modal-preview-row modal-preview-${fate === 'уйдёт' ? 'goes' : 'stays'}">
            <div class="modal-preview-who" title="${htmlEscape(who)}">${htmlEscape(who)}</div>
            <div class="modal-preview-text">${htmlEscape(text)}</div>
            <div class="modal-preview-fate">${htmlEscape(fate)}</div>
        </div>
    `;
}

async function removeRun() {
    const id = state.removing;

    if (id === null) return;

    // Разговор запоминаем до запроса: `removeClose` чистит только состояние
    // окна, но список после удаления перезагружается, и открытым должен
    // остаться тот же разговор, а не верхний.
    const pair = state.current;

    el.modalConfirm.disabled = true;
    el.modalCancel.disabled = true;

    try {
        await deleteData(`/session/companion/${id}/answer`);

        showNotification('Ответ убран; текст виден подсказкой на пометке',
            'success');
        removeClose();
        // Список целиком, а не вычитание единицы на месте: у разговора четыре
        // счётчика (обмены, его реплики, наши ответы, недоставленные), каждый
        // считается по своему условию, и повторять эти правила в браузере
        // значило бы завести вторую их копию.
        await pairsLoad(pair);
    } catch (e) {
        showNotification(`Ошибка удаления: ${e.message}`, 'error');
    } finally {
        el.modalConfirm.disabled = false;
        el.modalCancel.disabled = false;
    }
}

function removeClose() {
    state.removing = null;
    el.modal.hidden = true;
    el.modalPreview.innerHTML = '';
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
        // ⚠ Строка появляется только когда убирали: нуль в подсказке у каждого
        // разговора — шум, а отметка стоит у единиц.
        Number(pair.deleted_count || 0)
            ? `Убрано ответов: ${pair.deleted_count}`
            : '',
    ].filter(Boolean).join('\n');
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

/** Как называть сторону коротко: заголовок, иначе ключ записи.
 *
 * ⚠ Ключ — это `{номер}_{имя}` (`128282_gerard`), а заголовок — имя человека.
 * Пустой заголовок бывает: у трети людей в ленте имя нелатинское или его нет,
 * и тогда ключ — единственное, чем строку можно опознать.
 */
function sideLabel(pair, side) {
    return pair[`${side}_title`] || pair[`${side}_unique_id`]
        || `#${pair[`${side}_id`]}`;
}

/** Сторона полностью: «Имя (ключ)».
 *
 * ⚠⚠ Номер в скобках обязателен. **Имена не уникальны**: на установке две
 * Diana, две Elena, две Natalia — разные анкеты на сайте, разные люди. По
 * одному имени в шапке нельзя сказать, чья это переписка; номер анкеты
 * (`418024_diana` против `643694_diana`) говорит это однозначно.
 *
 * ⚠ Заголовок, равный ключу, не задваивается: такие записи заводили без
 * имени, и «999029_olga (999029_olga)» ничего не добавляет.
 */
function sideFull(pair, side) {
    const title = pair[`${side}_title`];
    const key = pair[`${side}_unique_id`];

    if (!key) return title || `#${pair[`${side}_id`]}`;

    return title && title !== key ? `${title} (${key})` : key;
}

