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
