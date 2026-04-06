import os
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq
from fastapi.middleware.cors import CORSMiddleware

# Import local services
from services.qdrant_service import QdrantService
from services.chunking_service import ChunkingService

# Load environment variables (e.g., GROQ_API_KEY)
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Groq Chatbot API with RAG")

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Groq client
try:
    api_key = os.environ.get("GROQ_API_KEY")
    groq_client = Groq(api_key=api_key)
except Exception as e:
    print(f"Warning: Failed to initialize Groq client: {e}")
    groq_client = None

# Initialize RAG Services
qdrant_service = QdrantService()
chunking_service = ChunkingService()

# Pydantic models for request validation
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    model: Optional[str] = os.environ.get("MODEL", "llama3-8b-8192")

class ChatResponse(BaseModel):
    response: str

class IngestRequest(BaseModel):
    text: str
    metadata: Optional[Dict[str, Any]] = None

class IngestResponse(BaseModel):
    message: str
    chunks_processed: int

@app.post("/api/ingest", response_model=IngestResponse)
async def ingest_document(request: IngestRequest):
    try:
        # 1. Process and chunk the input text
        processed_data = chunking_service.process_and_chunk(
            text=request.text, 
            source_metadata=request.metadata
        )
        
        # 2. Store the chunks in Qdrant
        qdrant_service.upsert_documents(
            documents=processed_data["documents"],
            metadatas=processed_data["metadatas"]
        )
        
        return {
            "message": "Document successfully ingested and processed.",
            "chunks_processed": len(processed_data["documents"])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    if not groq_client:
        raise HTTPException(
            status_code=500, 
            detail="Groq API client is not initialized. Please ensure your GROQ_API_KEY is set in the .env file."
        )
    
    try:
        # Convert Pydantic Message models to dictionaries for the Groq API
        messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        # RAG Implementation: Find the last user message to fetch relevant context
        last_user_message = next((msg.content for msg in reversed(request.messages) if msg.role == "user"), None)
        
        if last_user_message:
            # 1. Retrieve relevant chunks from Qdrant
            results = qdrant_service.search(query=last_user_message, limit=3)
            
            # 2. Augment the prompt with the retrieved context
            if results:
                context_texts = "\n---\n".join(
                    [f"Context Chunk:\n{r['text']}" for r in results]
                )
                system_prompt = (
                    "Use the following additional context to inform your answer. "
                    f"If it doesn't help, answer normally based on your knowledge:\n\n{context_texts}"
                )
                
                # Check if there is already a system prompt, update it, or add one.
                if messages_dict and messages_dict[0]["role"] == "system":
                    messages_dict[0]["content"] += f"\n\n{system_prompt}"
                else:
                    messages_dict.insert(0, {"role": "system", "content": system_prompt})
        
        # Call Groq API
        chat_completion = groq_client.chat.completions.create(
            messages=messages_dict,
            model=request.model,
        )
        
        # Extract the bots response
        bot_response = chat_completion.choices[0].message.content
        return {"response": bot_response}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Groq Chatbot API with RAG is running"}
