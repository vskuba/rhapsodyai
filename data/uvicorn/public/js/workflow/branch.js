/**
 * Вкладка «Branch» страницы Workflow: ветки разговора и темы внутри них.
 *
 * Ветка — род разговора со своим контрактом и необязательным подпотоком. Тема —
 * запись внутри ветки: метки и три текста (разрешено / желательно / запрещено).
 *
 * ⚠ Ветки принадлежат **ноде**, а не отдельному workflow: их читает шаг `branch`
 * любого workflow этой ноды. Поэтому список берётся по ноде, выбранной в левой
 * карусели страницы, а не по открытому workflow.
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
    page: 0,
    branchId: null,
    topics: [],
    topicId: null,
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

/**
 * Открыть вкладку: загрузить ветки выбранной ноды и нарисовать.
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
        branchState.branchId = null;
        branchState.topicId = null;
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
          <div class="branch-empty">Выберите ветку слева или заведите новую</div>
        </div>
      </div>`;

    document.getElementById('branchNew').onclick = branchNew;
    document.getElementById('branchPagePrev').onclick = () => {
        if (branchState.page > 0) {
            branchState.page -= 1;
            branchesRender();
        }
    };
    document.getElementById('branchPageNext').onclick = () => {
        if ((branchState.page + 1) * PAGE_SIZE < branchState.branches.length) {
            branchState.page += 1;
            branchesRender();
        }
    };

    await workflowsLoad();
    await branchesLoad();
    if (branchState.branchId) await branchOpen(branchState.branchId);
}

async function workflowsLoad() {
    try {
        branchState.workflows = (await branchApi(
            `/workflow/${branchState.nodeId}/list`)).result || [];
    } catch (e) {
        branchState.workflows = [];
    }
}

async function branchesLoad() {
    branchState.branches = (await branchApi(
        `/workflow_branch/list?node_id=${branchState.nodeId}`)).result || [];
    if (branchState.page * PAGE_SIZE >= branchState.branches.length) branchState.page = 0;
    branchesRender();
}

function branchesRender() {
    const list = document.getElementById('branchList');
    if (!list) return;

    if (!branchState.branches.length) {
        list.innerHTML = '<div class="branch-empty">Веток нет</div>';
        document.getElementById('branchPageLabel').textContent = '0';
        return;
    }

    const from = branchState.page * PAGE_SIZE;
    list.innerHTML = branchState.branches.slice(from, from + PAGE_SIZE).map(branch => `
        <div class="branch-row ${branch.id === branchState.branchId ? 'is-active' : ''}"
             data-id="${branch.id}">
          <span class="branch-dot ${branch.is_enabled ? 'is-on' : ''}"></span>
          <span class="branch-row-main">
            <span class="branch-row-title">${esc(branch.title)}</span><br>
            <span class="branch-row-name">${esc(branch.name)}</span>
          </span>
          <span class="branch-row-count">${plural(branch.topic_count, 'тема', 'темы', 'тем')}</span>
        </div>`).join('');

    list.querySelectorAll('.branch-row').forEach(row => {
        row.onclick = () => branchOpen(Number(row.dataset.id));
    });

    const pages = Math.ceil(branchState.branches.length / PAGE_SIZE);
    document.getElementById('branchPageLabel').textContent = `${branchState.page + 1} / ${pages}`;
}

async function branchOpen(branchId) {
    branchState.branchId = branchId;
    branchState.topicId = null;
    branchState.topics = (await branchApi(
        `/workflow_branch/${branchId}/topic/list`)).result || [];
    branchesRender();
    detailRender();
}

function branchCurrent() {
    return branchState.branches.find(b => b.id === branchState.branchId) || null;
}

function detailRender() {
    const branch = branchCurrent();
    const detail = document.getElementById('branchDetail');
    if (!detail) return;

    if (!branch) {
        detail.innerHTML = '<div class="branch-empty">Выберите ветку слева или заведите новую</div>';
        return;
    }

    const subflowOptions = ['<option value="">— нет, ветка сужает общий ответ —</option>']
        .concat(branchState.workflows.map(w =>
            `<option value="${w.id}" ${String(w.id) === String(branch.workflow_id) ? 'selected' : ''}>`
            + `${esc(w.title || w.name)}</option>`))
        .join('');

    detail.innerHTML = `
      <div class="branch-card">
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
          <button type="button" class="btn-branch btn-branch-danger" id="b_delete">Удалить ветку</button>
        </div>

        <div class="branch-section">Темы ветки</div>
        <div id="topicList"></div>
        <button type="button" class="btn-branch" id="t_new" style="margin-top:8px">+ Тема</button>
        <div id="topicForm"></div>
      </div>`;

    document.getElementById('b_save').onclick = branchSave;
    document.getElementById('b_delete').onclick = branchDelete;
    document.getElementById('t_new').onclick = () => topicForm(null);
    const subflowButton = document.getElementById('b_subflow_new');
    if (subflowButton) subflowButton.onclick = branchSubflowCreate;

    topicsRender();
}

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
        await branchesLoad();
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
    branchState.branchId = null;
    await branchesLoad();
    detailRender();
}

async function branchSubflowCreate() {
    const branch = branchCurrent();
    try {
        const created = await branchApi(`/workflow_branch/${branch.id}/subflow`, {method: 'POST'});
        await workflowsLoad();
        await branchesLoad();
        detailRender();
        alert(`Subflow заведён (id ${created.result.workflow_id}). `
              + `Его шаги правятся на вкладке «Шаги».`);
    } catch (e) {
        alert(e.message);
    }
}

function topicsRender() {
    const holder = document.getElementById('topicList');
    if (!holder) return;

    if (!branchState.topics.length) {
        holder.innerHTML = '<div class="branch-empty">Тем пока нет</div>';
        return;
    }

    holder.innerHTML = branchState.topics.map(topic => {
        const tags = tagList(topic.tags);
        return `
          <div class="topic-row ${topic.id === branchState.topicId ? 'is-active' : ''}"
               data-id="${topic.id}">
            <div class="topic-row-head">
              <span class="branch-dot ${topic.is_enabled ? 'is-on' : ''}"></span>
              <span class="topic-row-title">${esc(topic.title)}</span>
              <span class="topic-count">${plural(tags.length, 'метка', 'метки', 'меток')}</span>
            </div>
            <div class="branch-row-name">${esc(topic.name)}</div>
            <div class="topic-tags">
              ${tags.map(t => `<span class="topic-tag">${esc(t)}</span>`).join('')}
            </div>
          </div>`;
    }).join('');

    holder.querySelectorAll('.topic-row').forEach(row => {
        row.onclick = () => topicForm(Number(row.dataset.id));
    });
}

function topicForm(topicId) {
    branchState.topicId = topicId;
    const topic = branchState.topics.find(t => t.id === topicId) || {
        name: '', title: '', tags: '', acceptance: '', direction: '', restriction: '',
        is_enabled: 1,
    };

    topicsRender();
    document.getElementById('topicForm').innerHTML = `
      <div class="branch-section">${topicId ? 'Правка темы' : 'Новая тема'}</div>
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
        ${topicId ? '<button type="button" class="btn-branch btn-branch-danger" id="t_delete">Удалить тему</button>' : ''}
      </div>`;

    document.getElementById('t_save').onclick = () => topicSave(topicId);
    const removeButton = document.getElementById('t_delete');
    if (removeButton) removeButton.onclick = () => topicDelete(topicId);
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
    try {
        if (topicId) {
            await branchApi(`/workflow_branch/topic/${topicId}`, {method: 'PUT', headers, body});
        } else {
            await branchApi(`/workflow_branch/${branchState.branchId}/topic`,
                            {method: 'POST', headers, body});
        }
        await branchesLoad();
        await branchOpen(branchState.branchId);
    } catch (e) {
        alert(e.message);
    }
}

async function topicDelete(topicId) {
    if (!confirm('Удалить тему?')) return;
    await branchApi(`/workflow_branch/topic/${topicId}`, {method: 'DELETE'});
    branchState.topicId = null;
    await branchesLoad();
    await branchOpen(branchState.branchId);
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
        await branchesLoad();
        await branchOpen(created.result.id);
    } catch (e) {
        alert(e.message);
    }
}
