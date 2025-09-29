import flask
from flask import Flask, request, jsonify, session
import sqlite3
import chromadb
from sentence_transformers import SentenceTransformer
import os
from datetime import datetime
import PyPDF2
from docx import Document as DocxDocument
import csv
import json

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_me'
PASSWORD = "HenLey@2003"
DB_FILE = "knowledge_chatbot.db"
CHROMA_PATH = "chroma_db"
model = SentenceTransformer('all-MiniLM-L6-v2')
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="documents")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS documents
                 (id INTEGER PRIMARY KEY, name TEXT, upload_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_sessions
                 (session_id TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

def parse_document(file_path, file_type):
    text = ""
    if file_type == 'txt':
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
    elif file_type == 'pdf':
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
    elif file_type == 'docx':
        doc = DocxDocument(file_path)
        for para in doc.paragraphs:
            text += para.text + '\n'
    elif file_type == 'csv':
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                text += ','.join(row) + '\n'
    elif file_type == 'json':
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            text = json.dumps(data, ensure_ascii=False)
    return text

def chunk_text(text, chunk_size=500):
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks

@app.route('/')
def index():
    return jsonify({'message': 'Welcome to the Knowledge Chatbot API'})

@app.route('/admin_login', methods=['POST'])
def admin_login():
    password = request.form['password']
    if password == PASSWORD:
        session['admin'] = True
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Invalid password'}), 403

@app.route('/upload', methods=['POST'])
def upload():
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    filename = file.filename
    file_type = filename.split('.')[-1].lower()
    if file_type not in ['txt', 'pdf', 'docx', 'csv', 'json']:
        return jsonify({'error': 'Unsupported file type'}), 400
    temp_path = f"temp_{filename}"
    file.save(temp_path)
    text = parse_document(temp_path, file_type)
    chunks = chunk_text(text)
    if chunks:
        embeddings = model.encode(chunks)
        ids = [f"{filename}_{i}" for i in range(len(chunks))]
        metadatas = [{"filename": filename} for _ in chunks]
        collection.add(
            documents=chunks,
            embeddings=embeddings.tolist(),
            ids=ids,
            metadatas=metadatas
        )
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO documents (name, upload_date) VALUES (?, ?)",
              (filename, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    os.remove(temp_path)
    return jsonify({'success': True})

@app.route('/documents', methods=['GET'])
def get_documents():
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, name, upload_date FROM documents")
    docs = c.fetchall()
    conn.close()
    return jsonify([{'id': d[0], 'name': d[1], 'date': d[2]} for d in docs])

@app.route('/new_session', methods=['POST'])
def new_session():
    session_id = os.urandom(16).hex()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO chat_sessions (session_id) VALUES (?)", (session_id,))
    conn.commit()
    conn.close()
    return jsonify({'session_id': session_id})

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    session_id = data.get('session_id')
    query = data.get('query')
    if not session_id or not query:
        return jsonify({'error': 'Missing parameters'}), 400
    save_message(session_id, 'user', query)
    query_emb = model.encode(query).tolist()
    results = collection.query(
        query_embeddings=[query_emb],
        n_results=5
    )
    relevant_docs = results['documents'][0]
    if not relevant_docs:
        response = "Sorry, no matching information found in the database."
    else:
        response = "Relevant information found:\n\n" + "\n\n".join(relevant_docs)
    save_message(session_id, 'bot', response)
    return jsonify({'response': response})

def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
              (session_id, role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()

@app.route('/history', methods=['GET'])
def get_history():
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({'error': 'Missing session_id'}), 400
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY id ASC",
              (session_id,))
    msgs = c.fetchall()
    conn.close()
    return jsonify([{'role': m[0], 'content': m[1], 'time': m[2]} for m in msgs])

if __name__ == '__main__':
    app.run(debug=True)
