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
from services.llm_metadata_service import LlmMetadataService, ProjectIngestionService

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Resume Chatbot API (RAG + Groq)")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://127.0.0.1",
        "https://portfolio-2-iota-dun.vercel.app",
    ],
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
qdrant_service        = QdrantService()
chunking_service      = ChunkingService()
llm_metadata_service  = LlmMetadataService(groq_client=groq_client)  if groq_client else None
project_ingest_service = ProjectIngestionService(groq_client=groq_client) if groq_client else None

# ---------- System Prompt ----------

SYSTEM_PROMPT = (
    "You are an intelligent AI assistant representing a software engineer and developer. "
    "You have two modes:\n"
    "1. RECRUITER MODE: When answering general HR/recruiter questions about experience, "
    "skills, education, or background — be confident, concise, and professional. "
    "Use bullet points where helpful. Keep general answers under 150 words.\n"
    "2. TECHNICAL MODE: When asked about a specific project's architecture, database design, "
    "API design, core logic, challenges, or implementation details — switch to a Senior "
    "Engineer mode. Give thorough, structured technical explanations using the context provided. "
    "Use headers and bullet points. Do NOT truncate technical answers.\n"
    "In BOTH modes: Answer using ONLY the context provided. "
    "If information is not in the context, say so honestly. Never fabricate."
)

# Max non-system conversation turns kept in sliding window
MAX_HISTORY_MESSAGES = 6

# ---------- Pydantic Models ----------

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    model: Optional[str] = os.environ.get("MODEL", "llama3-8b-8192")

class ChatResponse(BaseModel):
    response: str

class UploadResumeResponse(BaseModel):
    message: str
    chunks_processed: int
    extracted_metadata: Dict[str, Any]

class UploadProjectResponse(BaseModel):
    message: str
    project_name: str
    chunks_processed: int

# ---------- Helper: read text from an uploaded file ----------

async def _read_file_text(file: UploadFile) -> str:
    """
    Reads raw text from .pdf, .md, or .txt uploads.
    Raises HTTPException on unsupported types or empty content.
    """
    filename_lower = file.filename.lower()
    file_bytes = await file.read()

    if filename_lower.endswith(".pdf"):
        text = extract_text_from_pdf(file_bytes)
    elif filename_lower.endswith((".md", ".txt")):
        text = file_bytes.decode("utf-8", errors="ignore")
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a .pdf, .md, or .txt file."
        )

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract text from the file. The file may be empty or image-based."
        )
    return text

# =====================================================================
# API 1  —  /api/upload-resume
# =====================================================================

