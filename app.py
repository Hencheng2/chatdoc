import os
import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from PyPDF2 import PdfReader
import docx
import pandas as pd

app = Flask(__name__, static_folder="static")
CORS(app)

DB_FILE = "database.db"
ADMIN_PASSWORD = "Hemley@2003"

# ---------- DATABASE ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    content TEXT,
                    filename TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

def add_document(title, content, filename=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO documents (title, content, filename) VALUES (?, ?, ?)",
              (title, content, filename))
    conn.commit()
    conn.close()

def search_documents(query):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, title, content, filename FROM documents "
              "WHERE content LIKE ? OR title LIKE ? "
              "ORDER BY added_at DESC LIMIT 5",
              (f"%{query}%", f"%{query}%"))
    results = c.fetchall()
    conn.close()
    return results

# ---------- FILE PARSERS ----------
def extract_text_from_pdf(path):
    text = ""
    try:
        reader = PdfReader(path)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    except Exception as e:
        print("PDF error:", e)
    return text.strip()

def extract_text_from_docx(path):
    text = ""
    try:
        doc = docx.Document(path)
        text = "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print("DOCX error:", e)
    return text.strip()

def extract_text_from_csv(path):
    try:
        df = pd.read_csv(path)
        return df.to_string()
    except Exception as e:
        print("CSV error:", e)
        return ""

def extract_text_from_xlsx(path):
    try:
        df = pd.read_excel(path)
        return df.to_string()
    except Exception as e:
        print("XLSX error:", e)
        return ""

# ---------- API ROUTES ----------
@app.route("/")
def home():
    return send_from_directory(app.static_folder, "client.html")

@app.route("/api/upload", methods=["POST"])
def upload_file():
    pw = request.form.get("password")
    if pw != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Unauthorized"})
    
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file part"})
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"success": False, "error": "No selected file"})

    os.makedirs("uploads", exist_ok=True)
    path = os.path.join("uploads", f.filename)
    f.save(path)

    ext = f.filename.lower().split(".")[-1]
    text = ""
    if ext == "pdf":
        text = extract_text_from_pdf(path)
    elif ext == "docx":
        text = extract_text_from_docx(path)
    elif ext == "csv":
        text = extract_text_from_csv(path)
    elif ext in ["xls", "xlsx"]:
        text = extract_text_from_xlsx(path)
    else:
        with open(path, "r", errors="ignore") as fp:
            text = fp.read()

    if text:
        add_document(f.filename, text, f.filename)
        return jsonify({"success": True, "filename": f.filename})
    return jsonify({"success": False, "error": "Unsupported or empty file"})

@app.route("/api/add_text", methods=["POST"])
def add_text():
    data = request.json
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Unauthorized"})

    title = data.get("title") or "Untitled"
    content = data.get("content", "")
    if not content.strip():
        return jsonify({"success": False, "error": "No content"})
    add_document(title, content)
    return jsonify({"success": True})

@app.route("/api/chat", methods=["POST"])
def chat():
    q = request.json.get("question", "")
    if not q.strip():
        return jsonify({"success": False, "error": "Empty question"})
    matches = search_documents(q)
    if not matches:
        return jsonify({"success": True, "answer": "No matching information found in database."})
    ans = "\n---\n".join([f"[{m[1] or m[3]}]\n{m[2][:500]}..." for m in matches])
    return jsonify({"success": True, "answer": ans})

@app.route("/api/docs", methods=["GET"])
def list_docs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, title, filename, added_at FROM documents ORDER BY added_at DESC")
    docs = [{"id": row[0], "title": row[1], "filename": row[2], "added_at": row[3]} for row in c.fetchall()]
    conn.close()
    return jsonify({"success": True, "docs": docs})

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
