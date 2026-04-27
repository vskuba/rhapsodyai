const progressBar = document.getElementById('topProgressBar');

// Единая функция индикации загрузки
export function toggleLoading(show) {
    progressBar.classList.toggle('progress-active', show);
}