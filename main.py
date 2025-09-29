from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sqlite3
import os
import uuid
from datetime import datetime
import aiofiles
from typing import List, Optional
import chromadb
from sentence_transformers import SentenceTransformer
import PyPDF2
from docx import Document
import json

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
model = SentenceTransformer('all-MiniLM-L6-v2')
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="documents")

# Database setup
def init_db():
    conn = sqlite3.connect('chatbot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            upload_date TEXT NOT NULL,
            processed BOOLEAN DEFAULT FALSE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            source_documents TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# File processing functions
async def process_text_file(file_path: str) -> str:
    async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
        return await f.read()

async def process_pdf_file(file_path: str) -> str:
    text = ""
    with open(file_path, 'rb') as f:
        pdf_reader = PyPDF2.PdfReader(f)
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
    return text

async def process_docx_file(file_path: str) -> str:
    doc = Document(file_path)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    return text

# API Routes
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Generate unique ID
        file_id = str(uuid.uuid4())
        file_path = f"uploads/{file_id}_{file.filename}"
        
        # Create uploads directory if not exists
        os.makedirs("uploads", exist_ok=True)
        
        # Save file
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        # Process file based on type
        file_extension = file.filename.split('.')[-1].lower()
        text_content = ""
        
        if file_extension in ['txt', 'md']:
            text_content = await process_text_file(file_path)
        elif file_extension == 'pdf':
            text_content = await process_pdf_file(file_path)
        elif file_extension in ['docx', 'doc']:
            text_content = await process_docx_file(file_path)
        else:
            # For other file types, try to read as text
            try:
                text_content = await process_text_file(file_path)
            except:
                text_content = f"File content could not be extracted: {file.filename}"
        
        # Split content into chunks and add to vector database
        chunks = chunk_text(text_content, chunk_size=500)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_id}_{i}"
            embedding = model.encode(chunk).tolist()
            collection.add(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{
                    "file_id": file_id,
                    "filename": file.filename,
                    "chunk_index": i
                }]
            )
        
        # Save to SQLite
        conn = sqlite3.connect('chatbot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO documents (id, filename, content_type, file_size, upload_date, processed)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (file_id, file.filename, file.content_type, len(content), datetime.now().isoformat(), True))
        conn.commit()
        conn.close()
        
        return {"message": "File uploaded and processed successfully", "file_id": file_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@app.post("/chat")
async def chat(question: str):
    try:
        # Generate embedding for question
        question_embedding = model.encode(question).tolist()
        
        # Search for similar content
        results = collection.query(
            query_embeddings=[question_embedding],
            n_results=3
        )
        
        # Build context from retrieved documents
        context = "\n\n".join(results['documents'][0]) if results['documents'] else "No relevant documents found."
        
        # Generate answer (simplified - you can integrate with OpenAI API here)
        answer = generate_answer(question, context)
        
        # Save to chat history
        chat_id = str(uuid.uuid4())
        conn = sqlite3.connect('chatbot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO chat_history (id, question, answer, timestamp, source_documents)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, question, answer, datetime.now().isoformat(), json.dumps(results['metadatas'][0])))
        conn.commit()
        conn.close()
        
        return {
            "question": question,
            "answer": answer,
            "sources": results['metadatas'][0] if results['metadatas'] else []
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")

@app.get("/documents")
async def get_documents():
    conn = sqlite3.connect('chatbot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM documents ORDER BY upload_date DESC')
    documents = cursor.fetchall()
    conn.close()
    
    return {
        "documents": [
            {
                "id": doc[0],
                "filename": doc[1],
                "content_type": doc[2],
                "file_size": doc[3],
                "upload_date": doc[4],
                "processed": bool(doc[5])
            }
            for doc in documents
        ]
    }

@app.get("/chat-history")
async def get_chat_history():
    conn = sqlite3.connect('chatbot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM chat_history ORDER BY timestamp DESC LIMIT 50')
    chats = cursor.fetchall()
    conn.close()
    
    return {
        "chat_history": [
            {
                "id": chat[0],
                "question": chat[1],
                "answer": chat[2],
                "timestamp": chat[3],
                "sources": json.loads(chat[4]) if chat[4] else []
            }
            for chat in chats
        ]
    }

def chunk_text(text: str, chunk_size: int = 500) -> List[str]:
    """Split text into chunks of specified size"""
    words = text.split()
    chunks = []
    current_chunk = []
    current_size = 0
    
    for word in words:
        if current_size + len(word) + 1 > chunk_size:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_size = len(word)
        else:
            current_chunk.append(word)
            current_size += len(word) + 1
    
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    return chunks

def generate_answer(question: str, context: str) -> str:
    """Generate answer based on question and context"""
    # This is a simplified version. You can integrate with OpenAI GPT or other LLMs here
    if "no relevant documents" in context.lower():
        return "I don't have enough information in my knowledge base to answer this question accurately. Please upload relevant documents first."
    
    prompt = f"""Based on the following context, please answer the question. If the context doesn't contain enough information, say so.

Context: {context}

Question: {question}

Answer:"""
    
    # For production, replace this with actual LLM call
    # For now, return a simple response
    return f"Based on the documents I've analyzed: {context[:200]}... [This is a simplified response. Integrate with an LLM for better answers.]"

# Serve frontend
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
