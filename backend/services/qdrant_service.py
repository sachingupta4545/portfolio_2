import os
import uuid
import time
from typing import List, Dict, Any
from qdrant_client import QdrantClient, models

class QdrantService:
    def __init__(self, collection_name: str = "chatbot_docs"):
        self.collection_name = collection_name

        qdrant_url = os.environ.get("QDRANT_URL")
        qdrant_api_key = os.environ.get("QDRANT_API_KEY")

        if qdrant_url:
            print(f"🌐 Attempting Qdrant Cloud connection: {qdrant_url}")
            try:
                self.client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
                # Test the connection immediately
                self.client.get_collections()
                print("✅ Connected to Qdrant Cloud!")
            except Exception as e:
                print(f"⚠️  Cloud unreachable ({e}). Falling back to local storage...")
                self._use_local_storage()
        else:
            self._use_local_storage()

        # Ensure the collection exists on startup
        self._ensure_collection()

    def _use_local_storage(self):
        """Set up local file-based Qdrant storage."""
        db_path = os.path.join(os.path.dirname(__file__), "..", "qdrant_data")
        os.makedirs(db_path, exist_ok=True)
        self.client = QdrantClient(path=db_path)
        print("💾 Using local Qdrant storage (qdrant_data/)")

    def _ensure_collection(self):
        """Creates the collection if it doesn't already exist."""
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection_name not in existing:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=384,  # BAAI/bge-small-en-v1.5 output dimension
                    distance=models.Distance.COSINE,
                ),
            )
            print(f"Collection '{self.collection_name}' created.")


    def upsert_documents(self, documents: List[str], metadatas: List[Dict[str, Any]]):
        """
        Takes raw text chunks and their metadata, generates embeddings using Fastembed,
        and stores them in Qdrant using the modern Document wrapper API.
        """
        if not documents:
            return

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=models.Document(text=doc, model="BAAI/bge-small-en-v1.5"),
                    payload={**meta, "document": doc}
                )
                for doc, meta in zip(documents, metadatas)
            ]
        )

    def clear_collection(self):
        """
        Deletes the collection, wiping all existing data.
        Ensures it is recreated immediately so it is ready for the next upload.
        """
        try:
            self.client.delete_collection(collection_name=self.collection_name)
            print(f"Collection '{self.collection_name}' cleared.")
        except Exception as e:
            print(f"Note: Could not clear collection (may not exist yet): {e}")
        # Always recreate so next upsert doesn't fail
        self._ensure_collection()


    def search(self, query: str, limit: int = 4) -> List[Dict[str, Any]]:
        """
        Searches for the closest chunks to the given query using the modern query_points API.
        """
        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=models.Document(text=query, model="BAAI/bge-small-en-v1.5"),
                limit=limit
            )

            formatted = []
            for r in results.points:
                payload = r.payload or {}
                formatted.append({
                    "text": payload.get("document", ""),
                    "metadata": {k: v for k, v in payload.items() if k != "document"},
                    "score": r.score
                })
            return formatted
        except Exception as e:
            print(f"Error during search (collection might be empty): {e}")
            return []
