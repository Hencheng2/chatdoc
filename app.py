import os
import sqlite3
import traceback
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Optional parsers
try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None
try:
    import docx
except Exception:
    docx = None
try:
    import pandas as pd
except Exception:
    pd = None

# ---------------- CONFIG ----------------
DB_FILE = "database.db"
UPLOAD_DIR = "uploads"
ADMIN_PASSWORD = "Hemley@2003"   # admin password you requested

# ---------------- APP ----------------
app = Flask(__name__, static_folder="static")
CORS(app, resources={r"/*": {"origins": "*"}})

# ---------------- DB ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        filename TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def add_document(title, content, filename=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO documents (title, content, filename) VALUES (?, ?, ?)",
              (title, content, filename))
    conn.commit()
    conn.close()

def list_documents(limit=100):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, title, filename, added_at FROM documents ORDER BY added_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "filename": r[2], "added_at": r[3]} for r in rows]

def get_document(doc_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, title, content, filename, added_at FROM documents WHERE id = ?", (doc_id,))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {"id": r[0], "title": r[1], "content": r[2], "filename": r[3], "added_at": r[4]}

def search_documents(query, limit=5):
    q = f"%{query}%"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""SELECT id, title, content, filename FROM documents
                 WHERE content LIKE ? OR title LIKE ?
                 ORDER BY added_at DESC LIMIT ?""", (q, q, limit))
    rows = c.fetchall()
    conn.close()
    results = []
    for r in rows:
        snippet = (r[2] or "")[:600]
        results.append({"id": r[0], "title": r[1], "filename": r[3], "snippet": snippet})
    return results

# ---------------- Parsers ----------------
def extract_text_from_pdf(path):
    if PdfReader is None:
        return ""
    text = []
    try:
        reader = PdfReader(path)
        for p in reader.pages:
            txt = p.extract_text()
            if txt:
                text.append(txt)
    except Exception as e:
        print("PDF parse error:", e)
    return "\n".join(text).strip()

def extract_text_from_docx(path):
    if docx is None:
        return ""
    try:
        d = docx.Document(path)
        paragraphs = [p.text for p in d.paragraphs if p.text]
        return "\n".join(paragraphs).strip()
    except Exception as e:
        print("DOCX parse error:", e)
        return ""

def extract_text_from_csv(path):
    if pd is None:
        return ""
    try:
        df = pd.read_csv(path)
        return df.to_string()
    except Exception as e:
        print("CSV parse error:", e)
        return ""

def extract_text_from_xlsx(path):
    if pd is None:
        return ""
    try:
        df = pd.read_excel(path)
        return df.to_string()
    except Exception as e:
        print("XLSX parse error:", e)
        return ""

def extract_text_generic(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print("Generic text read error:", e)
        return ""

# ---------------- Routes ----------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/docs", methods=["GET"])
def api_docs():
    try:
        docs = list_documents()
        return jsonify({"success": True, "docs": docs})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/doc/<int:doc_id>", methods=["GET"])
def api_get_doc(doc_id):
    doc = get_document(doc_id)
    if not doc:
        return jsonify({"success": False, "error": "Not found"}), 404
    return jsonify({"success": True, "doc": doc})

@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"success": False, "error": "Empty question"}), 400
        results = search_documents(message, limit=5)
        if not results:
            return jsonify({"success": True, "found": False, "response": "No matching information found in the local database."})
        # Build response from matches
        parts = []
        for r in results:
            title = r["title"] or r["filename"] or f"doc-{r['id']}"
            parts.append(f"Document: {title}\nSnippet:\n{r['snippet']}")
        return jsonify({"success": True, "found": True, "response": "\n\n---\n\n".join(parts), "matches": results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/upload", methods=["POST"])
def api_upload():
    try:
        password = request.form.get("password", "")
        if password != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file part"}), 400
        f = request.files["file"]
        if f.filename == "":
            return jsonify({"success": False, "error": "No selected file"}), 400

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        save_path = os.path.join(UPLOAD_DIR, f.filename)
        f.save(save_path)

        ext = f.filename.lower().rsplit(".", 1)[-1] if "." in f.filename else ""
        text = ""
        if ext == "pdf":
            text = extract_text_from_pdf(save_path)
        elif ext == "docx":
            text = extract_text_from_docx(save_path)
        elif ext == "csv":
            text = extract_text_from_csv(save_path)
        elif ext in ("xls", "xlsx"):
            text = extract_text_from_xlsx(save_path)
        elif ext in ("txt", "md"):
            text = extract_text_generic(save_path)
        else:
            # attempt generic text read
            text = extract_text_generic(save_path)

        if not text:
            # still save a short placeholder so the file remains recorded
            add_document(f.filename, f"[uploaded file: {f.filename}]. (No text extracted.)", f.filename)
            return jsonify({"success": True, "filename": f.filename, "note": "No text extracted, file stored as placeholder."})

        add_document(f.filename, text, f.filename)
        return jsonify({"success": True, "filename": f.filename})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/add_text", methods=["POST"])
def api_add_text():
    try:
        data = request.get_json(force=True)
        password = data.get("password", "")
        if password != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        title = data.get("title") or "Untitled"
        content = data.get("content") or ""
        if not content.strip():
            return jsonify({"success": False, "error": "Empty content"}), 400
        add_document(title, content)
        return jsonify({"success": True, "title": title})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# ---------------- Startup ----------------
if __name__ == "__main__":
    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=True)
