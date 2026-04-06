import os
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from groq import Groq
from fastapi.middleware.cors import CORSMiddleware

# Import local services
from services.qdrant_service import QdrantService
from services.chunking_service import ChunkingService
from services.resume_parser import extract_text_from_pdf
from services.llm_metadata_service import LlmMetadataService

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Resume Chatbot API (RAG + Groq)")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Initialize RAG services
qdrant_service = QdrantService()
chunking_service = ChunkingService()
llm_metadata_service = LlmMetadataService(groq_client=groq_client) if groq_client else None

# Recruiter-mode system prompt
RECRUITER_SYSTEM_PROMPT = (
    "You are a professional AI assistant representing a job candidate. "
    "You are speaking with an HR professional or recruiter. "
    "Your goal is to present the candidate's experience, skills, and achievements "
    "in a confident, clear, and positive manner based solely on the context provided. "
    "If a question is asked that isn't covered in their resume, politely say you don't have "
    "that information. Do not make up any information. Always be professional and concise."
)

# ---------- Pydantic Models ----------

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

class UploadResumeResponse(BaseModel):
    message: str
    chunks_processed: int
    extracted_metadata: Dict[str, Any]

# ---------- Endpoints ----------

@app.post("/api/upload-resume", response_model=UploadResumeResponse)
async def upload_resume(file: UploadFile = File(...), replace_existing: bool = Form(default=True)):
    """
    Accepts a PDF resume, extracts text, uses the LLM to parse structured metadata
    (experience, skills, projects), chunks the text, and stores everything in Qdrant.
    Set replace_existing=true (default) to wipe previous resume data before ingesting.
    """
    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    try:
        # 1. Read uploaded file bytes
        file_bytes = await file.read()

        # 2. Extract raw text from PDF
        resume_text = extract_text_from_pdf(file_bytes)
        if not resume_text.strip():
            raise HTTPException(status_code=422, detail="Could not extract text from the PDF. The file may be scanned or image-based.")

        # 3. Use LLM to extract structured metadata
        if llm_metadata_service:
            extracted_metadata = llm_metadata_service.extract_resume_metadata(resume_text)
        else:
            extracted_metadata = {}
        
        # Add file-level metadata
        extracted_metadata["source"] = file.filename
        extracted_metadata["document_type"] = "resume"

        # 4. Optionally wipe the collection so only this resume is referenced
        if replace_existing:
            qdrant_service.clear_collection()

        # 5. Chunk the resume text, passing the extracted metadata to every chunk
        processed = chunking_service.process_and_chunk(
            text=resume_text,
            source_metadata=extracted_metadata
        )

        # 6. Upsert into Qdrant
        qdrant_service.upsert_documents(
            documents=processed["documents"],
            metadatas=processed["metadatas"]
        )

        return {
            "message": f"Resume '{file.filename}' successfully processed and stored.",
            "chunks_processed": len(processed["documents"]),
            "extracted_metadata": extracted_metadata,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resume processing failed: {str(e)}")


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest_document(request: IngestRequest):
    """General-purpose text ingestion endpoint."""
    try:
        processed = chunking_service.process_and_chunk(
            text=request.text,
            source_metadata=request.metadata
        )
        qdrant_service.upsert_documents(
            documents=processed["documents"],
            metadatas=processed["metadatas"]
        )
        return {
            "message": "Document successfully ingested and processed.",
            "chunks_processed": len(processed["documents"])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    RAG-powered chat endpoint. Retrieves relevant resume context from Qdrant,
    injects it into a recruiter-persona system prompt, then calls Groq.
    """
    if not groq_client:
        raise HTTPException(
            status_code=500,
            detail="Groq API client is not initialized. Please ensure your GROQ_API_KEY is set in the .env file."
        )

    try:
        messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        # RAG: use the last user message to retrieve context
        last_user_message = next(
            (msg.content for msg in reversed(request.messages) if msg.role == "user"), None
        )

        system_prompt = RECRUITER_SYSTEM_PROMPT

        if last_user_message:
            results = qdrant_service.search(query=last_user_message, limit=4)
            if results:
                context_texts = "\n---\n".join(
                    [f"Resume Excerpt:\n{r['text']}" for r in results]
                )
                system_prompt += (
                    f"\n\nUse the following excerpts from the candidate's resume to answer the recruiter's question:\n\n{context_texts}"
                )

        # Inject or replace system prompt
        if messages_dict and messages_dict[0]["role"] == "system":
            messages_dict[0]["content"] = system_prompt
        else:
            messages_dict.insert(0, {"role": "system", "content": system_prompt})

        chat_completion = groq_client.chat.completions.create(
            messages=messages_dict,
            model=request.model,
        )

        bot_response = chat_completion.choices[0].message.content
        return {"response": bot_response}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Resume Chatbot API with RAG is running"}
