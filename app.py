"""
Personal Semantic Chatbot backend with chunking + FAISS

- SQLite stores documents + chunks
- Chunks are embedded and stored in FAISS (IndexIDMap -> vector id == chunk_id)
- Admin endpoints protected by ADMIN_PASSWORD (Hemley@2003)
- Supports .txt, .pdf, .docx, .csv, .xlsx (parsing libs optional)
- If sentence-transformers/faiss not available, falls back to keyword search
"""
import os
import sqlite3
import threading
import traceback
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

# Optional parsing libs
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

# Embeddings + FAISS (optional)
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    import faiss
except Exception:
    SentenceTransformer = None
    np = None
    faiss = None

# ---------- CONFIG ----------
DB_FILE = "database.db"
UPLOAD_DIR = "uploads"
ADMIN_PASSWORD = "Hemley@2003"
FAISS_INDEX_FILE = "faiss.index"

# chunking settings
CHUNK_SIZE = 800        # characters per chunk
CHUNK_OVERLAP = 200     # overlap between chunks

# ---------- APP ----------
app = Flask(__name__, static_folder="static")
from flask_cors import CORS
CORS(app)

# global model & index
_model = None
_index = None
_index_lock = threading.Lock()  # guard index creation/updates

# ---------- DB HELPERS ----------
def get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        filename TEXT,
        added_at TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id INTEGER,
        chunk_index INTEGER,
        chunk_text TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- PARSERS ----------
