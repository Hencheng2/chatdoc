#!/usr/bin/env python3
import os
import sqlite3
import uuid
from datetime import datetime
from typing import List, Dict, Any
import hashlib
import json
import io
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
import PyPDF2
from docx import Document

# Initialize the application
app = FastAPI(title="SolAI")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Password for upload access
UPLOAD_PASSWORD = "Henley@2003"

# Initialize components
class KnowledgeBase:
    def __init__(self):
        self.init_database()
        self.documents = []
        self.document_metadata = []
        self.vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
        self.tfidf_matrix = None
        self.load_existing_documents()
    
    def init_database(self):
        """Initialize SQLite database for metadata"""
        conn = sqlite3.connect('knowledge_chatbot.db')
        cursor = conn.cursor()
        
        # Documents table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                content_text TEXT NOT NULL,
                upload_date TEXT NOT NULL,
                chunk_count INTEGER DEFAULT 0
            )
        ''')
        
        # Chat history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources TEXT,
                timestamp TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def load_existing_documents(self):
        """Load existing documents from database"""
        conn = sqlite3.connect('knowledge_chatbot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM documents')
        documents = cursor.fetchall()
        conn.close()
        
        self.documents = []
        self.document_metadata = []
        
        for doc in documents:
            doc_id, filename, file_type, file_size, content_hash, content_text, upload_date, chunk_count = doc
            # Split content into chunks if it's large
            chunks = self.chunk_text(content_text)
            for i, chunk in enumerate(chunks):
                self.documents.append(chunk)
                self.document_metadata.append({
                    "file_id": doc_id,
                    "filename": filename,
                    "chunk_index": i,
                    "content_hash": content_hash
                })
        
        # Update TF-IDF matrix if we have documents
        if self.documents:
            self.tfidf_matrix = self.vectorizer.fit_transform(self.documents)
    
    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """Split text into overlapping chunks"""
        words = text.split()
        if not words:
            return []
            
        chunks = []
        
        for i in range(0, len(words), chunk_size - overlap):
            chunk = words[i:i + chunk_size]
            if chunk:
                chunks.append(" ".join(chunk))
            
            if i + chunk_size >= len(words):
                break
                
        return chunks if chunks else [text]
    
    async def process_file(self, file_content: bytes, filename: str) -> str:
        """Process different file types and extract text"""
        file_extension = filename.split('.')[-1].lower()
        
        try:
            if file_extension in ['txt', 'md', 'csv', 'json']:
                try:
                    return file_content.decode('utf-8')
                except:
                    return file_content.decode('latin-1')
            
            elif file_extension == 'pdf':
                text = ""
                pdf_file = io.BytesIO(file_content)
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                return text
            
            elif file_extension in ['docx', 'doc']:
                doc_file = io.BytesIO(file_content)
                doc = Document(doc_file)
                text = ""
                for paragraph in doc.paragraphs:
                    if paragraph.text:
                        text += paragraph.text + "\n"
                return text
            
            else:
                try:
                    return file_content.decode('utf-8')
                except:
                    return file_content.decode('latin-1')
                    
        except Exception as e:
            return f"Error processing file {filename}: {str(e)}"
    
    def add_document_to_knowledge(self, file_id: str, filename: str, text_content: str) -> bool:
        """Add document content to knowledge base"""
        if not text_content or len(text_content.strip()) == 0:
            return False
            
        # Generate content hash to avoid duplicates
        content_hash = hashlib.md5(text_content.encode()).hexdigest()
        
        # Check if content already exists
        conn = sqlite3.connect('knowledge_chatbot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM documents WHERE content_hash = ?', (content_hash,))
        existing = cursor.fetchone()
        
        if existing:
            conn.close()
            return False
        
        # Split into chunks
        chunks = self.chunk_text(text_content)
        
        if not chunks:
            conn.close()
            return False
        
        # Save to database
        cursor.execute('''
            INSERT INTO documents (id, filename, file_type, file_size, content_hash, content_text, upload_date, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            file_id, 
            filename, 
            filename.split('.')[-1].lower(),
            len(text_content.encode('utf-8')),
            content_hash,
            text_content,
            datetime.now().isoformat(),
            len(chunks)
        ))
        
        conn.commit()
        conn.close()
        
        # Add to in-memory storage for TF-IDF
        for i, chunk in enumerate(chunks):
            self.documents.append(chunk)
            self.document_metadata.append({
                "file_id": file_id,
                "filename": filename,
                "chunk_index": i,
                "content_hash": content_hash
            })
        
        # Update TF-IDF matrix
        if self.documents:
            self.tfidf_matrix = self.vectorizer.fit_transform(self.documents)
        
        return True
    
    def search_similar_content(self, query: str, n_results: int = 3) -> Dict[str, Any]:
        """Search for similar content using TF-IDF and cosine similarity"""
        if not self.documents or self.tfidf_matrix is None:
            return {'documents': [], 'metadatas': [], 'scores': []}
        
        try:
            # Transform query to TF-IDF
            query_vec = self.vectorizer.transform([query])
            
            # Calculate cosine similarities
            similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
            
            # Get top N results
            top_indices = similarities.argsort()[-n_results:][::-1]
            
            results = {
                'documents': [self.documents[i] for i in top_indices],
                'metadatas': [self.document_metadata[i] for i in top_indices],
                'scores': [float(similarities[i]) for i in top_indices]
            }
            
            return results
        except Exception as e:
            print(f"Search error: {e}")
            return {'documents': [], 'metadatas': [], 'scores': []}
    
    def generate_answer(self, question: str, context: str) -> str:
        """Generate answer based on question and context"""
        if not context or "no relevant" in context.lower() or "error" in context.lower():
            return "I don't have enough information in my knowledge base to answer this question accurately. Please upload relevant documents first."
        
        context_lines = context.split('\n')
        if len(context_lines) > 3:
            context_preview = '\n'.join(context_lines[:3]) + "\n..."
        else:
            context_preview = context
            
        return f"""Based on your documents:

{context_preview}

I found this information relevant to your question. The system searches through your uploaded documents using semantic similarity to find the most relevant content."""
    
    def save_chat_message(self, session_id: str, question: str, answer: str, sources: List[Dict] = None):
        """Save chat message to database"""
        chat_id = str(uuid.uuid4())
        
        conn = sqlite3.connect('knowledge_chatbot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO chat_history (id, session_id, question, answer, sources, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            chat_id,
            session_id,
            question,
            answer,
            json.dumps(sources) if sources else None,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()

# Global knowledge base instance
kb = KnowledgeBase()

@app.get("/")
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), password: str = Form(...)):
    try:
        # Verify password
        if password != UPLOAD_PASSWORD:
            raise HTTPException(status_code=403, detail="Invalid upload password")
        
        # Generate unique file ID
        file_id = str(uuid.uuid4())
        
        # Read file content
        content = await file.read()
        
        # Process file
        text_content = await kb.process_file(content, file.filename)
        
        # Add to knowledge base
        success = kb.add_document_to_knowledge(file_id, file.filename, text_content)
        
        if success:
            return {"message": f"File '{file.filename}' uploaded and processed successfully", "file_id": file_id}
        else:
            return {"message": f"File '{file.filename}' was already in the knowledge base", "file_id": file_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@app.post("/chat")
async def chat(question: dict):
    try:
        user_question = question.get("question", "")
        session_id = question.get("session_id", "default")
        
        if not user_question:
            raise HTTPException(status_code=400, detail="Question is required")
        
        # Search for similar content
        search_results = kb.search_similar_content(user_question)
        
        # Build context
        context = "\n\n".join(search_results['documents']) if search_results['documents'] else ""
        
        # Generate answer
        answer = kb.generate_answer(user_question, context)
        
        # Save to chat history
        kb.save_chat_message(session_id, user_question, answer, search_results['metadatas'])
        
        return {
            "question": user_question,
            "answer": answer,
            "sources": search_results['metadatas']
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")

@app.get("/documents")
async def get_documents():
    conn = sqlite3.connect('knowledge_chatbot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM documents ORDER BY upload_date DESC')
    documents = cursor.fetchall()
    conn.close()
    
    return {
        "documents": [
            {
                "id": doc[0],
                "filename": doc[1],
                "file_type": doc[2],
                "file_size": doc[3],
                "upload_date": doc[6],
                "chunk_count": doc[7]
            }
            for doc in documents
        ]
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    print("🚀 Starting SolAI...")
    print("📚 Access the application at: http://localhost:8000")
    print("🔒 Upload access hidden behind 'S' in SolAI")
    print("🔑 Password required for uploads")
    print("⏹️  Press Ctrl+C to stop the server\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
