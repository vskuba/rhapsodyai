/**
 * Инициализирует draggable-разделитель между сайдбаром и основным контентом.
 * Сохраняет ширину в localStorage.
 *
 * @param {string} resizerId  - id элемента-разделителя
 * @param {string} storageKey - ключ для localStorage
 * @param {Element} sidebar   - элемент сайдбара (по умолчанию ближайший предыдущий сиблинг)
 * @param {number} minW       - минимальная ширина px (default 160)
 * @param {number} maxW       - максимальная ширина px (default 520)
 */
function initSidebarResizer(resizerId, storageKey, sidebar, minW = 160, maxW = 520) {
    const resizer = document.getElementById(resizerId);
    if (!resizer || !sidebar) return;

    const saved = parseInt(localStorage.getItem(storageKey), 10);
    if (saved && saved >= minW && saved <= maxW) sidebar.style.width = saved + 'px';

    resizer.addEventListener('mousedown', e => {
        const startX = e.clientX;
        const startW = sidebar.getBoundingClientRect().width;
        resizer.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        function onMove(e) {
            const w = Math.min(maxW, Math.max(minW, startW + e.clientX - startX));
            sidebar.style.width = w + 'px';
        }

        function onUp() {
            resizer.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            localStorage.setItem(storageKey, parseInt(sidebar.style.width, 10));
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        }

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}
