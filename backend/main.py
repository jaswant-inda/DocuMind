"""DocuMind API v3: auth, per-user files, PDF find/replace with undo/redo, persistent chats."""
import hashlib, json, logging, re, time, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
import fitz
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import repo, security, vector_store, rag_pipeline
from security import current_user, rate
from config import UPLOAD_DIR, CORS_ORIGINS, TOP_K_RESULTS, MAX_FILE_SIZE_MB, MAX_PDF_PAGES
from document_parser import parse_document
from chunking import chunk_pages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

@asynccontextmanager
async def lifespan(app):
    repo.init()
    try:
        from embeddings import check_chunk_limit
        check_chunk_limit(); vector_store.preload_reranker()
    except Exception as e:
        print("model preload warning:", e)
    yield

app = FastAPI(title="DocuMind", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])

# ---------------- schemas ----------------
class Signup(BaseModel): full_name: str; email: str; password: str
class Login(BaseModel): email: str; password: str
class Replace(BaseModel): page: int; rect: List[float]; q: str; new_text: str
class EditLine(BaseModel): page: int; rect: List[float]; new_text: str
class ReplaceAll(BaseModel): q: str; new_text: str
class NewChat(BaseModel): linked_pdf_ids: List[str] = []
class Ask(BaseModel): question: str; top_k: Optional[int] = TOP_K_RESULTS; linked_pdf_ids: List[str] = []

pub = lambda u: {k: u[k] for k in ("user_id", "full_name", "email", "created_at")}

# ---------------- auth ----------------
@app.post("/auth/signup")
def signup(b: Signup, req: Request):
    rate("auth:" + req.client.host, 10)
    email = b.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email): raise HTTPException(400, "Enter a valid email")
    if len(b.password) < 8: raise HTTPException(400, "Password must be at least 8 characters")
    if not b.full_name.strip(): raise HTTPException(400, "Name is required")
    if repo.one("SELECT 1 x FROM users WHERE email=?", email): raise HTTPException(409, "Email already registered")
    uid = uuid.uuid4().hex
    repo.run("INSERT INTO users VALUES(?,?,?,?,?)", uid, b.full_name.strip(), email, security.hash_pw(b.password), time.time())
    return {"token": security.make_token(uid)}

@app.post("/auth/login")
def login(b: Login, req: Request):
    rate("auth:" + req.client.host, 10)
    u = repo.one("SELECT * FROM users WHERE email=?", b.email.strip().lower())
    if not u or not security.check_pw(b.password, u["pw"]): raise HTTPException(400, "Incorrect email or password")
    return {"token": security.make_token(u["user_id"])}

@app.get("/auth/me")
def me(u=Depends(current_user)): return pub(u)

# ---------------- files ----------------
def _path(f, n): return UPLOAD_DIR / f"{f['file_id']}.v{n}{Path(f['filename']).suffix.lower()}"

def _own(fid, u):
    f = repo.one("SELECT * FROM files WHERE file_id=? AND user_id=?", fid, u["user_id"])
    if not f: raise HTTPException(404, "File not found")
    return f

def _drop(f):
    vector_store.delete_document(f["file_id"])
    for n in range(f["maxv"] + 1): _path(f, n).unlink(missing_ok=True)
    repo.run("DELETE FROM files WHERE file_id=?", f["file_id"])

def _index(f, path):
    pages = parse_document(path)
    if not pages: raise ValueError("No extractable text (scanned PDFs need OCR)")
    if len(pages) > MAX_PDF_PAGES: raise ValueError(f"Over {MAX_PDF_PAGES} pages")
    chunks = chunk_pages(pages, f["file_id"], f["file_id"])   # source key = file_id (never collides across users)
    vector_store.delete_document(f["file_id"]); vector_store.add_chunks(chunks)
    repo.run("UPDATE files SET page_count=?, updated_at=? WHERE file_id=?", len(pages), time.time(), f["file_id"])

