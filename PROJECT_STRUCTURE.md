# Project Structure

```text
rag-document-qa/
├── backend/
│   ├── main.py              # FastAPI: upload/query/SSE/search/replace/delete/health
│   ├── config.py            # Environment settings, thresholds, limits, feature toggles
│   ├── database.py          # SQLite document upsert/delete and Q&A history
│   ├── document_parser.py   # PDF/TXT/MD extraction, paragraph preservation, optional OCR
│   ├── chunking.py          # Embedding-tokenizer-aware, deterministic page chunks
│   ├── embeddings.py        # SentenceTransformer model/tokenizer and embeddings
│   ├── vector_store.py      # Chroma upsert, vector search, optional BM25/RRF and reranker
│   ├── rag_pipeline.py      # Follow-up context, threshold, augmentation, generation, citations
│   ├── tests/test_core.py   # Core unit tests
│   ├── requirements.txt
│   ├── .env.example
│   ├── uploads/
│   └── chroma_db/
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── app.js               # App orchestration and interactions
│   ├── api.js               # API client, upload progress, SSE parser
│   ├── state.js             # Local conversation persistence
│   ├── ui/render.js         # DOM-safe message/source rendering
│   └── favicon.svg
├── eval/
│   ├── testset.json
│   └── run_eval.py
├── requirements.txt
├── README.md
```

## Request lifecycle

1. `/upload`: validate file and hash contents; skip byte-identical uploads; replace old filename version; parse PDF/TXT/MD; clean without flattening paragraphs; chunk with the embedding model's tokenizer; embed and Chroma upsert; persist SQLite metadata.
2. `/query`: optionally rewrite a follow-up using recent turns; retrieve vector candidates; optionally fuse BM25 ranks and rerank with cross-encoder; apply minimum similarity; build grounded context; generate and validate citation numbers; log turn.
3. `/query/stream`: same RAG flow but emits SSE token events and a final metadata event.
4. `/documents/{filename}/search`: exact phrase search in PDF pages, returning page and bounding rectangles.\n5. `/documents/{filename}/download`: download the stored PDF after edits.
5. `/documents/{filename}/replace`: redact found text, insert replacement in the original rectangle, hash and re-index the modified PDF.
6. DELETE: remove vectors, SQLite metadata and stored upload file.

## Notes
- Existing databases should be re-indexed after changing chunking/tokenization because the old vector index contains chunks created with different boundaries.
- Similarity scores are cosine-derived and model-dependent; tune `MIN_SIMILARITY` on a labelled evaluation set.
- OCR and cross-encoder models may require additional downloads/system packages.