def extract_text(path):
    p = path.lower()
    if p.endswith(".txt") or p.endswith(".md"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""
    if p.endswith(".pdf") and PdfReader is not None:
        try:
            reader = PdfReader(path)
            parts = []
            for page in reader.pages:
                txt = page.extract_text()
                if txt:
                    parts.append(txt)
            return "\n".join(parts)
        except Exception:
            return ""
    if p.endswith(".docx") and docx is not None:
        try:
            d = docx.Document(path)
            return "\n".join([p.text for p in d.paragraphs if p.text])
        except Exception:
            return ""
    if (p.endswith(".csv") or p.endswith(".xls") or p.endswith(".xlsx")) and pd is not None:
        try:
            df = pd.read_csv(path) if p.endswith(".csv") else pd.read_excel(path)
            return df.to_string()
        except Exception:
            return ""
    # fallback - try reading
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

# ---------- CHUNKING ----------
def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = text.strip()
    if not text:
        return []
    n = len(text)
    if n <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < n:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= n:
            break
        start = end - overlap
    return chunks

# ---------- DB operations for docs + chunks ----------
def add_document_record(title, filename=None):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("INSERT INTO documents (title, filename, added_at) VALUES (?, ?, ?)", (title, filename, now))
    doc_id = c.lastrowid
    conn.commit()
    conn.close()
    return doc_id

def add_chunks_for_doc(doc_id, chunk_texts):
    conn = get_conn()
    c = conn.cursor()
    chunk_ids = []
    for idx, txt in enumerate(chunk_texts):
        c.execute("INSERT INTO chunks (doc_id, chunk_index, chunk_text) VALUES (?, ?, ?)", (doc_id, idx, txt))
        chunk_ids.append(c.lastrowid)
    conn.commit()
    conn.close()
    return chunk_ids

def delete_chunks_for_doc(doc_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    conn.commit()
    conn.close()

def get_chunks_by_ids(chunk_ids):
    if not chunk_ids:
        return []
    conn = get_conn()
    c = conn.cursor()
    q = f"SELECT id, chunk_text, doc_id FROM chunks WHERE id IN ({','.join(['?']*len(chunk_ids))})"
    c.execute(q, chunk_ids)
    rows = c.fetchall()
    conn.close()
    # return in same order as chunk_ids
    id_to_row = {r['id']: r for r in rows}
    return [id_to_row[int(i)] for i in chunk_ids if int(i) in id_to_row]

def list_documents(limit=200):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, title, filename, added_at FROM documents ORDER BY added_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_document(doc_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, title, filename, added_at FROM documents WHERE id = ?", (doc_id,))
    r = c.fetchone()
    conn.close()
    return dict(r) if r else None

def get_doc_content(doc_id):
    # reconstruct doc content from chunks (preferably order by chunk_index)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT chunk_text FROM chunks WHERE doc_id = ? ORDER BY chunk_index", (doc_id,))
    rows = c.fetchall()
    conn.close()
    return "\n\n".join([r['chunk_text'] for r in rows])

def delete_document(doc_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    c.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    conn.commit()
    conn.close()

# ---------- Embeddings & FAISS ----------
def load_model():
    global _model
    if _model is None:
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers not installed")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

def embed_texts(texts):
    # returns float32 normalized numpy array
    if SentenceTransformer is None or np is None:
        raise RuntimeError("Embedding libraries not available")
    m = load_model()
    arr = m.encode(texts, convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)
    if arr.dtype != np.float32:
        arr = arr.astype(np.float32)
    return arr

def ensure_faiss_index():
    """
    Ensure _index exists. If index file exists, load it.
    Otherwise build index from all existing chunks (if model + faiss available).
    """
    global _index
    with _index_lock:
        if _index is not None:
            return _index
        if faiss is None or SentenceTransformer is None or np is None:
            _index = None
            return None
        # try loading on disk
        if os.path.exists(FAISS_INDEX_FILE):
            try:
                _index = faiss.read_index(FAISS_INDEX_FILE)
                return _index
            except Exception:
                # fall through to rebuild
                _index = None
        # create new index
        model = load_model()
        dim = model.get_sentence_embedding_dimension()
        base_index = faiss.IndexFlatIP(dim)
        index = faiss.IndexIDMap(base_index)
        # build from all chunks
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id, chunk_text FROM chunks")
        rows = c.fetchall()
        conn.close()
        if not rows:
            _index = index
            faiss.write_index(_index, FAISS_INDEX_FILE)
            return _index
        # embed in batches
        chunk_ids = [r['id'] for r in rows]
        texts = [r['chunk_text'] for r in rows]
        batch = 64
        all_vecs = []
        all_ids = []
        for i in range(0, len(texts), batch):
            sub = texts[i:i+batch]
            ids_sub = chunk_ids[i:i+batch]
            try:
                vecs = embed_texts(sub)
            except Exception as e:
                print("Embedding failed during index build:", e)
                _index = index
                return _index
            index.add_with_ids(vecs, np.array(ids_sub, dtype=np.int64))
        _index = index
        try:
            faiss.write_index(_index, FAISS_INDEX_FILE)
        except Exception:
            pass
        return _index

def add_vectors_to_index(chunk_id_text_pairs):
    """
    chunk_id_text_pairs: list of (chunk_id, text)
    Adds embeddings to FAISS. Creates index if needed.
    """
    if faiss is None or SentenceTransformer is None or np is None:
        return
    index = ensure_faiss_index()
    if index is None:
        return
    batch_size = 64
    for i in range(0, len(chunk_id_text_pairs), batch_size):
        batch = chunk_id_text_pairs[i:i+batch_size]
        ids = [b[0] for b in batch]
        texts = [b[1] for b in batch]
        try:
            vecs = embed_texts(texts)
            index.add_with_ids(vecs, np.array(ids, dtype=np.int64))
        except Exception as e:
            print("Error adding vectors to index:", e)
    try:
        faiss.write_index(index, FAISS_INDEX_FILE)
    except Exception:
        pass

def rebuild_faiss_index_background():
    def _rebuild():
        try:
            # delete index file to avoid stale issues
            if os.path.exists(FAISS_INDEX_FILE):
                try:
                    os.remove(FAISS_INDEX_FILE)
                except Exception:
                    pass
            ensure_faiss_index()
        except Exception as e:
            print("Rebuild index failed:", e)
            traceback.print_exc()
    threading.Thread(target=_rebuild, daemon=True).start()

# ---------- SEARCH ----------
def semantic_search(query, top_k=5):
    """
    Returns list of dicts: {chunk_id, doc_id, title, snippet, score}
    """
    if SentenceTransformer is None or faiss is None or np is None:
        return []
    try:
        q_emb = embed_texts([query])
    except Exception as e:
        raise
    idx = ensure_faiss_index()
    if idx is None:
        return []
    D, I = idx.search(q_emb, top_k)
    out = []
    ids = I[0]
    scores = D[0]
    for i, cid in enumerate(ids):
        if cid == -1:
            continue
        score = float(scores[i])
        # fetch chunk info from DB
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT doc_id, chunk_text FROM chunks WHERE id = ?", (int(cid),))
        r = c.fetchone()
        conn.close()
        if not r:
            continue
        doc = get_document(r['doc_id'])
        out.append({
            "chunk_id": int(cid),
            "doc_id": int(r['doc_id']),
            "title": doc['title'] if doc else None,
            "snippet": (r['chunk_text'] or "")[:900],
            "score": score
        })
    return out

def keyword_search(query, top_k=5):
    qlike = f"%{query.lower()}%"
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT c.id as chunk_id, c.doc_id, c.chunk_text, d.title
                 FROM chunks c JOIN documents d ON c.doc_id = d.id
                 WHERE lower(c.chunk_text) LIKE ?
                 ORDER BY c.id DESC LIMIT ?""", (qlike, top_k))
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "chunk_id": int(r['chunk_id']),
            "doc_id": int(r['doc_id']),
            "title": r['title'],
            "snippet": (r['chunk_text'] or "")[:900],
            "score": None
        })
    return out

# ---------- ROUTES ----------
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
def api_doc(doc_id):
    try:
        doc = get_document(doc_id)
        if not doc:
            return jsonify({"success": False, "error": "Not found"}), 404
        content = get_doc_content(doc_id)
        doc['content'] = content
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
            return jsonify({"success": False, "error": "No file provided"}), 400
        f = request.files["file"]
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        save_path = os.path.join(UPLOAD_DIR, f.filename)
        f.save(save_path)
        text = extract_text(save_path)
        doc_title = f.filename
        doc_id = add_document_record(doc_title, filename=f.filename)
        if not text or not text.strip():
            # create placeholder chunk so doc is visible
            add_chunks_for_doc(doc_id, [f"[uploaded file: {f.filename}] (no text extracted)"])
            rebuild_faiss_index_background()
            return jsonify({"success": True, "id": doc_id, "note": "no text extracted"})
        chunks = chunk_text(text)
        chunk_ids = add_chunks_for_doc(doc_id, chunks)
        # embed chunks in background
        def _bg(chunk_ids_local):
            try:
                pairs = []
                rows = get_chunks_by_ids(chunk_ids_local)
                for r in rows:
                    pairs.append((r['id'], r['chunk_text']))
                add_vectors_to_index(pairs)
            except Exception as e:
                print("Background embed error:", e)
                traceback.print_exc()
                rebuild_faiss_index_background()
        threading.Thread(target=_bg, args=(chunk_ids,), daemon=True).start()
        return jsonify({"success": True, "id": doc_id, "chunks": len(chunk_ids)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/add_text", methods=["POST"])
def api_add_text():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"success": False, "error": "Invalid payload"}), 400
        if data.get("password") != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        title = data.get("title") or f"text-{datetime.utcnow().isoformat()}"
        content = data.get("content") or ""
        if not content.strip():
            return jsonify({"success": False, "error": "Empty content"}), 400
        doc_id = add_document_record(title, filename=None)
        chunks = chunk_text(content)
        chunk_ids = add_chunks_for_doc(doc_id, chunks)
        # embed in background
        def _bg(chunk_ids_local):
            try:
                rows = get_chunks_by_ids(chunk_ids_local)
                pairs = [(r['id'], r['chunk_text']) for r in rows]
                add_vectors_to_index(pairs)
            except Exception:
                rebuild_faiss_index_background()
        threading.Thread(target=_bg, args=(chunk_ids,), daemon=True).start()
        return jsonify({"success": True, "id": doc_id, "chunks": len(chunk_ids)})
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
        # rebuild FAISS index to remove vectors
        rebuild_faiss_index_background()
        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/append/<int:doc_id>", methods=["POST"])
def api_append(doc_id):
    try:
        data = request.get_json(force=True)
        if not data or data.get("password") != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        extra = data.get("extra") or ""
        if not extra.strip():
            return jsonify({"success": False, "error": "Empty extra"}), 400
        # rebuild all chunks for this doc (simpler & safe)
        # get current content:
        old_content = get_doc_content(doc_id) or ""
        new_content = old_content + "\n\n" + extra
        # delete existing chunks
        delete_chunks_for_doc(doc_id)
        # create new chunks
        chunks = chunk_text(new_content)
        chunk_ids = add_chunks_for_doc(doc_id, chunks)
        # re-embed in background
        def _bg(ids):
            try:
                rows = get_chunks_by_ids(ids)
                pairs = [(r['id'], r['chunk_text']) for r in rows]
                add_vectors_to_index(pairs)
            except Exception:
                rebuild_faiss_index_background()
        threading.Thread(target=_bg, args=(chunk_ids,), daemon=True).start()
        return jsonify({"success": True, "chunks": len(chunk_ids)})
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
        # prefer semantic if available
        if SentenceTransformer is not None and faiss is not None and np is not None:
            try:
                results = semantic_search(q, top_k=6)
                if results:
                    return jsonify({"success": True, "mode": "semantic", "results": results})
                # if semantic returned empty, fall back to keyword
            except Exception as e:
                print("Semantic search error:", e)
        # fallback keyword search
        results = keyword_search(q, top_k=6)
        return jsonify({"success": True, "mode": "keyword", "results": results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/reindex", methods=["POST"])
def api_reindex():
    try:
        pw = request.json.get("password")
        if pw != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        rebuild_faiss_index_background()
        return jsonify({"success": True, "note": "reindex started in background"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# ---------- START ----------
if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # warm model/index in background (non-blocking)
    def _warm():
        try:
            if SentenceTransformer is not None and faiss is not None:
                load_model()
                ensure_faiss_index()
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()
    print("Running on http://127.0.0.1:5000 — Admin password: Hemley@2003")
    app.run(host="0.0.0.0", port=5000, debug=True)