@app.post("/api/upload-resume", response_model=UploadResumeResponse)
async def upload_resume(
    file: UploadFile = File(...),
    replace_existing: bool = Form(default=True)
):
    """
    Upload your main resume (PDF, MD, or TXT).

    The LLM extracts:
      - Profile (name, contact, summary)
      - Full tech stack + categorised tools (languages, frameworks, DevOps, cloud …)
      - Work experience with date-computed total years
      - Education & certifications
      - High-level project summaries

    Use replace_existing=true (default) to wipe the database before ingesting
    so that stale resume data is removed.
    Deep project details should be uploaded separately via /api/upload-project.
    """
    try:
        resume_text = await _read_file_text(file)

        # LLM metadata extraction
        if llm_metadata_service:
            extracted_metadata = llm_metadata_service.extract_resume_metadata(resume_text)
        else:
            extracted_metadata = {}

        extracted_metadata["source"]        = file.filename
        extracted_metadata["document_type"] = "resume"

        # Optionally wipe the collection
        if replace_existing:
            qdrant_service.clear_collection()

        # Chunk + upsert
        processed = chunking_service.process_and_chunk(
            text=resume_text,
            source_metadata=extracted_metadata
        )
        qdrant_service.upsert_documents(
            documents=processed["documents"],
            metadatas=processed["metadatas"]
        )

        return {
            "message":            f"Resume '{file.filename}' processed and stored successfully.",
            "chunks_processed":   len(processed["documents"]),
            "extracted_metadata": extracted_metadata,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resume processing failed: {str(e)}")


# =====================================================================
# API 2  —  /api/upload-project
# =====================================================================

@app.post("/api/upload-project", response_model=UploadProjectResponse)
async def upload_project(
    file: UploadFile = File(...),
):
    """
    Upload a detailed project document (PDF, MD, or TXT) for ONE project.

    The document should describe the project in depth — the more detail you
    include, the better the chatbot can answer technical questions.

    Suggested sections to include in your file:
      - Overview / Purpose
      - Tech Stack (backend, frontend, database, infra, third-party)
      - Features
      - Architecture (flow + components)
      - Database Design
      - API Design
      - Core Logic
      - Edge Cases
      - Challenges & How They Were Solved
      - Optimizations
      - Deployment
      - Future Improvements

    Data is APPENDED to the existing vector database — it does NOT wipe your resume.
    You can call this endpoint multiple times for different projects.
    """
    try:
        project_text = await _read_file_text(file)

        # LLM deep extraction
        if project_ingest_service:
            project_data = project_ingest_service.extract_project_metadata(project_text)
        else:
            raise HTTPException(status_code=500, detail="Groq client not initialized.")

        if not project_data:
            raise HTTPException(
                status_code=422,
                detail="Could not extract project information from the file. "
                       "Ensure the document describes a project clearly."
            )

        project_data["source"]        = file.filename
        project_data["document_type"] = "project"

        # Chunk into 3 sub-chunks and APPEND (no wipe)
        processed = chunking_service.process_deep_project(
            project_data=project_data,
            source_filename=file.filename
        )
        qdrant_service.upsert_documents(
            documents=processed["documents"],
            metadatas=processed["metadatas"]
        )

        project_name = project_data.get("project_name") or "Unknown Project"
        return {
            "message":          f"Project '{project_name}' processed and stored successfully.",
            "project_name":     project_name,
            "chunks_processed": len(processed["documents"]),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project ingestion failed: {str(e)}")


# =====================================================================
# Chat endpoint
# =====================================================================

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    RAG-powered chat endpoint.
    Retrieves up to 6 relevant chunks from Qdrant (covering both resume and
    deep project data), injects them into the system prompt, and calls Groq.
    """
    if not groq_client:
        raise HTTPException(
            status_code=500,
            detail="Groq API client is not initialized. Ensure GROQ_API_KEY is set."
        )

    try:
        messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        last_user_message = next(
            (msg.content for msg in reversed(request.messages) if msg.role == "user"), None
        )

        system_prompt = SYSTEM_PROMPT

        if last_user_message:
            results = qdrant_service.search(query=last_user_message, limit=6)
            if results:
                context_texts = "\n---\n".join(
                    [f"Context [{i+1}]:\n{r['text']}" for i, r in enumerate(results)]
                )
                system_prompt += (
                    f"\n\nUse the following context from the candidate's documents to answer:\n\n{context_texts}"
                )

        # Inject / replace system prompt
        if messages_dict and messages_dict[0]["role"] == "system":
            messages_dict[0]["content"] = system_prompt
        else:
            messages_dict.insert(0, {"role": "system", "content": system_prompt})

        # Sliding window
        system_msg    = [m for m in messages_dict if m["role"] == "system"]
        non_system    = [m for m in messages_dict if m["role"] != "system"]
        trimmed_msgs  = system_msg + non_system[-MAX_HISTORY_MESSAGES:]

        chat_completion = groq_client.chat.completions.create(
            messages=trimmed_msgs,
            model=request.model,
            max_tokens=1024,
            temperature=0.5,
        )

        bot_response = chat_completion.choices[0].message.content
        return {"response": bot_response}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# General ingest (kept for backward compat)
# =====================================================================

@app.post("/api/ingest")
async def ingest_document(request: dict):
    """General-purpose text ingestion (legacy endpoint)."""
    try:
        text = request.get("text", "")
        metadata = request.get("metadata")
        processed = chunking_service.process_and_chunk(text=text, source_metadata=metadata)
        qdrant_service.upsert_documents(
            documents=processed["documents"],
            metadatas=processed["metadatas"]
        )
        return {"message": "Document ingested.", "chunks_processed": len(processed["documents"])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


# =====================================================================
# Health check
# =====================================================================

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Resume Chatbot API with Two-API RAG is running"}