@app.post("/files")
def upload(files: List[UploadFile] = File(...), u=Depends(current_user)):
    out = []
    for up in files:
        name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", Path(up.filename or "").name).strip(" .")
        if Path(name).suffix.lower() not in (".pdf", ".txt", ".md"):
            out.append({"filename": name, "status": "failed", "reason": "unsupported type"}); continue
        raw = up.file.read()
        if len(raw) > MAX_FILE_SIZE_MB * 1048576:
            out.append({"filename": name, "status": "failed", "reason": f"over {MAX_FILE_SIZE_MB} MB"}); continue
        old = repo.one("SELECT * FROM files WHERE user_id=? AND filename=?", u["user_id"], name)
        if old: _drop(old)
        f = {"file_id": uuid.uuid4().hex, "user_id": u["user_id"], "filename": name}
        p = _path(f, 0); p.write_bytes(raw)
        repo.run("INSERT INTO files VALUES(?,?,?,?,?,?,0,0,?)", f["file_id"], u["user_id"], name, 0, len(raw), str(p), time.time())
        try:
            _index(f, p); out.append({"filename": name, "status": "indexed"})
        except Exception as e:
            _drop({**f, "maxv": 0}); out.append({"filename": name, "status": "failed", "reason": str(e)})
    return {"results": out}

@app.get("/files")
def list_files(u=Depends(current_user)):
    return {"files": repo.q("SELECT file_id,filename,page_count,file_size,head,maxv,updated_at FROM files WHERE user_id=? ORDER BY updated_at DESC", u["user_id"])}

@app.delete("/files/{fid}")
def delete_file(fid: str, u=Depends(current_user)):
    _drop(_own(fid, u)); return {"status": "deleted"}

@app.get("/files/{fid}/page/{n}")
def page_png(fid: str, n: int, u=Depends(current_user)):
    f = _own(fid, u)
    with fitz.open(_path(f, f["head"])) as d:
        if not 1 <= n <= len(d): raise HTTPException(404, "No such page")
        return Response(d[n - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).tobytes("png"), media_type="image/png")

@app.get("/files/{fid}/matches")
def matches(fid: str, q: str, u=Depends(current_user)):
    f, out = _own(fid, u), []
    if not q.strip(): return {"matches": []}
    with fitz.open(_path(f, f["head"])) as d:
        for i, pg in enumerate(d):
            for r in pg.search_for(q):
                try: ln = _ltext(_line_at(pg, r)).strip()
                except HTTPException: ln = ""
                out.append({"page": i + 1, "rect": [r.x0, r.y0, r.x1, r.y1], "snippet": ln[:160], "line": ln})
    return {"matches": out}

def _line_at(pg, rect):
    """The text line that contains the match (so edits keep that line's font, size and baseline)."""
    c, hit = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2), None
    for b in pg.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            lr = fitz.Rect(l["bbox"])
            if lr.contains(c): return l
            if hit is None and lr.intersects(rect): hit = l
    if hit is None: raise HTTPException(404, "Text line not found")
    return hit

_ltext = lambda l: "".join(s["text"] for s in l["spans"])

def _font(sp):
    n, fl = sp["font"].lower(), sp["flags"]
    bold, ital = "bold" in n or fl & 16, "italic" in n or "oblique" in n or fl & 2
    fam = ("ti", ("ro", "bo", "it", "bi")) if ("times" in n or "serif" in n and "sans" not in n) else \
          ("co", ("ur", "bo", "it", "bi")) if ("courier" in n or "mono" in n) else ("he", ("lv", "bo", "it", "bi"))
    k = 3 if bold and ital else 1 if bold else 2 if ital else 0
    return {"ti": ["tiro", "tibo", "tiit", "tibi"], "co": ["cour", "cobo", "coit", "cobi"], "he": ["helv", "hebo", "heit", "hebi"]}[fam[0]][k]

