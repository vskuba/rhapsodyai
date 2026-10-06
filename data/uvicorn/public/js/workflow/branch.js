/**
 * Вкладка «Branch» страницы Workflow: ветки разговора и темы внутри них.
 *
 * Ветка — род разговора со своим контрактом и необязательным подпотоком. Тема —
 * запись внутри ветки: метки и три текста (разрешено / желательно / запрещено).
 *
 * ## Устройство страницы
 *
 * Слева — **дерево**: ветки, под каждой её темы локтями. Справа — настройки
 * **ровно того, что выбрано**: ветка или тема, не оба сразу.
 *
 * ⚠ Прежде темы стояли списком внутри карточки ветки, и выходило двойное
 * показывание: та же тема и в списке, и в форме правки под ним. Карточка росла
 * вниз, а выбранного места в ней было не найти.
 *
 * ⚠ Ветки принадлежат **ноде**, а не отдельному workflow: их читает шаг `branch`
 * любого workflow этой ноды. Поэтому список берётся по ноде, выбранной в левой
 * карусели страницы.
 *
 * ⚠⚠ Правил выбора темы здесь нет и быть не должно: их считает движок
 * (`src/ai/ai_workflow_branch.py`). Своя копия арифметики на странице разошлась
 * бы с ним на первой же правке.
 *
 * Устройство слоя — `.claude/docs/workflow_branch.md`.
 */

const PAGE_SIZE = 20;

const branchState = {
    nodeId: null,
    branches: [],
    topicsByBranch: {},
    page: 0,
    // Что открыто справа: `{kind: 'branch'|'topic'|null, id}`. Одно на двоих —
    // выбрано всегда что-то одно, и второго показывать нечего.
    picked: {kind: null, id: null},
    workflows: [],
};

async function branchApi(url, options) {
    const response = await fetch(url, options);
    let body = null;
    try {
        body = await response.json();
    } catch (e) {
        body = null;
    }
    if (!response.ok) {
        throw new Error((body && (body.detail || body.message)) || response.statusText);
    }
    return body;
}

function esc(text) {
    return String(text == null ? '' : text).replace(/[&<>"]/g, c => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]
    ));
}

function tagList(raw) {
    return String(raw || '').split(',').map(t => t.trim()).filter(Boolean);
}

/**
 * «2 темы», а не «2 тем».
 *
 * ⚠ Число рядом со словом читают глазами, и неверная форма видна сразу — а в
 * коде её не видно вовсе.
 */
function plural(count, one, few, many) {
    const tens = count % 100;
    if (tens >= 11 && tens <= 14) return `${count} ${many}`;
    const last = count % 10;
    if (last === 1) return `${count} ${one}`;
    if (last >= 2 && last <= 4) return `${count} ${few}`;
    return `${count} ${many}`;
}

function topicsOf(branchId) {
    return branchState.topicsByBranch[String(branchId)] || [];
}

function branchCurrent() {
    const id = branchState.picked.kind === 'branch' ? branchState.picked.id
        : (topicCurrent() || {}).branch_id;
    return branchState.branches.find(b => String(b.id) === String(id)) || null;
}

function topicCurrent() {
    if (branchState.picked.kind !== 'topic') return null;
    for (const rows of Object.values(branchState.topicsByBranch)) {
        const found = rows.find(t => String(t.id) === String(branchState.picked.id));
        if (found) return found;
    }
    return null;
}

/**
 * Открыть вкладку: загрузить ветки выбранной ноды и нарисовать дерево.
 *
 * @param {object|null} node нода из карусели страницы; без неё рисуется подсказка.
 */
