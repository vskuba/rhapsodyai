// Точка входа PWA detective. Заготовка - реальный игровой UI (чат с
// подозреваемыми/сержантом через /chat/ask) добавляется отдельным шагом.

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/play/detective/sw.js');
}