def _apply(pg, items):
    """items: [(line, new_text)]. White-out each whole line, then rewrite it at the same origin, font and size."""
    for line, _ in items: pg.add_redact_annot(fitz.Rect(line["bbox"]) + (-0.5, -0.5, 0.5, 0.5), fill=(1, 1, 1))
    pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    for line, text in items:
        sp = line["spans"][0]; size, fn, c = sp["size"], _font(sp), sp["color"]
        col = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)
        ox, oy = sp["origin"]; limit, s = max(line["bbox"][2], pg.rect.x1 - 36), size
        while s > size * 0.7 and fitz.get_text_length(text, fontname=fn, fontsize=s) > limit - ox: s -= 0.25
        pg.insert_text((ox, oy), text, fontname=fn, fontsize=s, color=col)

def _edit(f, fn):
    """Run fn(doc) on a copy of the current version and store it as the next version (drops the redo stack)."""
    src, dst = _path(f, f["head"]), _path(f, f["head"] + 1)
    with fitz.open(src) as d:
        fn(d); d.save(dst, garbage=3, deflate=True)
    for n in range(f["head"] + 2, f["maxv"] + 1): _path(f, n).unlink(missing_ok=True)
    repo.run("UPDATE files SET head=?, maxv=?, updated_at=? WHERE file_id=?", f["head"] + 1, f["head"] + 1, time.time(), f["file_id"])

state = lambda fid: repo.one("SELECT file_id,filename,page_count,head,maxv FROM files WHERE file_id=?", fid)

@app.post("/files/{fid}/replace")
def replace_one(fid: str, b: Replace, u=Depends(current_user)):
    f = _own(fid, u)
    if not b.q.strip(): raise HTTPException(400, "Nothing to find")
    def run(d):
        pg = d[b.page - 1]; r = fitz.Rect(*b.rect); line = _line_at(pg, r); text = _ltext(line)
        occ = list(re.finditer(re.escape(b.q), text, re.I))
        if not occ: raise HTTPException(404, "Match not found on this line")
        w, cx = max(line["bbox"][2] - line["bbox"][0], 1), (r.x0 + r.x1) / 2 - line["bbox"][0]
        m = min(occ, key=lambda m: abs((m.start() + m.end()) / 2 / max(len(text), 1) * w - cx))   # only THIS occurrence
        _apply(pg, [(line, text[:m.start()] + b.new_text + text[m.end():])])
    _edit(f, run); return state(fid)

@app.post("/files/{fid}/replace_all")
def replace_all(fid: str, b: ReplaceAll, u=Depends(current_user)):
    f = _own(fid, u)
    def run(d):
        hit = False
        for pg in d:
            items = [(l, re.sub(re.escape(b.q), lambda _: b.new_text, _ltext(l), flags=re.I))
                     for bl in pg.get_text("dict")["blocks"] for l in bl.get("lines", [])
                     if re.search(re.escape(b.q), _ltext(l), re.I)]
            if items: _apply(pg, items); hit = True
        if not hit: raise HTTPException(404, "No matches")
    _edit(f, run); return state(fid)

@app.post("/files/{fid}/edit_line")
def edit_line(fid: str, b: EditLine, u=Depends(current_user)):
    f = _own(fid, u)
    def run(d):
        pg = d[b.page - 1]; _apply(pg, [(_line_at(pg, fitz.Rect(*b.rect)), b.new_text)])
    _edit(f, run); return state(fid)

@app.post("/files/{fid}/undo")
def undo(fid: str, u=Depends(current_user)):
    f = _own(fid, u)
    if f["head"] > 0: repo.run("UPDATE files SET head=head-1 WHERE file_id=?", fid)
    return state(fid)

@app.post("/files/{fid}/redo")
def redo(fid: str, u=Depends(current_user)):
    f = _own(fid, u)
    if f["head"] < f["maxv"]: repo.run("UPDATE files SET head=head+1 WHERE file_id=?", fid)
    return state(fid)

@app.post("/files/{fid}/commit")
def commit(fid: str, u=Depends(current_user)):
    f = _own(fid, u); _index(f, _path(f, f["head"])); return state(fid)   # re-index so chat sees the edits