export async function openWorkflowBranch(node) {
    const host = document.getElementById('workflowBranch');
    host.style.display = 'block';

    if (!node || !node.id) {
        host.innerHTML = '<div class="branch-empty">Выберите ноду слева: '
            + 'ветки принадлежат ноде, а не отдельному workflow</div>';
        return;
    }

    if (branchState.nodeId !== node.id) {
        branchState.nodeId = node.id;
        branchState.picked = {kind: null, id: null};
        branchState.page = 0;
    }

    host.innerHTML = `
      <div class="branch-body">
        <div class="branch-sidebar">
          <div class="branch-sidebar-head">
            <span class="branch-node-name">${esc(node.name)}</span>
            <button type="button" class="btn-branch btn-branch-primary" id="branchNew">+ Ветка</button>
          </div>
          <div class="branch-list" id="branchList"></div>
          <div class="branch-pager">
            <button type="button" class="btn-branch" id="branchPagePrev">Назад</button>
            <span id="branchPageLabel">0</span>
            <button type="button" class="btn-branch" id="branchPageNext">Вперёд</button>
          </div>
        </div>
        <div class="branch-detail" id="branchDetail">
          <div class="branch-empty">Выберите ветку или тему слева</div>
        </div>
      </div>`;

    document.getElementById('branchNew').onclick = branchNew;
    document.getElementById('branchPagePrev').onclick = () => {
        if (branchState.page > 0) {
            branchState.page -= 1;
            treeRender();
        }
    };
    document.getElementById('branchPageNext').onclick = () => {
        if ((branchState.page + 1) * PAGE_SIZE < branchState.branches.length) {
            branchState.page += 1;
            treeRender();
        }
    };

    await workflowsLoad();
    await treeLoad();
    detailRender();
}

/**
 * Подпотоки ноды — кандидаты в «свою дорогу» ветки.
 *
 * ⚠ Только `subflow = 1`. Обычный workflow дорогой ветки быть не может: его
 * зовут запросом к агенту, у него свой вход и свой ответ наружу, — а шаг
 * `branch` вызывает ребёнка той же подпрограммой, что `workflow_invoke`, и ждёт
 * от него возврата родителю. Полный список предлагал бы выбрать то, что сломает
 * прогон, и узналось бы это уже в проде.
 */
async function workflowsLoad() {
    try {
        const rows = (await branchApi(`/workflow/${branchState.nodeId}/list`)).result || [];
        branchState.workflows = rows.filter(w => Number(w.subflow) === 1);
    } catch (e) {
        branchState.workflows = [];
    }
}

/**
 * Ветки и все их темы — двумя запросами на всё дерево.
 *
 * ⚠ Темы берутся одной ручкой по ноде, а не по ветке в цикле: дерево показывает
 * их сразу все, и запрос на каждую ветку означал бы десяток походов на отрисовку.
 */
async function treeLoad() {
    branchState.branches = (await branchApi(
        `/workflow_branch/list?node_id=${branchState.nodeId}`)).result || [];

    const topics = (await branchApi(
        `/workflow_branch/topic/list?node_id=${branchState.nodeId}`)).result || [];

    branchState.topicsByBranch = {};
    topics.forEach(topic => {
        const key = String(topic.branch_id);
        (branchState.topicsByBranch[key] = branchState.topicsByBranch[key] || []).push(topic);
    });

    if (branchState.page * PAGE_SIZE >= branchState.branches.length) branchState.page = 0;
    treeRender();
}

