import chromadb
from chromadb import ClientAPI

chroma_client: ClientAPI | None = None

def _chroma_db_get_client() -> ClientAPI:
    """
    Create chroma collection
    """
    global chroma_client

    if chroma_client:
        return chroma_client

    # chroma_client = chromadb.PersistentClient(path="./" + config_get('DATA_DIR') + "/chroma_db_memory")
    # chroma_collection = chroma_client.get_or_create_collection("bank_memory")

    chroma_client = chromadb.HttpClient(host='chroma', port=8000)
    # chroma_collection = chroma_client.get_or_create_collection(collection_name)

    return chroma_client
