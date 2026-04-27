export async function postData(url, data = {}) {
    const options = {
        method: 'POST',
        headers: data instanceof FormData ? {} : { 'Content-Type': 'application/json' },
        body: data instanceof FormData ? data : JSON.stringify(data)
    };

    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`Ошибка: ${response.status}`);
    return await response.json();
}