function treeRender() {
    const list = document.getElementById('branchList');
    if (!list) return;

    if (!branchState.branches.length) {
        list.innerHTML = '<div class="branch-empty">Веток нет</div>';
        document.getElementById('branchPageLabel').textContent = '0';
        return;
    }

    const activeBranchId = String((branchCurrent() || {}).id || '');
    const from = branchState.page * PAGE_SIZE;

    list.innerHTML = branchState.branches.slice(from, from + PAGE_SIZE).map(branch => {
        const topics = topicsOf(branch.id);
        const isActiveBranch = branchState.picked.kind === 'branch'
            && String(branchState.picked.id) === String(branch.id);
        // «+ Тема» показываем только у ветки, с которой сейчас работают: у
        // каждой она была бы шумом в дереве
        const showAdd = String(branch.id) === activeBranchId;

        const children = topics.map((topic, index) => {
            const last = index === topics.length - 1 && !showAdd;
            const isActiveTopic = branchState.picked.kind === 'topic'
                && String(branchState.picked.id) === String(topic.id);
            return `
              <div class="tree-child ${last ? 'is-last' : ''} ${isActiveTopic ? 'is-active' : ''}"
                   data-topic="${topic.id}">
                <span class="branch-dot ${topic.is_enabled ? 'is-on' : ''}"></span>
                <span class="tree-child-main">
                  <span class="tree-child-title">${esc(topic.title)}</span><br>
                  <span class="branch-row-name">${esc(topic.name)}</span>
                </span>
                <span class="topic-count">${plural(
                    tagList(topic.tags).length, 'метка', 'метки', 'меток')}</span>
              </div>`;
        }).join('');

        const addRow = showAdd ? `
          <div class="tree-child is-last tree-add" data-add="${branch.id}">
            <span class="tree-add-text">+ Тема</span>
          </div>` : '';

        return `
          <div class="tree-branch">
            <div class="branch-row ${isActiveBranch ? 'is-active' : ''}" data-branch="${branch.id}">
              <span class="branch-dot ${branch.is_enabled ? 'is-on' : ''}"></span>
              <span class="branch-row-main">
                <span class="branch-row-title">${esc(branch.title)}</span><br>
                <span class="branch-row-name">${esc(branch.name)}</span>
              </span>
              <span class="branch-row-count">${plural(
                  topics.length, 'тема', 'темы', 'тем')}</span>
            </div>
            ${children}${addRow}
          </div>`;
    }).join('');

    list.querySelectorAll('[data-branch]').forEach(row => {
        row.onclick = () => pick('branch', Number(row.dataset.branch));
    });
    list.querySelectorAll('[data-topic]').forEach(row => {
        row.onclick = () => pick('topic', Number(row.dataset.topic));
    });
    list.querySelectorAll('[data-add]').forEach(row => {
        row.onclick = () => {
            branchState.picked = {kind: 'topic', id: null};
            treeRender();
            detailRender();
        };
    });

    const pages = Math.ceil(branchState.branches.length / PAGE_SIZE);
    document.getElementById('branchPageLabel').textContent = `${branchState.page + 1} / ${pages}`;
}

function pick(kind, id) {
    branchState.picked = {kind, id};
    treeRender();
    detailRender();
}

// ── Правая колонка: ровно то, что выбрано ───────────────────────────────────

function detailRender() {
    const detail = document.getElementById('branchDetail');
    if (!detail) return;

    if (branchState.picked.kind === 'topic') {
        topicCardRender(detail);
        return;
    }
    if (branchState.picked.kind === 'branch') {
        branchCardRender(detail);
        return;
    }
    detail.innerHTML = '<div class="branch-empty">Выберите ветку или тему слева</div>';
}

