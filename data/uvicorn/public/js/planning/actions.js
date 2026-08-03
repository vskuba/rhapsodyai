// Project CRUD actions and modal helpers

function openNewModal() {
    document.getElementById('newTitle').value = '';
    document.getElementById('newIdea').value = '';
    document.getElementById('newModal').classList.add('visible');
    setTimeout(() => document.getElementById('newTitle').focus(), 50);
}

async function createProject() {
    const title = document.getElementById('newTitle').value.trim();
    const idea = document.getElementById('newIdea').value.trim();
    if (!idea) { alert('Введите описание идеи'); return; }
    const btn = document.getElementById('btnCreate');
    btn.disabled = true;
    btn.textContent = 'Создаём...';
    try {
        const res = await fetch('/planning/project', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title, idea}),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        closeModal('newModal');
        currentProjectId = null;
        await loadProjects(false);
        const newId = data.result;
        const el = document.querySelector(`.project-item[data-id="${newId}"]`);
        if (el) selectProject(newId, el);
    } catch (e) {
        alert('Ошибка: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Создать и запустить анализ';
    }
}

async function retryProject(id) {
    if (!confirm('Полный сброс: удалить все фазы и документы, запустить с нуля?')) return;
    try {
        const res = await fetch(`/planning/project/${id}/retry`, {method: 'POST'});
        if (!res.ok) throw new Error(await res.text());
        await loadProjects(true);
        selectProject(id, document.querySelector(`.project-item[data-id="${id}"]`));
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function retryPhase(id, phase) {
    const LABELS = {'analyze':'Анализ идеи','market':'Исследование рынка','product':'Продуктовый план',
        'tech':'Тех. архитектура','gtm':'GTM-стратегия','financial':'Финансовая модель',
        'blueprint':'Blueprint','score':'Оценка Blueprint','supplement':'Дополнение'};
    let label = LABELS[phase];
    if (!label && phase.startsWith('supplement_')) {
        const subKey = phase.replace('supplement_', '');
        label = 'Дополнение: ' + (_phaseTitles[phase] || subKey);
    }
    label = label || phase;
    if (!confirm(`Сбросить фазу «${label}» и запустить повторно?`)) return;
    try {
        const res = await fetch(`/planning/project/${id}/phase/${phase}/retry`, {method: 'POST'});
        if (!res.ok) throw new Error(await res.text());
        await loadProjects(true);
        selectProject(id, document.querySelector(`.project-item[data-id="${id}"]`));
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function deleteProject(id) {
    if (!confirm('Удалить проект и все его данные?')) return;
    await fetch(`/planning/project/${id}`, {method: 'DELETE'});
    currentProjectId = null;
    allProjects = allProjects.filter(p => p.id !== id);
    document.getElementById('mainPanel').innerHTML = '<div class="placeholder-panel">Выберите проект</div>';
    loadProjects(false);
}

async function deletePrototypeVersion(projectId, version) {
    if (!confirm(`Удалить прототип v${version}?`)) return;
    try {
        await fetch(`/planning/project/${projectId}/prototype/${version}`, {method: 'DELETE'});
        selectProject(projectId);
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

function closeModal(id) {
    document.getElementById(id).classList.remove('visible');
}
