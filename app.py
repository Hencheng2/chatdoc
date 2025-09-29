"""
Semantic Personal Chatbot backend (single-file)

- SQLite stores documents and metadata (database: database.db)
- FAISS index + sentence-transformers provides semantic search
- Admin-protected upload/add endpoints (password: Hemley@2003)
- Supports .txt, .md, .pdf, .docx, .csv, .xlsx
- If sentence-transformers or faiss not available, falls back to keyword LIKE search

Run:
    pip install -r requirements.txt
    python app.py

Notes:
 - First run may download the embedding model (requires internet).
 - FAISS index stored in 'vector.index', mapping in 'idmap.pkl'
"""

import os
import sqlite3
import threading
import pickle
import traceback
from datetime import datetime
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

# Embedding libs
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    import faiss
except Exception:
    SentenceTransformer = None
    np = None
    faiss = None

# ---------------- CONFIG ----------------
DB_FILE = "database.db"
UPLOAD_DIR = "uploads"
ADMIN_PASSWORD = "Hemley@2003"
FAISS_INDEX_FILE = "vector.index"
IDMAP_FILE = "idmap.pkl"   # list of doc_ids in same order as vectors in FAISS
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # small, good tradeoff
EMBED_DIM = 384  # embedding dim for all-MiniLM-L6-v2

# ---------------- APP ----------------
app = Flask(__name__, static_folder="static")
CORS(app)

# Global embedding model and index (loaded lazily)
_model = None
_index = None
_idmap = []

_index_lock = threading.Lock()

# ---------------- DB ----------------
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
        filename TEXT,
        added_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def add_document(title, content, filename=None):
    init_db()
    conn = get_conn()
    c = conn.cursor()
    added_at = datetime.utcnow().isoformat()
    c.execute("INSERT INTO documents (title, content, filename, added_at) VALUES (?, ?, ?, ?)",
              (title, content, filename, added_at))
    doc_id = c.lastrowid
    conn.commit()
    conn.close()
    return doc_id

def update_document_append(doc_id, extra_text):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT content FROM documents WHERE id = ?", (doc_id,))
    r = c.fetchone()
    if not r:
        return False
    newcontent = (r["content"] or "") + "\n\n" + extra_text
    c.execute("UPDATE documents SET content = ? WHERE id = ?", (newcontent, doc_id))
    conn.commit()
    conn.close()
    # re-embed & update index for this doc
    try:
        emb = embed_texts([newcontent])[0]
        update_faiss_vector(doc_id, emb)
    except Exception:
        pass
    return True