function branchCardRender(detail) {
    const branch = branchCurrent();
    if (!branch) {
        detail.innerHTML = '<div class="branch-empty">Выберите ветку или тему слева</div>';
        return;
    }

    const subflowOptions = ['<option value="">— нет, ветка сужает общий ответ —</option>']
        .concat(branchState.workflows.map(w =>
            `<option value="${w.id}" ${String(w.id) === String(branch.workflow_id) ? 'selected' : ''}>`
            + `${esc(w.title || w.name)}</option>`))
        .join('');

    detail.innerHTML = `
      <div class="branch-card">
        <div class="branch-card-head">Ветка</div>
        <div class="branch-form-row">
          <div class="branch-field"><label>Название</label>
            <input class="branch-control" id="b_title" value="${esc(branch.title)}"></div>
          <div class="branch-field"><label>Код</label>
            <input class="branch-control" id="b_name" value="${esc(branch.name)}"></div>
        </div>
        <div class="branch-form-row">
          <div class="branch-field">
            <label>Минимум совпавших меток</label>
            <input class="branch-control" id="b_match_min" type="number" min="1" max="10"
                   value="${branch.match_min}">
            <div class="branch-hint">Тема ниже этого порога в выборе не участвует.
                 Порог живёт у ветки: на шаге он глушил бы и чужие темы.</div>
          </div>
          <div class="branch-field"><label>Включена</label>
            <select class="branch-control" id="b_is_enabled">
              <option value="1" ${branch.is_enabled ? 'selected' : ''}>да</option>
              <option value="0" ${branch.is_enabled ? '' : 'selected'}>нет</option>
            </select></div>
        </div>
        <div class="branch-field">
          <label>Своя дорога (subflow)</label>
          <div style="display:flex; gap:8px">
            <select class="branch-control" id="b_workflow_id" style="flex:1">${subflowOptions}</select>
            <button type="button" class="btn-branch" id="b_subflow_new"
                    ${branch.workflow_id ? 'disabled' : ''}>Создать subflow</button>
          </div>
          <div class="branch-hint">Пусто — ветка не заменяет генерацию ответа, а сужает её:
               критерии темы приезжают метками в общий промпт.</div>
        </div>
        <div class="branch-actions">
          <button type="button" class="btn-branch btn-branch-primary" id="b_save">Сохранить</button>
          <button type="button" class="btn-branch" id="b_topic_new">+ Тема</button>
          <button type="button" class="btn-branch btn-branch-danger" id="b_delete">Удалить ветку</button>
        </div>
      </div>`;

    document.getElementById('b_save').onclick = branchSave;
    document.getElementById('b_delete').onclick = branchDelete;
    document.getElementById('b_topic_new').onclick = () => pick('topic', null);
    const subflowButton = document.getElementById('b_subflow_new');
    if (subflowButton) subflowButton.onclick = branchSubflowCreate;
}

function topicCardRender(detail) {
    const branch = branchCurrent();
    const topic = topicCurrent() || {
        name: '', title: '', tags: '', acceptance: '', direction: '', restriction: '',
        is_enabled: 1,
    };
    const isNew = !topicCurrent();

    detail.innerHTML = `
      <div class="branch-card">
        <div class="branch-card-head">
          <span class="branch-crumb">${esc((branch || {}).title || '')}</span>
          ${isNew ? 'новая тема' : 'тема'}
        </div>
        <div class="branch-form-row">
          <div class="branch-field"><label>Название</label>
            <input class="branch-control" id="t_title" value="${esc(topic.title)}"></div>
          <div class="branch-field"><label>Код</label>
            <input class="branch-control" id="t_name" value="${esc(topic.name)}"></div>
        </div>
        <div class="branch-field">
          <label>Метки</label>
          <input class="branch-control" id="t_tags" value="${esc(topic.tags)}">
          <div class="branch-hint">Через запятую, каждая из двух слов и больше:
               «обмен письмами, пришли письмо». Односложные не различают близкие темы.</div>
        </div>
        <div class="branch-field">
          <label>Разрешено — что можно и как отвечать</label>
          <textarea class="branch-control" id="t_acceptance">${esc(topic.acceptance)}</textarea>
        </div>
        <div class="branch-field">
          <label>Желательно — куда вести разговор</label>
          <textarea class="branch-control" id="t_direction">${esc(topic.direction)}</textarea>
          <div class="branch-hint">То, ради чего слой и заведён: не реакция, а направление.</div>
        </div>
        <div class="branch-field">
          <label>Запрещено — о чём нельзя</label>
          <textarea class="branch-control" id="t_restriction">${esc(topic.restriction)}</textarea>
          <div class="branch-hint">Уезжает и в генерацию ответа, и к судье.</div>
        </div>
        <div class="branch-field">
          <label>Включена</label>
          <select class="branch-control" id="t_is_enabled">
            <option value="1" ${topic.is_enabled ? 'selected' : ''}>да</option>
            <option value="0" ${topic.is_enabled ? '' : 'selected'}>нет</option>
          </select>
        </div>
        <div class="branch-actions">
          <button type="button" class="btn-branch btn-branch-primary" id="t_save">Сохранить тему</button>
          ${isNew ? '' : '<button type="button" class="btn-branch btn-branch-danger" id="t_delete">Удалить тему</button>'}
        </div>
      </div>`;

    document.getElementById('t_save').onclick = () => topicSave(isNew ? null : topic.id);
    const removeButton = document.getElementById('t_delete');
    if (removeButton) removeButton.onclick = () => topicDelete(topic.id);
}

