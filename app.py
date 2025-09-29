# app.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
import uuid
from datetime import datetime
import PyPDF2
import docx
import chardet

app = Flask(__name__)
CORS(app)

# Database initialization
def init_db():
    conn = sqlite3.connect('knowledge_base.db')
    c = conn.cursor()
    
    # Create documents table
    c.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT,
            content_type TEXT,
            content TEXT,
            uploaded_at TIMESTAMP
        )
    ''')
    
    # Create chunks table for better search
    c.execute('''
        CREATE TABLE IF NOT EXISTS document_chunks (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            chunk_text TEXT,
            chunk_index INTEGER,
            FOREIGN KEY (document_id) REFERENCES documents (id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def extract_text_from_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

def extract_text_from_docx(file):
    doc = docx.Document(file)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    return text

def extract_text_from_txt(file):
    raw_data = file.read()
    encoding = chardet.detect(raw_data)['encoding']
    return raw_data.decode(encoding)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_document():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Extract text based on file type
        filename = file.filename.lower()
        file_content = ""
        
        if filename.endswith('.pdf'):
            file_content = extract_text_from_pdf(file)
        elif filename.endswith('.docx'):
            file_content = extract_text_from_docx(file)
        elif filename.endswith('.txt'):
            file_content = extract_text_from_txt(file)
        else:
            return jsonify({'error': 'Unsupported file type'}), 400
        
        # Store in database
        doc_id = str(uuid.uuid4())
        conn = sqlite3.connect('knowledge_base.db')
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO documents (id, filename, content_type, content, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (doc_id, file.filename, file.content_type, file_content, datetime.now()))
        
        # Split content into chunks for better search
        chunks = split_into_chunks(file_content)
        for i, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            c.execute('''
                INSERT INTO document_chunks (id, document_id, chunk_text, chunk_index)
                VALUES (?, ?, ?, ?)
            ''', (chunk_id, doc_id, chunk, i))
        
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'File uploaded successfully', 'doc_id': doc_id})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def split_into_chunks(text, chunk_size=500):
    words = text.split()
    chunks = []
    current_chunk = []
    current_size = 0
    
    for word in words:
        current_chunk.append(word)
        current_size += len(word) + 1
        
        if current_size >= chunk_size:
            chunks.append(' '.join(current_chunk))
            current_chunk = []
            current_size = 0
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        question = data.get('question', '').strip().lower()
        
        if not question:
            return jsonify({'error': 'No question provided'}), 400
        
        conn = sqlite3.connect('knowledge_base.db')
        c = conn.cursor()
        
        # Search in document chunks
        c.execute('''
            SELECT chunk_text, filename 
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE chunk_text LIKE ? 
            ORDER BY dc.chunk_index
        ''', (f'%{question}%',))
        
        results = c.fetchall()
        conn.close()
        
        if results:
            # Combine relevant chunks
            answer_parts = []
            sources = set()
            for chunk, filename in results:
                answer_parts.append(chunk)
                sources.add(filename)
            
            answer = " ".join(answer_parts[:3])  # Limit response length
            response = {
                'answer': answer,
                'sources': list(sources),
                'found_in_kb': True
            }
        else:
            response = {
                'answer': "I couldn't find information about that in my knowledge base. Please upload relevant documents to help me learn about this topic.",
                'sources': [],
                'found_in_kb': False
            }
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/documents', methods=['GET'])
def get_documents():
    conn = sqlite3.connect('knowledge_base.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT id, filename, uploaded_at 
        FROM documents 
        ORDER BY uploaded_at DESC
    ''')
    
    documents = c.fetchall()
    conn.close()
    
    docs_list = []
    for doc in documents:
        docs_list.append({
            'id': doc[0],
            'filename': doc[1],
            'uploaded_at': doc[2]
        })
    
    return jsonify(docs_list)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
