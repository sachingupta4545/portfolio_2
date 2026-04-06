import os
from typing import List, Dict, Any
from qdrant_client import QdrantClient

class QdrantService:
    def __init__(self, collection_name: str = "chatbot_docs"):
        self.collection_name = collection_name
        # Use local persistent storage by default
        db_path = os.path.join(os.path.dirname(__file__), "..", "qdrant_data")
        os.makedirs(db_path, exist_ok=True)
        
        # Initialize client with local path
        self.client = QdrantClient(path=db_path)
        
        # Set the fastembed model (downloads it on first run if not cached)
        self.client.set_model("BAAI/bge-small-en-v1.5")
    
    def upsert_documents(self, documents: List[str], metadatas: List[Dict[str, Any]]):
        """
        Takes raw text chunks and their metadata, generates embeddings using Fastembed,
        and stores them in Qdrant.
        """
        if not documents:
            return
            
        self.client.add(
            collection_name=self.collection_name,
            documents=documents,
            metadata=metadatas
        )

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Searches the collection for the closest chunks to the given query.
        Returns the raw text and metadata.
        """
        # If collection is empty, this handles the exception gracefully
        try:
            results = self.client.query(
                collection_name=self.collection_name,
                query_text=query,
                limit=limit
            )
            
            # format results for easy consumption
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "text": result.document,
                    "metadata": result.metadata,
                    "score": result.score
                })
            return formatted_results
        except Exception as e:
            print(f"Error during search (collection might be empty): {e}")
            return []
