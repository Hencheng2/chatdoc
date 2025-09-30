from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import sqlite3
import os
import json
import hashlib
import uuid
from datetime import datetime
import chromadb
from chromadb.config import Settings
from werkzeug.utils import secure_filename
import PyPDF2
import docx
import csv

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
CORS(app)

# Database setup
def init_db():
    conn = sqlite3.connect('knowledge_chatbot.db')
    cursor = conn.cursor()
    
    # Documents table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_size INTEGER,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            content TEXT
        )
    ''')
    
    # Chat sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Chat messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            message TEXT NOT NULL,
            is_user BOOLEAN NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize ChromaDB
def init_chroma():
    chroma_client = chromadb.PersistentClient(path="chroma_db")
    collection = chroma_client.get_or_create_collection(
        name="documents",
        metadata={"description": "Document embeddings for chatbot"}
    )
    return chroma_client, collection

# Initialize databases
init_db()
chroma_client, chroma_collection = init_chroma()

# Password verification
def verify_password(password):
    return hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256("HenLey@2003".encode()).hexdigest()

# File processing functions
def extract_text_from_pdf(file_path):
    text = ""
    with open(file_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text

def extract_text_from_docx(file_path):
    doc = docx.Document(file_path)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    return text

def extract_text_from_csv(file_path):
    text = ""
    with open(file_path, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            text += ", ".join(row) + "\n"
    return text

def extract_text_from_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
        return json.dumps(data, indent=2)

def process_uploaded_file(file):
    filename = secure_filename(file.filename)
    file_extension = filename.split('.')[-1].lower()
    
    # Save uploaded file temporarily
    temp_path = f"temp_{uuid.uuid4().hex}_{filename}"
    file.save(temp_path)
    
    try:
        # Extract text based on file type
        if file_extension == 'pdf':
            content = extract_text_from_pdf(temp_path)
        elif file_extension == 'docx':
            content = extract_text_from_docx(temp_path)
        elif file_extension == 'csv':
            content = extract_text_from_csv(temp_path)
        elif file_extension == 'json':
            content = extract_text_from_json(temp_path)
        elif file_extension == 'txt':
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            content = f"Unsupported file type: {file_extension}"
        
        # Store in SQLite
        conn = sqlite3.connect('knowledge_chatbot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO documents (filename, file_type, file_size, content)
            VALUES (?, ?, ?, ?)
        ''', (filename, file_extension, len(content), content))
        doc_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Store in ChromaDB
        chroma_collection.add(
            documents=[content],
            metadatas=[{"filename": filename, "file_type": file_extension, "doc_id": doc_id}],
            ids=[str(doc_id)]
        )
        
        return {"success": True, "message": f"File '{filename}' uploaded successfully"}
    
    except Exception as e:
        return {"success": False, "message": f"Error processing file: {str(e)}"}
    
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)

# Routes
@app.route('/')
def serve_frontend():
    return send_from_directory('.', 'index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if verify_password(data.get('password', '')):
        session['admin'] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Invalid password"})

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('admin', None)
    return jsonify({"success": True})

@app.route('/check_admin')
def check_admin():
    return jsonify({"is_admin": session.get('admin', False)})

@app.route('/upload', methods=['POST'])
def upload_file():
    if not session.get('admin'):
        return jsonify({"success": False, "message": "Unauthorized"})
    
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file provided"})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "No file selected"})
    
    result = process_uploaded_file(file)
    return jsonify(result)

@app.route('/documents')
def get_documents():
    if not session.get('admin'):
        return jsonify({"success": False, "message": "Unauthorized"})
    
    conn = sqlite3.connect('knowledge_chatbot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, filename, file_type, file_size, upload_date FROM documents ORDER BY upload_date DESC')
    documents = cursor.fetchall()
    conn.close()
    
    docs_list = []
    for doc in documents:
        docs_list.append({
            'id': doc[0],
            'filename': doc[1],
            'file_type': doc[2],
            'file_size': doc[3],
            'upload_date': doc[4]
        })
    
    return jsonify({"success": True, "documents": docs_list})

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message', '')
    session_id = data.get('session_id', 'default')
    
    if not message.strip():
        return jsonify({"success": False, "message": "Empty message"})
    
    # Search in ChromaDB for relevant content
    try:
        results = chroma_collection.query(
            query_texts=[message],
            n_results=3
        )
        
        relevant_content = ""
        if results['documents']:
            for doc in results['documents'][0]:
                relevant_content += doc + "\n\n"
        
        # Generate response based on relevant content
        if relevant_content.strip():
            response = f"I found this information in your documents:\n\n{relevant_content.strip()}"
        else:
            response = "I couldn't find relevant information in your uploaded documents. Please upload relevant documents or ask something else."
    
    except Exception as e:
        response = f"Error searching documents: {str(e)}"
    
    # Store chat messages
    conn = sqlite3.connect('knowledge_chatbot.db')
    cursor = conn.cursor()
    
    # Ensure session exists
    cursor.execute('INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)', (session_id,))
    
    # Store user message
    cursor.execute('''
        INSERT INTO chat_messages (session_id, message, is_user)
        VALUES (?, ?, ?)
    ''', (session_id, message, True))
    
    # Store bot response
    cursor.execute('''
        INSERT INTO chat_messages (session_id, message, is_user)
        VALUES (?, ?, ?)
    ''', (session_id, response, False))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "response": response})

@app.route('/chat_history/<session_id>')
def get_chat_history(session_id):
    conn = sqlite3.connect('knowledge_chatbot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT message, is_user, timestamp 
        FROM chat_messages 
        WHERE session_id = ? 
        ORDER BY timestamp ASC
    ''', (session_id,))
    messages = cursor.fetchall()
    conn.close()
    
    messages_list = []
    for msg in messages:
        messages_list.append({
            'message': msg[0],
            'is_user': bool(msg[1]),
            'timestamp': msg[2]
        })
    
    return jsonify({"success": True, "messages": messages_list})

@app.route('/sessions')
def get_sessions():
    conn = sqlite3.connect('knowledge_chatbot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT session_id, created_date FROM chat_sessions ORDER BY created_date DESC')
    sessions = cursor.fetchall()
    conn.close()
    
    sessions_list = []
    for sess in sessions:
        sessions_list.append({
            'session_id': sess[0],
            'created_date': sess[1]
        })
    
    return jsonify({"success": True, "sessions": sessions_list})

if __name__ == '__main__':
    # Create necessary directories
    if not os.path.exists('chroma_db'):
        os.makedirs('chroma_db')
    
    app.run(debug=True, host='0.0.0.0', port=5000)
