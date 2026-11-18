"""SQLite persistence for document metadata and Q&A history."""
import sqlite3, json, time
from contextlib import contextmanager
from config import SQLITE_DB_PATH

def _connect():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL UNIQUE,
          stored_path TEXT NOT NULL, num_pages INTEGER, num_chunks INTEGER,
          uploaded_at REAL NOT NULL, content_hash TEXT)""")
        cols = [r["name"] for r in c.execute("PRAGMA table_info(documents)").fetchall()]
        if "content_hash" not in cols: c.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")
        # Migrate older installs that allowed duplicate filenames.
        c.execute("DELETE FROM documents WHERE id NOT IN (SELECT MAX(id) FROM documents GROUP BY filename)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_filename ON documents(filename)")
        c.execute("""CREATE TABLE IF NOT EXISTS chat_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, answer TEXT NOT NULL,
          sources_json TEXT, doc_filter_json TEXT, latency_ms REAL, created_at REAL NOT NULL)""")

def get_document(filename):
    with get_conn() as c:
        row = c.execute("SELECT * FROM documents WHERE filename=?", (filename,)).fetchone()
        return dict(row) if row else None

def add_document(filename, stored_path, num_pages, num_chunks, content_hash=""):
    with get_conn() as c:
        c.execute("""INSERT INTO documents(filename,stored_path,num_pages,num_chunks,uploaded_at,content_hash)
          VALUES(?,?,?,?,?,?) ON CONFLICT(filename) DO UPDATE SET stored_path=excluded.stored_path,
          num_pages=excluded.num_pages,num_chunks=excluded.num_chunks,uploaded_at=excluded.uploaded_at,
          content_hash=excluded.content_hash""",
          (filename, stored_path, num_pages, num_chunks, time.time(), content_hash))

def delete_document(filename):
    with get_conn() as c:
        row = c.execute("SELECT stored_path FROM documents WHERE filename=?", (filename,)).fetchone()
        c.execute("DELETE FROM documents WHERE filename=?", (filename,))
        return row["stored_path"] if row else None

def list_documents():
    with get_conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM documents ORDER BY uploaded_at DESC").fetchall()]

def add_chat_entry(question, answer, sources, doc_filter, latency_ms):
    with get_conn() as c:
        c.execute("INSERT INTO chat_history(question,answer,sources_json,doc_filter_json,latency_ms,created_at) VALUES(?,?,?,?,?,?)",
          (question, answer, json.dumps(sources), json.dumps(doc_filter or []), latency_ms, time.time()))

def list_history(limit=50):
    with get_conn() as c:
        rows = c.execute("SELECT * FROM chat_history ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["sources"]=json.loads(d.pop("sources_json") or "[]")
            d["doc_filter"]=json.loads(d.pop("doc_filter_json") or "[]"); out.append(d)
        return out
