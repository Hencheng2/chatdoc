from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3, os
from PyPDF2 import PdfReader

DB_FILE = "database.db"
UPLOAD_FOLDER = "uploads"
ADMIN_PASSWORD = "Hemley@2003"

app = Flask(__name__, static_folder="static")
CORS(app)

# -------------------- DB Setup --------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
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

init_db()

def get_conn():
    return sqlite3.connect(DB_FILE)

def add_document(title, content, filename=None):
    conn = get_conn()
    c = conn.cursor()
    print(f"[DB] Saving: {title} ({len(content)} chars)")
    c.execute("INSERT INTO documents (title, content, filename) VALUES (?, ?, ?)",
              (title, content, filename))
    conn.commit()
    conn.close()

def search_documents(query):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT title, content FROM documents WHERE lower(content) LIKE ?", 
              (f"%{query.lower()}%",))
    results = c.fetchall()
    conn.close()
    return results

# -------------------- File Parsing --------------------
def extract_text(path):
    if path.endswith(".txt"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    elif path.endswith(".pdf"):
        text = ""
        with open(path, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
        return text
    return ""

# -------------------- Routes --------------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/upload", methods=["POST"])
def upload():
    pw = request.form.get("password")
    if pw != ADMIN_PASSWORD:
        return jsonify({"error": "Unauthorized"}), 403
    
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    path = os.path.join(UPLOAD_FOLDER, f.filename)
    f.save(path)

    text = extract_text(path)
    if not text.strip():
        return jsonify({"error": "Unsupported or empty file"}), 400
    
    add_document(f.filename, text, f.filename)
    return jsonify({"success": True, "filename": f.filename})

@app.route("/api/add_text", methods=["POST"])
def add_text():
    pw = request.json.get("password")
    if pw != ADMIN_PASSWORD:
        return jsonify({"error": "Unauthorized"}), 403

    title = request.json.get("title", "Untitled")
    content = request.json.get("content", "")
    if not content.strip():
        return jsonify({"error": "No content"}), 400

    add_document(title, content)
    return jsonify({"success": True})

@app.route("/api/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "").strip()
    if not msg:
        return jsonify({"error": "Empty message"}), 400

    results = search_documents(msg)
    if results:
        # return first match snippet
        title, content = results[0]
        snippet = content[:400] + ("..." if len(content) > 400 else "")
        return jsonify({"response": f"From {title}:\n{snippet}"})
    return jsonify({"response": "I couldn’t find anything in my knowledge base."})

@app.route("/api/docs")
def list_docs():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, title, filename FROM documents")
    docs = [{"id": r[0], "title": r[1], "filename": r[2]} for r in c.fetchall()]
    conn.close()
    return jsonify(docs)

if __name__ == "__main__":
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print("🚀 Chatbot running at http://127.0.0.1:5000/")
    app.run(debug=True)
