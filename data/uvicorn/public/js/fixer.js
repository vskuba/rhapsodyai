// Фиксер — «покажи пальцем и скажи, что не так».
//
// Иконка в правом краю второй строки меню включает режим выбора: под курсором
// подсвечивается элемент страницы, по клику открывается окошко с путём до него и
// полем, куда claim пишется текстом или голосом. Отправка заводит на /admin/task
// задачу с типом «plan» в проекте самой системы — с адресом страницы, путём до
// элемента и его разметкой в описании, чтобы разработчику не пришлось выяснять,
// о каком месте вообще шла речь.
//
// Живёт в общем шаблоне: замечание рождается на той странице, где его увидели, и
// заставлять человека уходить с неё, чтобы завести задачу, — верный способ не
// завести её вовсе.
//
// Стили окошка инжектятся отсюда же (как в lang_switcher.js): подсветка и попап —
// принадлежность этого модуля, а не темы меню, и тащить их в общий CSS незачем.

import {getData, postData} from '/static/js/api.js';
import {showNotification} from '/static/js/notification.js';

// Замечание с экрана — это заявка на изменение в самой системе, поэтому задача
// заводится в проекте системы с типом «bug»: по умолчанию её берёт багфиксер, а
// чекбокс в окошке даёт выбрать, куда она уйдёт — в конвейер багфикса или в план.
// Проект и тип ищем по имени, а не по числовому id: id зависят от установки, а
// имена одинаковы везде, где эта админка развёрнута.
const FIXER_PROJECT_TITLE   = 'RhapsodyAi';
const FIXER_TASK_TYPE_NAME  = 'bug';
const FIXER_PROJECT_LIST_URL = '/project/list';
const FIXER_TYPE_LIST_URL    = '/api/team/types';
const FIXER_TASK_URL         = '/tasks/{project_id}';
const FIXER_VOICE_URL        = '/chat/voice';

// Пометки флажков — те же ключи, что у флажков на `/admin/task` (см.
// `TASK_METADATA_KEY_*` в src/project/task/task_metadata.py). Оба хранятся наизнанку:
// включено — это отсутствие ключа, и снятый флажок отправляется явным `false`. Поэтому
// metadata шлём только если какой-то флажок снят, в обычном случае — не шлём вовсе.
const FIXER_META_KEY_PLAN   = 'to_planning';
const FIXER_META_KEY_BUGFIX = 'to_bugfix';

// Разметка выбранного элемента уходит в описание целиком, но не безразмерно: в
// неё бывает завёрнут весь список строк таблицы, а задача с мегабайтом HTML
// нечитаема. Обрезанное отмечаем прямо в тексте, чтобы обрыв не выглядел багом.
const FIXER_HTML_LIMIT = 4000;

// Совсем короткая запись — это почти всегда промах по кнопке, а не речь: распознавание
// такого куска возвращает мусор, и он молча дописывается в поле.
const FIXER_VOICE_MIN_MS = 1000;

// Заголовок задачи — первая строка замечания. Целиком туда не влезет и не нужно:
// полный текст всё равно уходит в описание.
const FIXER_TITLE_LIMIT = 80;

const FIXER_STYLE_ID = 'fixer-style';

