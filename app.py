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
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

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

def preprocess_text(text):
    """Clean and preprocess text for better search"""
    # Convert to lowercase
    text = text.lower()
    # Remove extra whitespace
    text = ' '.join(text.split())
    # Remove special characters but keep words
    text = re.sub(r'[^\w\s]', ' ', text)
    return text

def find_best_matches(question, chunks_data, top_k=3):
    """Use TF-IDF and cosine similarity to find best matches"""
    if not chunks_data:
        return []
    
    # Preprocess question
    processed_question = preprocess_text(question)
    
    # Prepare documents: question + all chunks
    documents = [processed_question]
    chunk_texts = []
    chunk_info = []
    
    for chunk_text, filename, chunk_id in chunks_data:
        processed_chunk = preprocess_text(chunk_text)
        documents.append(processed_chunk)
        chunk_texts.append(processed_chunk)
        chunk_info.append((chunk_text, filename, chunk_id))
    
    # Create TF-IDF matrix
    vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
    try:
        tfidf_matrix = vectorizer.fit_transform(documents)
    except:
        # Fallback if TF-IDF fails
        return chunks_data[:top_k]
    
    # Calculate similarity between question and all chunks
    question_vector = tfidf_matrix[0]
    chunk_vectors = tfidf_matrix[1:]
    
    similarities = cosine_similarity(question_vector, chunk_vectors).flatten()
    
    # Get top k matches
    top_indices = similarities.argsort()[-top_k:][::-1]
    
    best_matches = []
    for idx in top_indices:
        if similarities[idx] > 0.1:  # Similarity threshold
            best_matches.append(chunk_info[idx])
    
    return best_matches

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

def split_into_chunks(text, chunk_size=300):
    """Split text into smaller chunks for better search"""
    sentences = re.split(r'[.!?]+', text)
    chunks = []
    current_chunk = []
    current_length = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        sentence_length = len(sentence)
        if current_length + sentence_length <= chunk_size:
            current_chunk.append(sentence)
            current_length += sentence_length
        else:
            if current_chunk:
                chunks.append('. '.join(current_chunk) + '.')
            current_chunk = [sentence]
            current_length = sentence_length
    
    if current_chunk:
        chunks.append('. '.join(current_chunk) + '.')
    
    return chunks if chunks else [text]

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        question = data.get('question', '').strip()
        
        if not question:
            return jsonify({'error': 'No question provided'}), 400
        
        conn = sqlite3.connect('knowledge_base.db')
        c = conn.cursor()
        
        # Get all chunks with their document info
        c.execute('''
            SELECT dc.chunk_text, d.filename, dc.id
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
        ''')
        
        all_chunks = c.fetchall()
        conn.close()
        
        if all_chunks:
            # Use improved search with TF-IDF
            best_matches = find_best_matches(question, all_chunks, top_k=3)
            
            if best_matches:
                # Combine best matches
                answer_parts = []
                sources = set()
                
                for chunk_text, filename, chunk_id in best_matches:
                    answer_parts.append(chunk_text)
                    sources.add(filename)
                
                answer = "\n\n".join(answer_parts)
                response = {
                    'answer': answer,
                    'sources': list(sources),
                    'found_in_kb': True
                }
            else:
                response = {
                    'answer': "I've reviewed my knowledge base but couldn't find specific information about that topic. The documents I have don't seem to contain details matching your question. You might want to upload more specific documents or try rephrasing your question.",
                    'sources': [],
                    'found_in_kb': False
                }
        else:
            response = {
                'answer': "I couldn't find information about that in my knowledge base. Please upload relevant documents to help me learn about this topic.",
                'sources': [],
                'found_in_kb': False
            }
        
        return jsonify(response)
    
    except Exception as e:
        print(f"Error in chat: {str(e)}")
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

@app.route('/search-debug', methods=['POST'])
def search_debug():
    """Debug endpoint to see what's in the database"""
    data = request.json
    question = data.get('question', '')
    
    conn = sqlite3.connect('knowledge_base.db')
    c = conn.cursor()
    
    # Get all chunks
    c.execute('''
        SELECT dc.chunk_text, d.filename 
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        LIMIT 5
    ''')
    
    sample_chunks = c.fetchall()
    
    # Simple search
    c.execute('''
        SELECT chunk_text, filename 
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE chunk_text LIKE ? 
        LIMIT 3
    ''', (f'%{question}%',))
    
    simple_results = c.fetchall()
    conn.close()
    
    return jsonify({
        'sample_chunks': sample_chunks,
        'simple_search_results': simple_results,
        'question': question
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
