import os
import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from PyPDF2 import PdfReader
import docx
import csv
import openpyxl

# ----------------------
# Config
# ----------------------
DB_FILE = "database.db"
UPLOAD_DIR = "uploads"
ADMIN_PASSWORD = "Hemley@2003"

# ----------------------
# App
# ----------------------
app = Flask(__name__, static_folder="static")
CORS(app)

# ----------------------
# Database Helpers
# ----------------------
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            filename TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_document(title, content, filename=None):
    init_db()  # ensure table exists
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO documents (title, content, filename) VALUES (?, ?, ?)",
              (title, content, filename))
    conn.commit()
    conn.close()

def search_documents(query):
    init_db()  # ensure table exists
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT title, content FROM documents WHERE content LIKE ?", (f"%{query}%",))
    results = c.fetchall()
    conn.close()
    return results

# ----------------------
# File Parsing
# ----------------------
def extract_text_from_file(filepath):
    text = ""
    if filepath.lower().endswith(".txt"):
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    elif filepath.lower().endswith(".pdf"):
        try:
            reader = PdfReader(filepath)
            for page in reader.pages:
                text += page.extract_text() or ""
        except Exception as e:
            print("PDF parse error:", e)
    elif filepath.lower().endswith(".docx"):
        try:
            doc = docx.Document(filepath)
            text = "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            print("DOCX parse error:", e)
    elif filepath.lower().endswith(".csv"):
        try:
            with open(filepath, newline="", encoding="utf-8", errors="ignore") as f:
                rows = list(csv.reader(f))
                text = "\n".join([", ".join(row) for row in rows])
        except Exception as e:
            print("CSV parse error:", e)
    elif filepath.lower().endswith(".xlsx"):
        try:
            wb = openpyxl.load_workbook(filepath, data_only=True)
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    line = " ".join([str(cell) for cell in row if cell is not None])
                    if line.strip():
                        text += line + "\n"
        except Exception as e:
            print("XLSX parse error:", e)
    return text.strip()

# ----------------------
# Routes
# ----------------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    query = request.json.get("message", "").strip()
    if not query:
        return jsonify({"response": "Please ask something."})
    results = search_documents(query)
    if results:
        snippets = [f"📄 {r['title']}: {r['content'][:200]}..." for r in results[:3]]
        return jsonify({"response": "\n\n".join(snippets)})
    return jsonify({"response": "I couldn’t find anything about that in my knowledge base."})

@app.route("/api/upload", methods=["POST"])
def upload():
    password = request.form.get("password")
    if password != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Unauthorized"})
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file"})
    f = request.files["file"]
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filepath = os.path.join(UPLOAD_DIR, f.filename)
    f.save(filepath)
    text = extract_text_from_file(filepath)
    if not text:
        return jsonify({"success": False, "error": "Unsupported or empty file"})
    add_document(f.filename, text, f.filename)
    return jsonify({"success": True, "filename": f.filename})

@app.route("/api/add_text", methods=["POST"])
def add_text():
    data = request.json
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Unauthorized"})
    title = data.get("title") or "Untitled"
    content = data.get("content", "")
    if not content.strip():
        return jsonify({"success": False, "error": "Empty content"})
    add_document(title, content)
    return jsonify({"success": True, "title": title})

# ----------------------
# Run
# ----------------------
if __name__ == "__main__":
    init_db()  # ensure DB + table exist at startup
    app.run(debug=True)