const FIXER_CSS = `
.fixer-on, .fixer-on * { cursor: crosshair !important; }
.fixer-on .fixer-ui, .fixer-on .fixer-ui * { cursor: auto !important; }

.fixer-box {
    position: fixed;
    z-index: 2147483000;
    pointer-events: none;
    border: 2px solid #4f46e5;
    background: rgba(79, 70, 229, 0.10);
    border-radius: 3px;
    transition: all 0.05s linear;
}

.fixer-box-label {
    position: absolute;
    left: 0;
    top: -19px;
    max-width: 520px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 2px 6px;
    font: 600 10px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #fff;
    background: #4f46e5;
    border-radius: 3px 3px 0 0;
}

.fixer-pop {
    position: fixed;
    z-index: 2147483100;
    width: 380px;
    max-width: calc(100vw - 20px);
    padding: 10px;
    background: #fff;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    box-shadow: 0 12px 32px rgba(15, 23, 42, 0.22);
    font-family: inherit;
}

.fixer-pop-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 7px;
}

.fixer-pop-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: #64748b;
}

.fixer-pop-close {
    border: none;
    background: none;
    padding: 0 2px;
    font-size: 15px;
    line-height: 1;
    color: #94a3b8;
    cursor: pointer;
}

.fixer-pop-close:hover { color: #ef4444; }

.fixer-pop-path {
    width: 100%;
    box-sizing: border-box;
    padding: 6px 8px;
    font: 500 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #334155;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
}

.fixer-pop-row {
    display: flex;
    align-items: stretch;
    gap: 6px;
    margin-top: 7px;
}

.fixer-pop-mic, .fixer-pop-send {
    flex-shrink: 0;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    background: #f8fafc;
    cursor: pointer;
    font-size: 13px;
    color: #334155;
    transition: background .12s, border-color .12s;
}

.fixer-pop-mic { width: 34px; }
.fixer-pop-mic:hover, .fixer-pop-send:hover { background: #eef2f7; border-color: #cbd5e1; }

/* Запись идёт — кнопка красная и пульсирует: без этого не отличить «пишу» от
   «не нажалось», а браузер спрашивает разрешение только в первый раз. */
.fixer-pop-mic.recording {
    background: #fee2e2;
    border-color: #fca5a5;
    animation: fixer-pulse 1s ease-in-out infinite;
}

@keyframes fixer-pulse { 50% { opacity: .55; } }

.fixer-pop-text {
    flex: 1;
    min-width: 0;
    height: 52px;
    resize: vertical;
    padding: 6px 8px;
    font-size: 12px;
    color: #1e293b;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
}

.fixer-pop-send {
    padding: 0 12px;
    font-weight: 600;
    color: #fff;
    background: #4f46e5;
    border-color: #4338ca;
}

.fixer-pop-send:hover { background: #4338ca; }
.fixer-pop-send:disabled { opacity: .6; cursor: default; }

.fixer-pop-flag {
    display: flex;
    align-items: center;
    gap: 5px;
    margin-top: 7px;
    font-size: 11px;
    color: #475569;
    cursor: pointer;
    user-select: none;
}

.fixer-pop-flag input { margin: 0; cursor: pointer; }
`;

let _mode   = false;   // режим выбора включён
let _hover  = null;    // элемент под курсором
let _picked = null;    // выбранный элемент: пока он есть, подсветка заморожена
let _box    = null;
let _pop    = null;
let _btn    = null;

document.addEventListener('DOMContentLoaded', () => {
    _btn = document.getElementById('fixerBtn');
    if (!_btn) return;
    _btn.addEventListener('click', (e) => {
        e.preventDefault();
        _mode ? _modeOff() : _modeOn();
    });
});

