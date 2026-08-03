// Entry point — state variables, tab switching, init

let currentProjectId = null;
let currentTab = 'projects';
let autoRefreshTimer = null;
let autoRefreshRunning = false;
let allProjects = [];
let compareFilter = 'all';
let compareSortKey = 'score_total';
let compareSortDir = -1;
let generatedIdeas = [];
let ideaHistory = JSON.parse(localStorage.getItem('planningIdeaHistory') || '[]');

function switchTab(tab) {
    currentTab = tab;
    const isIdeas = tab === 'ideas';
    document.getElementById('tabProjects').classList.toggle('active', tab === 'projects');
    document.getElementById('tabCompare').classList.toggle('active', tab === 'compare');
    document.getElementById('tabIdeas').classList.toggle('active', isIdeas);
    document.getElementById('mainPanel').style.display = isIdeas ? 'none' : '';
    document.getElementById('ideasPanel').style.display = isIdeas ? '' : 'none';

    if (tab === 'compare') {
        renderCompare();
    } else if (tab === 'ideas') {
        renderIdeasHistory();
    } else if (currentProjectId) {
        const el = document.querySelector(`.project-item[data-id="${currentProjectId}"]`);
        selectProject(currentProjectId, el);
    } else {
        document.getElementById('mainPanel').innerHTML = '<div class="placeholder-panel">Выберите проект</div>';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.modal-overlay').forEach(m => {
        m.addEventListener('click', e => { if (e.target === m) m.classList.remove('visible'); });
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.visible').forEach(m => m.classList.remove('visible'));
    });

    loadPhaseSections();
    autoRefreshStart();
    loadProjects();
});
