// Ошибка ответа API: вытягивает detail/message из JSON-тела, иначе — HTTP-статус.
// FastAPI кладет причину в {detail: "..."} (или массив объектов при 422-валидации).
//
// ⚠ Код ответа едет на самой ошибке (`error.status`): отказ по существу (409 —
// «так нельзя, и вот почему») вызывающий показывает иначе, чем поломку, а
// отличить их по тексту нечем.
async function apiError(response) {
    let message = `Ошибка: ${response.status}`;
    try {
        const body = await response.json();
        const detail = body.detail ?? body.message;
        if (typeof detail === 'string' && detail) message = detail;
        else if (detail) message = JSON.stringify(detail);
    } catch {
        // тело не JSON (HTML от прокси и т.п.) — оставляем статус
    }
    const error = new Error(message);
    error.status = response.status;
    return error;
}

export async function getData(url) {
    const options = {
        method: 'GET',
        headers: {'Content-Type': 'application/json'},
        credentials: 'include'
    };

    const response = await fetch(url, options);
    if (!response.ok) throw await apiError(response);
    return await response.json();
}

export async function postData(url, data = {}) {
    const options = {
        method: 'POST',
        headers: data instanceof FormData ? {} : {'Content-Type': 'application/json'},
        body: data instanceof FormData ? data : JSON.stringify(data),
        credentials: 'include'
    };

    const response = await fetch(url, options);
    if (!response.ok) throw await apiError(response);
    return await response.json();
}

export async function putData(url, data = {}) {
    const response = await fetch(url, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
        credentials: 'include'
    });
    if (!response.ok) throw await apiError(response);
    return await response.json();
}

export async function deleteData(url) {
    const options = {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        credentials: 'include'
    };

    const response = await fetch(url, options);
    if (!response.ok) throw await apiError(response);
    return await response.json();
}

/**
 * Забрать с ручки файл и отдать его человеку — имя берётся у сервера.
 *
 * ⚠⚠ Почему не `<a href>` и не `window.open`: сессия в куке, и ссылка бы
 * сработала — но отказ ручки открылся бы вкладкой с голым JSON `{"detail": …}`
 * вместо уведомления, а пока файл собирается (печать PDF — это секунды),
 * человек не видел бы ничего. Через `fetch` отказ приезжает обычным
 * исключением `apiError`, то есть ровно тем же, что у соседних функций.
 *
 * ⚠ Имя файла назначает сервер (`Content-Disposition`), а не вызывающий:
 * оно собрано там же, где содержимое, и второй источник имени разошёлся бы
 * с первым. `fallbackName` — только на случай ручки без заголовка.
 *
 * @param {string} url адрес ручки.
 * @param {string} fallbackName имя, если сервер своего не назвал.
 * @returns {Promise<string>} имя, под которым файл сохранён.
 */
export async function getFile(url, fallbackName = 'download') {
    const response = await fetch(url, {method: 'GET', credentials: 'include'});
    if (!response.ok) throw await apiError(response);

    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = fileNameOf(response.headers.get('Content-Disposition')) || fallbackName;
    document.body.appendChild(link);
    link.click();
    link.remove();

    // ⚠ Отзыв ссылки отложен: синхронный `revokeObjectURL` сразу после click()
    // обрывает скачивание крупного файла — браузер не успевает прочитать Blob.
    setTimeout(() => URL.revokeObjectURL(link.href), 60_000);
    return link.download;
}

// Имя файла из заголовка `Content-Disposition`; пусто, если его там нет.
//
// ⚠ Сперва `filename*` (RFC 5987, процентное кодирование UTF-8), потом простое
// `filename`: когда имя неASCII, сервер шлёт оба, и простое в таком случае —
// транслитерация или знаки вопроса.
function fileNameOf(header) {
    if (!header) return '';
    const extended = header.match(/filename\*=UTF-8''([^;]+)/i);
    if (extended) {
        try {
            return decodeURIComponent(extended[1]);
        } catch {
            // битое кодирование — пробуем простое имя ниже
        }
    }
    const plain = header.match(/filename="?([^";]+)"?/i);
    return plain ? plain[1] : '';
}
