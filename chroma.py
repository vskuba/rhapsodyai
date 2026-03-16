import chromadb

client = chromadb.HttpClient(host='localhost', port=8000)

try:
    # Проверяем список коллекций через новый клиент
    collections = client.list_collections()
    print(f"Доступные коллекции: {[c.name for c in collections]}")

    collection = client.get_collection("bank_memory")
    data = collection.get()

    print(f"\nНайдено записей: {len(data['ids'])}")
    for i in range(len(data['ids'])):
        print(f"ID: {data['ids'][i]} | Факт: {data['documents'][i]}")
except Exception as e:
    print(f"Ошибка при чтении: {e}")