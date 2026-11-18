"""SQLite repository: users, files, chats, messages. Every row carries user_id."""
import sqlite3
from contextlib import contextmanager
from config import SQLITE_DB_PATH

@contextmanager
def db():
    c = sqlite3.connect(SQLITE_DB_PATH); c.row_factory = sqlite3.Row
    try:
        yield c; c.commit()
    finally:
        c.close()

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, full_name TEXT, email TEXT UNIQUE, pw TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS files(file_id TEXT PRIMARY KEY, user_id TEXT, filename TEXT, page_count INT, file_size INT,
          storage_path TEXT, head INT DEFAULT 0, maxv INT DEFAULT 0, updated_at REAL, UNIQUE(user_id, filename));
        CREATE TABLE IF NOT EXISTS chats(chat_id TEXT PRIMARY KEY, user_id TEXT, title TEXT, linked_pdf_ids TEXT, created_at REAL, updated_at REAL);
        CREATE TABLE IF NOT EXISTS messages(message_id TEXT PRIMARY KEY, chat_id TEXT, role TEXT, content TEXT, sources TEXT, timestamp REAL);
        CREATE INDEX IF NOT EXISTS i_files ON files(user_id); CREATE INDEX IF NOT EXISTS i_chats ON chats(user_id);
        CREATE INDEX IF NOT EXISTS i_msgs ON messages(chat_id);""")

def q(sql, *a):
    with db() as c:
        return [dict(r) for r in c.execute(sql, a).fetchall()]

def one(sql, *a):
    r = q(sql, *a); return r[0] if r else None

def run(sql, *a):
    with db() as c:
        c.execute(sql, a)