@app.get("/files/{fid}/download")
def download(fid: str, u=Depends(current_user)):
    f = _own(fid, u); stem = Path(f["filename"]).stem
    return FileResponse(_path(f, f["head"]), filename=f"{stem}_edited.pdf", media_type="application/pdf")

# ---------------- chats ----------------
def _chat(cid, u):
    c = repo.one("SELECT * FROM chats WHERE chat_id=? AND user_id=?", cid, u["user_id"])
    if not c: raise HTTPException(404, "Chat not found")
    c["linked_pdf_ids"] = json.loads(c["linked_pdf_ids"] or "[]"); return c

@app.get("/chats")
def chats(u=Depends(current_user)):
    return {"chats": repo.q("SELECT chat_id,title,updated_at FROM chats WHERE user_id=? ORDER BY updated_at DESC", u["user_id"])}

@app.post("/chats")
def new_chat(b: NewChat, u=Depends(current_user)):
    cid, t = uuid.uuid4().hex, time.time()
    repo.run("INSERT INTO chats VALUES(?,?,?,?,?,?)", cid, u["user_id"], "New chat", json.dumps(b.linked_pdf_ids), t, t)
    return _chat(cid, u)

@app.get("/chats/{cid}")
def get_chat(cid: str, u=Depends(current_user)):
    c = _chat(cid, u)
    c["messages"] = [{**m, "sources": json.loads(m["sources"] or "[]")} for m in
                     repo.q("SELECT * FROM messages WHERE chat_id=? ORDER BY timestamp", cid)]
    return c

@app.delete("/chats/{cid}")
def del_chat(cid: str, u=Depends(current_user)):
    _chat(cid, u); repo.run("DELETE FROM messages WHERE chat_id=?", cid); repo.run("DELETE FROM chats WHERE chat_id=?", cid)
    return {"status": "deleted"}

@app.post("/chats/{cid}/ask")
def ask(cid: str, b: Ask, u=Depends(current_user)):
    rate("ask:" + u["user_id"], 30)
    c = _chat(cid, u)
    if not b.question.strip(): raise HTTPException(400, "Question is empty")
    mine = {f["file_id"]: f["filename"] for f in repo.q("SELECT file_id,filename FROM files WHERE user_id=?", u["user_id"])}
    ids = [i for i in b.linked_pdf_ids if i in mine] or list(mine)       # always scoped to this user's files
    hist = [{"role": m["role"], "content": m["content"]} for m in
            repo.q("SELECT role,content FROM messages WHERE chat_id=? ORDER BY timestamp DESC LIMIT 6", cid)][::-1]
    if not ids:
        res = {"answer": "Upload a document first, then ask again.", "sources": [], "no_relevant_content": True}
    else:
        try:
            res = rag_pipeline.answer_question(b.question, b.top_k or TOP_K_RESULTS, ids, hist)
        except Exception as e:
            m = str(e).lower()
            if "429" in m or "rate" in m or "quota" in m: raise HTTPException(429, "LLM rate limit reached - retry shortly")
            if "api key" in m or "401" in m: raise HTTPException(502, "LLM API key rejected or missing")
            raise HTTPException(502, f"LLM request failed: {str(e)[:200]}")
    for s in res.get("sources", []): s["source_name"] = mine.get(s["source_file"], "document")
    t = time.time()
    repo.run("INSERT INTO messages VALUES(?,?,?,?,?,?)", uuid.uuid4().hex, cid, "user", b.question, "[]", t)
    repo.run("INSERT INTO messages VALUES(?,?,?,?,?,?)", uuid.uuid4().hex, cid, "assistant", res["answer"], json.dumps(res.get("sources", [])), t + 0.001)
    title = c["title"] if c["title"] != "New chat" else (b.question.strip()[:48] + ("…" if len(b.question) > 48 else ""))
    repo.run("UPDATE chats SET title=?, linked_pdf_ids=?, updated_at=? WHERE chat_id=?", title, json.dumps(ids if b.linked_pdf_ids else []), time.time(), cid)
    return res

@app.get("/health")
def health(): return {"status": "ok"}
