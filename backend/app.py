import os
from typing import List, Dict
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables (e.g., GROQ_API_KEY)
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Groq Chatbot API")

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Groq client
# Make sure to set GROQ_API_KEY in your .env file
try:
    api_key = os.environ.get("GROQ_API_KEY")
    # if not api_key: print warning, Groq() will fail if it's missing entirely and we don't pass it or it's not in env directly
    groq_client = Groq(api_key=api_key)
except Exception as e:
    print(f"Warning: Failed to initialize Groq client: {e}")
    groq_client = None

# Pydantic models for request validation
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    model: str = os.environ.get("MODEL") # Default Groq model, can be overridden by frontend

class ChatResponse(BaseModel):
    response: str

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
    return {"status": "ok", "message": "Groq Chatbot API is running"}
