from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
import datetime

class ChunkingService:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

    def process_and_chunk(self, text: str, source_metadata: Dict[str, Any] = None) -> Dict[str, List]:
        """
        Splits text into highly reusable chunks and adds context-rich metadata.
        """
        chunks = self.text_splitter.split_text(text)
        
        documents = []
        metadatas = []
        
        base_meta = source_metadata or {}
        ingest_time = datetime.datetime.now().isoformat()
        
        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            
            # Enrich metadata with niche filtering properties
            meta = base_meta.copy()
            meta["chunk_index"] = i
            meta["total_chunks"] = len(chunks)
            meta["ingest_time"] = ingest_time
            metadatas.append(meta)
            
        return {
            "documents": documents,
            "metadatas": metadatas
        }
