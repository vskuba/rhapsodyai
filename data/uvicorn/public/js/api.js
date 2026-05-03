export async function getData(url) {
    const options = {
        method: 'GET',
        headers: {'Content-Type': 'application/json'}
    };

    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`Ошибка GET: ${response.status}`);
    return await response.json();
}

export async function postData(url, data = {}) {
    const options = {
        method: 'POST',
        headers: data instanceof FormData ? {} : {'Content-Type': 'application/json'},
        body: data instanceof FormData ? data : JSON.stringify(data)
    };

    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`Ошибка: ${response.status}`);
    return await response.json();
}

export async function putData(url, data = {}) {
    const response = await fetch(url, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `Ошибка: ${response.status}`);
    }
    return await response.json();
}

export async function deleteData(url) {
    const options = {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'}
    };

    const response = await fetch(url, options);

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `Ошибка: ${response.status}`);
    }

    return await response.json();
}