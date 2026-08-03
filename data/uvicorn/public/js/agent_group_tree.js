// Shared tree utilities for agent/workflow group_name sidebar rendering.
// group_name supports nested folders via '/' delimiter (e.g. 'Projects/Design').

export function buildGroupTree(items) {
    const root = { items: [], children: {} };
    for (const item of items) {
        const parts = (item.group_name || '').trim()
            .split('/').map(p => p.trim()).filter(Boolean);
        let node = root;
        for (const part of parts) {
            if (!node.children[part]) node.children[part] = { items: [], children: {} };
            node = node.children[part];
        }
        node.items.push(item);
    }
    return root;
}

// renderItemFn(item, depth, indent) => HTMLElement | null
export function renderGroupTree(treeNode, container, depth, storageKeyBase, renderItemFn, _pathSoFar = '') {
    const indent = 10 + depth * 14;

    Object.keys(treeNode.children).sort((a, b) => a.localeCompare(b, 'ru')).forEach(folderName => {
        const fullPath = _pathSoFar ? `${_pathSoFar}/${folderName}` : folderName;
        const storageKey = `${storageKeyBase}_${fullPath}`;
        const isOpen = localStorage.getItem(storageKey) !== '0';

        const folderHeader = document.createElement('div');
        folderHeader.className = 'group-folder-header';
        folderHeader.style.paddingLeft = `${indent}px`;
        folderHeader.innerHTML = `<span class="folder-icon">${isOpen ? '📂' : '📁'}</span><span class="group-folder-name">${folderName}</span>`;
        container.appendChild(folderHeader);

        const folderBody = document.createElement('div');
        folderBody.style.display = isOpen ? '' : 'none';
        container.appendChild(folderBody);

        renderGroupTree(treeNode.children[folderName], folderBody, depth + 1, storageKeyBase, renderItemFn, fullPath);

        folderHeader.addEventListener('click', () => {
            const open = folderBody.style.display !== 'none';
            folderBody.style.display = open ? 'none' : '';
            folderHeader.querySelector('.folder-icon').textContent = open ? '📁' : '📂';
            localStorage.setItem(storageKey, open ? '0' : '1');
        });
    });

    treeNode.items.forEach(item => {
        const el = renderItemFn(item, depth, indent);
        if (el) container.appendChild(el);
    });
}
