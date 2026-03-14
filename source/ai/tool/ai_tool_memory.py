import uuid

import chromadb

from source.config import config_get

chroma_collection: chromadb.Collection | None = None


def _chromadb_memory_auth() -> chromadb.Collection:
    """
    Create chroma collection
    """
    global chroma_collection

    if chroma_collection:
        return chroma_collection

    chroma_client = chromadb.PersistentClient(path="./"+config_get('DATA_DIR')+"/chroma_db_memory")
    chroma_collection = chroma_client.get_or_create_collection("bank_memory")

    return chroma_collection


async def chromadb_memory_save(fact: str):
    """This tool converts the input text into a high-dimensional vector embedding and stores
    it in the ChromaDB collection. This allows for persistent long-term memory, enabling the
    agent to perform semantic searches and retrieve relevant context in future interactions."""
    unique_id = str(uuid.uuid4())[:8]

    _chromadb_memory_auth().add(
        documents=[fact],
        ids=[f"fact_{unique_id}"]
    )

    return "Saved to memory."


async def chromadb_memory_search(query: str):
    """Performs a semantic similarity search within the ChromaDB collection to retrieve relevant
    context or past information. It converts the query into an embedding and returns the most
    closely related documents, effectively providing the agent with access to its long-term memory
    and previously stored knowledge."""
    results = _chromadb_memory_auth().query(
        query_texts=[query],
        n_results=2
    )

    return results['documents']