function _styleInject() {
    if (document.getElementById(FIXER_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = FIXER_STYLE_ID;
    style.textContent = FIXER_CSS;
    document.head.appendChild(style);
}

function _modeOn() {
    _styleInject();
    _mode = true;
    _btn?.classList.add('active');
    document.body.classList.add('fixer-on');
    // Слушаем в фазе перехвата: страницы вешают свои обработчики на клик по строкам
    // и карточкам, и без перехвата выбор элемента заодно открывал бы задачу, менял
    // вкладку или отправлял форму.
    document.addEventListener('mousemove', _onMove, true);
    document.addEventListener('click', _onClick, true);
    document.addEventListener('contextmenu', _onContext, true);
    document.addEventListener('keydown', _onKey, true);
    window.addEventListener('scroll', _boxSync, true);
}

function _modeOff() {
    _mode = false;
    _picked = null;
    _hover = null;
    _btn?.classList.remove('active');
    document.body.classList.remove('fixer-on');
    document.removeEventListener('mousemove', _onMove, true);
    document.removeEventListener('click', _onClick, true);
    document.removeEventListener('contextmenu', _onContext, true);
    document.removeEventListener('keydown', _onKey, true);
    window.removeEventListener('scroll', _boxSync, true);
    _voice.cancel();
    _box?.remove();
    _box = null;
    _pop?.remove();
    _pop = null;
}

function _onMove(e) {
    if (_picked) return;                     // окошко открыто — подсветку не двигаем
    const el = e.target;
    if (!el || el.nodeType !== 1 || el.closest('.fixer-ui')) return;
    _hover = el;
    _boxSync();
}

function _onClick(e) {
    // Клик внутри собственного окошка — обычный клик по кнопке, не выбор элемента.
    if (e.target?.closest?.('.fixer-ui')) return;
    e.preventDefault();
    e.stopPropagation();
    const el = e.target;
    if (!el || el.nodeType !== 1) return;
    _picked = el;
    _hover = el;
    _boxSync();
    _popupOpen(el);
}

function _onContext(e) {
    // Правая кнопка — выход из режима. Внутри собственного окошка не перехватываем:
    // там правая кнопка нужна для обычного контекстного меню (вставить в поле ввода).
    if (e.target?.closest?.('.fixer-ui')) return;
    e.preventDefault();
    e.stopPropagation();
    _modeOff();
}

function _onKey(e) {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    _modeOff();
}

function _boxSync() {
    const el = _picked || _hover;
    if (!el || !el.isConnected) return;

    if (!_box) {
        _box = document.createElement('div');
        _box.className = 'fixer-box fixer-ui';
        _box.innerHTML = '<span class="fixer-box-label"></span>';
        document.body.appendChild(_box);
    }

    const rect = el.getBoundingClientRect();
    _box.style.left   = `${rect.left}px`;
    _box.style.top    = `${rect.top}px`;
    _box.style.width  = `${rect.width}px`;
    _box.style.height = `${rect.height}px`;
    _box.querySelector('.fixer-box-label').textContent = _pathBuild(el);
}

function _pathBuild(el) {
    const parts = [];
    let node = el;

    while (node && node.nodeType === 1) {
        if (node === document.body) { parts.unshift('body'); break; }

        // Дошли до элемента с id — выше не поднимаемся: id уникален, и всё, что левее,
        // только удлиняет путь, ничего к нему не добавляя.
        if (node.id) { parts.unshift(`#${CSS.escape(node.id)}`); break; }

        let part = node.tagName.toLowerCase();
        const classes = Array.from(node.classList).filter(c => !c.startsWith('fixer-')).slice(0, 2);
        if (classes.length) part += `.${classes.map(c => CSS.escape(c)).join('.')}`;

        const parent = node.parentElement;
        if (parent) {
            // Порядковый номер дописываем только когда соседей того же тега больше
            // одного: у единственного ребёнка `:nth-of-type(1)` — шум, а в таблицах
            // без номера путь указывает сразу на все строки.
            const same = Array.from(parent.children).filter(c => c.tagName === node.tagName);
            if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
        }

        parts.unshift(part);
        node = parent;
    }

    return parts.join(' > ');
}

function _popupOpen(el) {
    _pop?.remove();

    _pop = document.createElement('div');
    _pop.className = 'fixer-pop fixer-ui';
    _pop.innerHTML = `
        <div class="fixer-pop-head">
            <span class="fixer-pop-title">Фиксер</span>
            <button type="button" class="fixer-pop-close" title="Закрыть (Esc или правая кнопка — выйти из режима)">✕</button>
        </div>
        <input type="text" class="fixer-pop-path" spellcheck="false">
        <div class="fixer-pop-row">
            <button type="button" class="fixer-pop-mic" title="Продиктовать">🎤</button>
            <textarea class="fixer-pop-text" placeholder="Что поправить?"></textarea>
            <button type="button" class="fixer-pop-send">Отправить</button>
        </div>
        <label class="fixer-pop-flag" title="Отдать задачу менеджеру за планом. По умолчанию не стоит — задача уходит багфиксеру">
            <input type="checkbox" class="fixer-pop-plan">в планирование
        </label>
        <label class="fixer-pop-flag" title="Отдать задачу багфиксеру. По умолчанию стоит — снять, и задача заведётся, но будет ждать">
            <input type="checkbox" class="fixer-pop-bugfix" checked>bug fix
        </label>`;
    document.body.appendChild(_pop);

    _pop.querySelector('.fixer-pop-path').value = _pathBuild(el);
    _pop.querySelector('.fixer-pop-close').addEventListener('click', () => {
        // Закрыли окошко, но из режима не вышли: замечаний на странице обычно
        // несколько, и включать фиксер заново под каждое — лишний шаг.
        _pop?.remove();
        _pop = null;
        _picked = null;
        _voice.cancel();
    });
    _pop.querySelector('.fixer-pop-mic').addEventListener('click', (e) => _voice.toggle(e.currentTarget));
    _pop.querySelector('.fixer-pop-send').addEventListener('click', (e) => _send(e.currentTarget));

    _popupPlace(el);
    _pop.querySelector('.fixer-pop-text').focus();
}

function _popupPlace(el) {
    const rect = el.getBoundingClientRect();
    const size = _pop.getBoundingClientRect();
    const gap  = 8;

    // Под элементом, а если внизу не помещается — над ним. Оба края прижимаем к экрану:
    // выбранный элемент бывает и у самой кромки, и окошко уехало бы за неё.
    let top = rect.bottom + gap;
    if (top + size.height > window.innerHeight - gap) top = Math.max(gap, rect.top - size.height - gap);

    const left = Math.min(Math.max(gap, rect.left), window.innerWidth - size.width - gap);

    _pop.style.top  = `${top}px`;
    _pop.style.left = `${left}px`;
}

async function _send(btn) {
    const path = _pop.querySelector('.fixer-pop-path').value.trim();
    const text = _pop.querySelector('.fixer-pop-text').value.trim();
    const plan   = _pop.querySelector('.fixer-pop-plan').checked;
    const bugfix = _pop.querySelector('.fixer-pop-bugfix').checked;
    if (!text) {
        showNotification('Опишите, что поправить', 'warning');
        return;
    }

    // Разметку снимаем до запроса: пока идёт обращение к справочникам, страница
    // живёт своей жизнью и выбранный элемент успевает перерисоваться.
    const html = _picked ? _htmlSnippet(_picked) : '';

    btn.disabled = true;
    try {
        const target = await _targetResolve();
        const title = text.length > FIXER_TITLE_LIMIT
            ? `${text.slice(0, FIXER_TITLE_LIMIT - 1)}…`
            : text;
        // Адрес страницы, путь и разметка — в описании, а не в мешке metadata: читать
        // их будет человек и агент-разработчик, а оба читают описание. Адрес целиком
        // (с хостом и хэшем) — по нему сразу видно роутинг, вплоть до вкладки.
        const parts = [text, '', `Страница: ${location.href}`, `Элемент: ${path}`];
        if (html) parts.push('', 'HTML элемента:', '```html', html, '```');
        const body = {
            title,
            description: parts.join('\n'),
            task_type_id: target.task_type_id,
        };
        // Флажок снят — пишем пометку сразу при заведении, а не отдельным запросом:
        // между созданием задачи и вторым вызовом успевает пройти тик оркестратора, и
        // менеджер забрал бы её как раз в тот промежуток.
        const meta = {};
        if (!plan) meta[FIXER_META_KEY_PLAN] = false;
        if (!bugfix) meta[FIXER_META_KEY_BUGFIX] = false;
        if (Object.keys(meta).length) body.metadata = meta;
        await postData(FIXER_TASK_URL.replace('{project_id}', target.project_id), body);
        // Тип всегда «bug», но куда её возьмут решает флажок: оба сняты — ждёт,
        // снят planning — багфиксер, снят bugfix — планирование.
        const suffix = plan && bugfix ? ''
            : (!plan && bugfix) ? ' (багфиксер)'
            : (plan && !bugfix) ? ' (без багфикса)'
            : ' (ждёт)';
        showNotification(
            `Задача создана — проект «${FIXER_PROJECT_TITLE}», тип «Багфиксер»${suffix}`,
            'success');
        _modeOff();
    } catch (err) {
        showNotification(`Не удалось создать задачу: ${err.message}`, 'error');
        btn.disabled = false;
    }
}

// Справочники читаем один раз на страницу: проекты и типы задач за время правки
// вёрстки не меняются, а два лишних запроса на каждое замечание — заметная пауза
// между «Отправить» и подтверждением.
let _target = null;

async function _targetResolve() {
    if (_target) return _target;

    const [projects, types] = await Promise.all([
        getData(FIXER_PROJECT_LIST_URL),
        getData(FIXER_TYPE_LIST_URL),
    ]);

    const wanted = FIXER_PROJECT_TITLE.toLowerCase();
    const project = (projects?.result || []).find(p => String(p.title || '').trim().toLowerCase() === wanted);
    if (!project) throw new Error(`проект «${FIXER_PROJECT_TITLE}» не найден`);

    // Список типов эндпоинт отдаёт голым массивом, а не в конверте result.
    const type = (Array.isArray(types) ? types : types?.result || []).find(t => t.name === FIXER_TASK_TYPE_NAME);
    if (!type) throw new Error(`тип задачи «${FIXER_TASK_TYPE_NAME}» не найден`);

    _target = {project_id: project.id, task_type_id: type.id};
    return _target;
}

function _htmlSnippet(el) {
    // Работаем с копией: из разметки надо убрать собственные рамку и окошко — они
    // лежат в body и при выборе крупного контейнера попадают в отчёт как часть
    // страницы, сбивая с толку того, кто будет чинить.
    const clone = el.cloneNode(true);
    clone.querySelectorAll?.('.fixer-ui').forEach(node => node.remove());

    const html = clone.outerHTML || '';
    return html.length > FIXER_HTML_LIMIT
        ? `${html.slice(0, FIXER_HTML_LIMIT)}\n… обрезано, всего ${html.length} символов`
        : html;
}

// ── Диктовка ──
// Тот же путь, что у микрофонов на странице задач: запись MediaRecorder -> /chat/voice
// -> распознанный текст дописывается в поле. Дописывается, а не заменяет: человек
// успевает набрать начало руками и договорить остальное.
const _voice = (() => {
    let _mr = null, _chunks = [], _stream = null, _startedAt = 0, _btnEl = null;

    async function _start(btnEl) {
        if (!_stream) _stream = await navigator.mediaDevices.getUserMedia({audio: true});
        _btnEl = btnEl;
        _mr = new MediaRecorder(_stream);
        _chunks = [];
        _mr.ondataavailable = (e) => _chunks.push(e.data);
        _mr.onstop = _onStop;
        _mr.start();
        _startedAt = performance.now();
        btnEl.classList.add('recording');
    }

    async function _onStop() {
        const blob = new Blob(_chunks, {type: 'audio/wav'});
        const short = performance.now() - _startedAt < FIXER_VOICE_MIN_MS;
        _chunks = [];
        _btnEl?.classList.remove('recording');
        if (!blob.size || short || !_pop) return;

        const field = _pop.querySelector('.fixer-pop-text');
        if (_btnEl) _btnEl.textContent = '⏳';
        try {
            const form = new FormData();
            form.append('file', blob, 'voice.wav');
            const data = await postData(FIXER_VOICE_URL, form);
            if (data.result) field.value = (field.value ? `${field.value}\n` : '') + data.result;
        } catch (err) {
            showNotification(`Не удалось распознать: ${err.message}`, 'error');
        } finally {
            if (_btnEl) _btnEl.textContent = '🎤';
        }
    }

    return {
        toggle(btnEl) {
            if (!navigator.mediaDevices?.getUserMedia) {
                showNotification('Микрофон недоступен', 'warning');
                return;
            }
            if (_mr?.state === 'recording') _mr.stop();
            else _start(btnEl).catch(() => showNotification('Нет доступа к микрофону', 'error'));
        },
        // Окошко закрыли на середине записи — дорожку останавливаем, распознавать
        // нечего и некуда вставлять.
        cancel() {
            if (_mr?.state === 'recording') {
                _mr.onstop = null;
                _mr.stop();
            }
            _mr = null;
            _chunks = [];
            _btnEl?.classList.remove('recording');
            _btnEl = null;
        },
    };
})();
