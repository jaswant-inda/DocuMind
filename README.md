# DocuMind — Intelligent Document QA (RAG)

A no-build web application for uploading PDF/TXT/Markdown documents, searching their contents, asking grounded questions, and viewing source passages. The workflow follows the project synopsis: extraction → preprocessing/chunking → embeddings → ChromaDB → semantic retrieval → LLM generation with source references.

## Requirements
- Python 3.10+
- An OpenAI / Anthropic / Google Gemini API key (or a locally running Ollama server)
- Internet for the first download of the Sentence-Transformers embedding model
- Optional OCR: Tesseract executable plus `pytesseract` and `Pillow`

## Run locally

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set provider + API key
uvicorn main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
python -m http.server 5500
```

Open http://localhost:5500. Set the backend URL and optional X-API-Key in **Settings** if needed. CORS defaults allow localhost:5500 and 127.0.0.1:5500. Do not use `file://` to open the page.

## Configuration
Important `.env` values:
- `LLM_PROVIDER`, `LLM_MODEL_NAME`, provider API key, `LLM_TEMPERATURE`
- `EMBEDDING_MODEL_NAME`, `CHUNK_SIZE_TOKENS=200`, `CHUNK_OVERLAP_TOKENS=40`
- `TOP_K_RESULTS`, `RETRIEVAL_CANDIDATES`, `MIN_SIMILARITY`
- `RERANK_ENABLED`, `RERANKER_MODEL_NAME`, `HYBRID_SEARCH_ENABLED`
- `MAX_FILE_SIZE_MB`, `MAX_PDF_PAGES`, `API_KEY`, `CORS_ORIGINS`

The chunk length is measured with the embedding model tokenizer. Startup warns if the configured chunk size exceeds the model's `max_seq_length`. OCR is optional and gracefully skipped when its Python/system dependencies are unavailable.

## Features
- Multi-file drag/drop upload with client validation and per-file progress/status.
- Document list with filtering, select-all/none, page/chunk/date metadata, delete and PDF find/replace.
- Streaming RAG answers (fallback to non-streaming `/query`), conversation context, source citations, similarity meters and timings.
- Light/dark theme, responsive mobile drawer, local chat persistence, settings, connection health and accessible controls.
- PDF text search and replacement. Replacement uses PyMuPDF redaction and inserts the new text into the original bounding box; longer text can clip or change layout, so inspect the edited PDF. The replacement is re-indexed automatically.

Markdown rendering uses pinned CDN versions of Marked and DOMPurify. The frontend remains plain HTML/CSS/ES modules and has no build step.

## Evaluation and tests

Upload `sample_docs/Project_I_RAG_Synopsis_Final.pdf` in the web app (or upload your own labelled corpus), then run:

```bash
python eval/run_eval.py --url http://localhost:8000 --k 4
cd backend
pytest -q
```

`eval/testset.json` is a starter set. Replace expected filenames/pages with your own labelled questions. The evaluator reports hit-rate@k, MRR and average end-to-end latency. A meaningful before/after comparison requires running it against the same indexed corpus and provider before and after a code change.

## API
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/upload` | Multipart upload (`files`) |
| POST | `/query` | Grounded answer; accepts `question`, `top_k`, `source_files`, optional `history` |
| POST | `/query/stream` | SSE events `token`, `done`, `error` |
| GET | `/documents` | Document metadata |
| GET | `/documents/{filename}/search?q=...` | Exact PDF text search, page and rectangle matches |\n| GET | `/documents/{filename}/download` | Download original or edited stored file |
| POST | `/documents/{filename}/replace` | Replace `old_text` with `new_text`; optional `replace_all` |
| DELETE | `/documents/{filename}` | Delete Chroma vectors, SQLite row and stored upload |
| GET | `/history` | Recent Q&A log |
| GET | `/health` | Health check |
| POST | `/feedback` | Optional feedback receiver |

When `API_KEY` is set, protected endpoints require `X-API-Key`; `/health` remains public.

## Re-indexing
The chunk size/tokenizer and deterministic chunk IDs changed. Existing Chroma entries are not automatically migrated. For best retrieval consistency, remove the old `backend/chroma_db/` directory and `backend/app_data.db` (back up first), then re-upload all documents. Deleting only the database would leave stale vectors; deleting only Chroma would leave metadata rows.

## Limitations to verify in your environment
- OCR requires the external Tesseract binary and optional Python packages.
- Cross-encoder reranking downloads its model on first use; keep it disabled unless desired.
- BM25 hybrid search requires `rank-bm25` (included in requirements).
- Gemini model parameter compatibility depends on the installed `langchain-google-genai` version; install that optional package when using `LLM_PROVIDER=google`.
- PDF replacement is visual text redaction/reinsertion, not a full semantic PDF editor. Complex fonts, rotated text, multi-line matches and long replacements need manual review.


## DocuMind v3 (accounts + PDF editor)

Backend: `cd backend; python -m pip install -r requirements.txt; copy .env.example .env; python -m uvicorn main:app --reload --port 8000`
Frontend: `cd frontend; python -m http.server 5500` then open http://localhost:5500 and sign up.

- Accounts: scrypt password hashes, signed 7-day tokens (stdlib only), every file/chat query is filtered by `user_id`.
- PDFs: batch upload, switch the open PDF, tick files as chat context. Find/Replace works per match or all; Undo/Redo keep file versions; "Save to workspace" re-indexes for chat; "Save Edited PDF to Laptop" downloads `<name>_edited.pdf`.
- Chats: stored per user, searchable in the sidebar, deletable with confirmation.
- Limits: replacements redraw text in the original box using Helvetica, so fonts may differ and very long replacements are rejected.