def delete_document(doc_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()
    remove_faiss_vector(doc_id)

def list_documents(limit=200):
    init_db()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, title, filename, added_at FROM documents ORDER BY added_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_document(doc_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, title, content, filename, added_at FROM documents WHERE id = ?", (doc_id,))
    r = c.fetchone()
    conn.close()
    return dict(r) if r else None

# ---------------- File parsing ----------------
def extract_text_from_pdf(path):
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(path)
        parts = []
        for p in reader.pages:
            txt = p.extract_text()
            if txt:
                parts.append(txt)
        return "\n".join(parts)
    except Exception:
        return ""

def extract_text_from_docx(path):
    if docx is None:
        return ""
    try:
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs if p.text]
        return "\n".join(parts)
    except Exception:
        return ""

def extract_text_from_csv(path):
    if pd is None:
        return ""
    try:
        df = pd.read_csv(path)
        return df.to_string()
    except Exception:
        return ""

def extract_text_from_xlsx(path):
    if pd is None:
        return ""
    try:
        df = pd.read_excel(path)
        return df.to_string()
    except Exception:
        return ""

def extract_text_generic(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""

def extract_text(path):
    p = path.lower()
    if p.endswith(".pdf"):
        return extract_text_from_pdf(path)
    if p.endswith(".docx"):
        return extract_text_from_docx(path)
    if p.endswith(".csv"):
        return extract_text_from_csv(path)
    if p.endswith(".xlsx") or p.endswith(".xls"):
        return extract_text_from_xlsx(path)
    if p.endswith(".txt") or p.endswith(".md"):
        return extract_text_generic(path)
    # fallback: try generic
    return extract_text_generic(path)

# ---------------- Embedding & FAISS helpers ----------------
def load_embedding_model():
    global _model
    if _model is None:
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers not installed")
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model

def embed_texts(texts):
    """Return list of numpy arrays (float32)"""
    if SentenceTransformer is None or np is None:
        raise RuntimeError("Embedding model not available")
    model = load_embedding_model()
    embs = model.encode(texts, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
    # ensure float32
    if embs.dtype != np.float32:
        embs = embs.astype('float32')
    return embs

def ensure_faiss_index(dim=EMBED_DIM):
    """Load or create FAISS index and idmap"""
    global _index, _idmap
    with _index_lock:
        if _index is not None and _idmap:
            return _index, _idmap
        # if index file exists, load
        if faiss is not None and os.path.exists(FAISS_INDEX_FILE) and os.path.exists(IDMAP_FILE):
            try:
                _index = faiss.read_index(FAISS_INDEX_FILE)
                with open(IDMAP_FILE, "rb") as f:
                    _idmap = pickle.load(f)
                # if index dim mismatch, rebuild later
                return _index, _idmap
            except Exception:
                pass
        # otherwise create empty index
        if faiss is None or np is None:
            _index = None
            _idmap = []
            return _index, _idmap
        _index = faiss.IndexFlatIP(dim)  # cosine via normalized embeddings -> inner product
        _idmap = []
        # If DB has existing docs, build index
        docs = list_documents(limit=10000)
        if docs:
            texts = [d["content"] for d in map(get_document, [d["id"] for d in docs]) if d and d.get("content")]
            ids = [d["id"] for d in docs]
            # chunk embeddings to avoid memory issues
            batch_size = 64
            vecs = []
            for i in range(0, len(texts), batch_size):
                chunk = texts[i:i+batch_size]
                embs = embed_texts(chunk)
                vecs.append(embs)
            if vecs:
                allvecs = np.vstack(vecs)
                _index.add(allvecs)
                _idmap = ids
                faiss.write_index(_index, FAISS_INDEX_FILE)
                with open(IDMAP_FILE, "wb") as f:
                    pickle.dump(_idmap, f)
        return _index, _idmap

def add_faiss_vector(doc_id, vector):
    """Append vector to FAISS and save mapping."""
    global _index, _idmap
    if faiss is None or np is None:
        return
    ensure_faiss_index()
    with _index_lock:
        v = np.array(vector, dtype='float32').reshape(1, -1)
        _index.add(v)
        _idmap.append(doc_id)
        faiss.write_index(_index, FAISS_INDEX_FILE)
        with open(IDMAP_FILE, "wb") as f:
            pickle.dump(_idmap, f)

def update_faiss_vector(doc_id, vector):
    """FAISS IndexFlatIP cannot update. We'll rebuild whole index for simplicity."""
    # Rebuild index from DB embeddings (costly but acceptable for small sets)
    rebuild_faiss_index()

def remove_faiss_vector(doc_id):
    """Remove doc from index by rebuilding index."""
    rebuild_faiss_index()

def rebuild_faiss_index():
    global _index, _idmap
    with _index_lock:
        # build from scratch from DB
        docs = list_documents(limit=100000)
        texts = []
        ids = []
        for d in docs:
            rec = get_document(d["id"])
            if rec and rec.get("content"):
                texts.append(rec["content"])
                ids.append(rec["id"])
        if not texts:
            _index = None
            _idmap = []
            if os.path.exists(FAISS_INDEX_FILE): os.remove(FAISS_INDEX_FILE)
            if os.path.exists(IDMAP_FILE): os.remove(IDMAP_FILE)
            return
        embs = embed_texts(texts)  # may raise if model missing
        if faiss is None or np is None:
            return
        idx = faiss.IndexFlatIP(embs.shape[1])
        idx.add(embs)
        _index = idx
        _idmap = ids
        faiss.write_index(_index, FAISS_INDEX_FILE)
        with open(IDMAP_FILE, "wb") as f:
            pickle.dump(_idmap, f)

def semantic_search(query, top_k=5):
    """Return list of (doc_id, score) ordered desc by score"""
    try:
        embs = embed_texts([query])
    except Exception as e:
        raise
    idx, idmap = ensure_faiss_index()
    if idx is None or not idmap:
        return []
    D, I = idx.search(embs, top_k)
    res = []
    for score, idxpos in zip(D[0], I[0]):
        if idxpos < 0 or idxpos >= len(idmap):
            continue
        res.append((idmap[idxpos], float(score)))
    return res

# ---------------- Routes ----------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/docs", methods=["GET"])
def api_docs():
    try:
        docs = list_documents()
        return jsonify({"success": True, "docs": docs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/doc/<int:doc_id>", methods=["GET"])
def api_get_doc(doc_id):
    try:
        doc = get_document(doc_id)
        if not doc:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True, "doc": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/upload", methods=["POST"])
def api_upload():
    try:
        pw = request.form.get("password", "")
        if pw != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file"}), 400
        f = request.files["file"]
        if f.filename == "":
            return jsonify({"success": False, "error": "No filename"}), 400
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        save_path = os.path.join(UPLOAD_DIR, f.filename)
        f.save(save_path)
        text = extract_text(save_path)
        if not text.strip():
            # store placeholder
            doc_id = add_document(f.filename, f"[uploaded file: {f.filename}] (no text extracted)", f.filename)
            rebuild_faiss_index()
            return jsonify({"success": True, "id": doc_id, "note": "no text extracted"})
        doc_id = add_document(f.filename, text, f.filename)
        # embed & add to faiss in background to avoid blocking large uploads
        def _background_embed(docid, txt):
            try:
                emb = embed_texts([txt])[0]
                add_faiss_vector(docid, emb)
            except Exception:
                try:
                    rebuild_faiss_index()
                except Exception:
                    pass
        threading.Thread(target=_background_embed, args=(doc_id, text), daemon=True).start()
        return jsonify({"success": True, "id": doc_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/add_text", methods=["POST"])
def api_add_text():
    try:
        data = request.get_json(force=True)
        pw = data.get("password", "")
        if pw != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        title = data.get("title") or f"text-{datetime.utcnow().isoformat()}"
        content = data.get("content", "") or ""
        if not content.strip():
            return jsonify({"success": False, "error": "Empty content"}), 400
        doc_id = add_document(title, content)
        # embed in background
        def _bg(docid, txt):
            try:
                emb = embed_texts([txt])[0]
                add_faiss_vector(docid, emb)
            except Exception:
                try:
                    rebuild_faiss_index()
                except Exception:
                    pass
        threading.Thread(target=_bg, args=(doc_id, content), daemon=True).start()
        return jsonify({"success": True, "id": doc_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/append/<int:doc_id>", methods=["POST"])
def api_append(doc_id):
    try:
        data = request.get_json(force=True)
        pw = data.get("password", "")
        if pw != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        extra = data.get("extra", "") or ""
        if not extra.strip():
            return jsonify({"success": False, "error": "Empty extra"}), 400
        ok = update_document_append(doc_id, extra)
        if not ok:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/delete/<int:doc_id>", methods=["DELETE"])
def api_delete(doc_id):
    try:
        pw = request.args.get("password", "")
        if pw != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        delete_document(doc_id)
        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        data = request.get_json(force=True)
        q = (data.get("message") or "").strip()
        if not q:
            return jsonify({"success": False, "error": "Empty question"}), 400
        # try semantic search if available
        if SentenceTransformer is not None and faiss is not None:
            try:
                results = semantic_search(q, top_k=5)
                if results:
                    out = []
                    for doc_id, score in results:
                        doc = get_document(doc_id)
                        if not doc: continue
                        snippet = (doc["content"] or "")[:600]
                        out.append({"id": doc_id, "title": doc["title"], "score": score, "snippet": snippet})
                    return jsonify({"success": True, "mode": "semantic", "results": out})
                else:
                    return jsonify({"success": True, "mode": "semantic", "results": []})
            except Exception as e:
                # fallback to keyword search
                print("Semantic search failed, falling back:", str(e))
        # fallback keyword search
        conn = get_conn()
        c = conn.cursor()
        qlike = f"%{q.lower()}%"
        c.execute("SELECT id, title, content FROM documents WHERE lower(content) LIKE ? OR lower(title) LIKE ? LIMIT 10", (qlike, qlike))
        rows = c.fetchall()
        conn.close()
        results = []
        for r in rows:
            results.append({"id": r["id"], "title": r["title"], "snippet": (r["content"] or "")[:600]})
        return jsonify({"success": True, "mode": "keyword", "results": results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# ---------------- Startup ----------------
if __name__ == "__main__":
    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # try to ensure model & index (non-blocking index build)
    try:
        if SentenceTransformer is not None:
            # lazy load model in background to avoid startup slowness
            def _warm():
                try:
                    load_embedding_model()
                    ensure_faiss_index()
                except Exception:
                    pass
            threading.Thread(target=_warm, daemon=True).start()
    except Exception:
        pass
    print("Server running on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