// ── Правки ──────────────────────────────────────────────────────────────────

async function branchSave() {
    const branch = branchCurrent();
    try {
        await branchApi(`/workflow_branch/${branch.id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title: document.getElementById('b_title').value.trim(),
                name: document.getElementById('b_name').value.trim(),
                match_min: Number(document.getElementById('b_match_min').value) || 1,
                is_enabled: Number(document.getElementById('b_is_enabled').value),
                workflow_id: document.getElementById('b_workflow_id').value || null,
            }),
        });
        await treeLoad();
        detailRender();
    } catch (e) {
        alert(e.message);
    }
}

async function branchDelete() {
    const branch = branchCurrent();
    // ⚠ Удаление необратимо и уносит темы каскадом — спрашиваем всегда
    if (!confirm(`Удалить ветку «${branch.title}» вместе с её темами?`)) return;
    await branchApi(`/workflow_branch/${branch.id}`, {method: 'DELETE'});
    branchState.picked = {kind: null, id: null};
    await treeLoad();
    detailRender();
}

async function branchSubflowCreate() {
    const branch = branchCurrent();
    try {
        const created = await branchApi(`/workflow_branch/${branch.id}/subflow`, {method: 'POST'});
        await workflowsLoad();
        await treeLoad();
        detailRender();
        alert(`Subflow заведён (id ${created.result.workflow_id}). `
              + `Его шаги правятся на вкладке «Шаги».`);
    } catch (e) {
        alert(e.message);
    }
}

function topicBody() {
    return {
        name: document.getElementById('t_name').value.trim(),
        title: document.getElementById('t_title').value.trim(),
        tags: document.getElementById('t_tags').value.trim(),
        acceptance: document.getElementById('t_acceptance').value,
        direction: document.getElementById('t_direction').value,
        restriction: document.getElementById('t_restriction').value,
        is_enabled: Number(document.getElementById('t_is_enabled').value),
    };
}

async function topicSave(topicId) {
    const headers = {'Content-Type': 'application/json'};
    const body = JSON.stringify(topicBody());
    const branch = branchCurrent();
    try {
        if (topicId) {
            await branchApi(`/workflow_branch/topic/${topicId}`, {method: 'PUT', headers, body});
            await treeLoad();
        } else {
            const created = await branchApi(`/workflow_branch/${branch.id}/topic`,
                                            {method: 'POST', headers, body});
            await treeLoad();
            branchState.picked = {kind: 'topic', id: created.result.id};
            treeRender();
        }
        detailRender();
    } catch (e) {
        alert(e.message);
    }
}

async function topicDelete(topicId) {
    if (!confirm('Удалить тему?')) return;
    const branch = branchCurrent();
    await branchApi(`/workflow_branch/topic/${topicId}`, {method: 'DELETE'});
    // После удаления темы показываем её ветку: пустая правая колонка выглядела
    // бы так, будто выбор сбросился сам
    branchState.picked = branch ? {kind: 'branch', id: branch.id} : {kind: null, id: null};
    await treeLoad();
    detailRender();
}

async function branchNew() {
    const title = prompt('Название ветки (например «Договориться»)');
    if (!title) return;
    const name = prompt('Код ветки латиницей (например deal)');
    if (!name) return;
    try {
        const created = await branchApi('/workflow_branch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                node_id: branchState.nodeId, name: name.trim(), title: title.trim(),
            }),
        });
        await treeLoad();
        pick('branch', created.result.id);
    } catch (e) {
        alert(e.message);
    }
}
