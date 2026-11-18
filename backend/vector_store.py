"""Chroma vector index with optional BM25/RRF and cross-encoder reranking."""
from typing import List, Optional, Dict, Any
import re
import chromadb
from chromadb.config import Settings
from config import CHROMA_DIR, CHROMA_COLLECTION_NAME, TOP_K_RESULTS, RETRIEVAL_CANDIDATES, RERANK_ENABLED, HYBRID_SEARCH_ENABLED, RERANKER_MODEL_NAME
from chunking import Chunk
from embeddings import embed_texts, embed_query

_client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
_collection = _client.get_or_create_collection(name=CHROMA_COLLECTION_NAME, metadata={"hnsw:space":"cosine"})
_reranker = None

def add_chunks(chunks: List[Chunk]):
    if not chunks: return
    vectors = embed_texts([c.text for c in chunks])
    _collection.upsert(ids=[c.chunk_id for c in chunks], embeddings=vectors,
      documents=[c.text for c in chunks],
      metadatas=[{"source_file":c.source_file,"page_number":c.page_number,"chunk_id":c.chunk_id,
                  "token_count":c.token_count,"content_hash":c.content_hash,"chunk_index":c.chunk_index,
                  "section_kind":c.section_kind,"section_number":c.section_number,"section_label":c.section_label} for c in chunks])

def _vector_search(query, n, source_files):
    where = {"source_file":{"$in":source_files}} if source_files else None
    count = _collection.count()
    if not count: return []
    args={"query_embeddings":[embed_query(query)],"n_results":min(max(1,n),count),
          "include":["documents","metadatas","distances"]}
    if where: args["where"]=where
    result=_collection.query(**args); hits=[]
    if not result["ids"] or not result["ids"][0]: return hits
    for text,meta,distance in zip(result["documents"][0],result["metadatas"][0],result["distances"][0]):
        hits.append({"text":text,"source_file":meta["source_file"],"page_number":int(meta["page_number"]),
                     "chunk_id":meta["chunk_id"],"similarity":round(float(1-distance),4)})
    return hits

def _hybrid(query, hits, source_files):
    try:
        from rank_bm25 import BM25Okapi
        where={"source_file":{"$in":source_files}} if source_files else None
        args={"include":["documents","metadatas"]}
        if where: args["where"]=where
        raw=_collection.get(**args)
        docs=raw.get("documents") or []; metas=raw.get("metadatas") or []
        if not docs: return hits
        tokenized=[re.findall(r"\w+",d.lower()) for d in docs]
        bm=BM25Okapi(tokenized); scores=bm.get_scores(re.findall(r"\w+",query.lower()))
        bm_order=sorted(range(len(docs)),key=lambda i:scores[i],reverse=True)[:RETRIEVAL_CANDIDATES]
        ranks={}
        for rank,h in enumerate(hits,1): ranks[h["chunk_id"]]=ranks.get(h["chunk_id"],0)+1/(60+rank)
        for rank,i in enumerate(bm_order,1):
            cid=metas[i]["chunk_id"]; ranks[cid]=ranks.get(cid,0)+1/(60+rank)
        by_id={h["chunk_id"]:h for h in hits}
        for i in bm_order:
            m=metas[i]; cid=m["chunk_id"]
            if cid not in by_id and scores[i] > 0:
                by_id[cid]={"text":docs[i],"source_file":m["source_file"],"page_number":int(m["page_number"]),
                            "chunk_id":cid,"similarity":0.5}
        return sorted(by_id.values(),key=lambda h:ranks.get(h["chunk_id"],0),reverse=True)
    except ImportError:
        return hits

def preload_reranker():
    global _reranker
    if RERANK_ENABLED and _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker=CrossEncoder(RERANKER_MODEL_NAME)

def _rerank(query, hits, top_k):
    global _reranker
    if not RERANK_ENABLED or not hits: return hits[:top_k]
    try:
        if _reranker is None:
            from sentence_transformers import CrossEncoder
            _reranker=CrossEncoder(RERANKER_MODEL_NAME)
        scores=_reranker.predict([(query,h["text"]) for h in hits])
        for h,s in zip(hits,scores): h["rerank_score"]=float(s)
        return sorted(hits,key=lambda h:h["rerank_score"],reverse=True)[:top_k]
    except Exception:
        return hits[:top_k]

def similarity_search(query: str, top_k: int=TOP_K_RESULTS, source_files: Optional[List[str]]=None):
    candidates=_vector_search(query, RETRIEVAL_CANDIDATES if (RERANK_ENABLED or HYBRID_SEARCH_ENABLED) else top_k, source_files)
    if HYBRID_SEARCH_ENABLED: candidates=_hybrid(query,candidates,source_files)
    return _rerank(query,candidates,top_k)

def list_indexed_files():
    all_meta=_collection.get(include=["metadatas"])["metadatas"]
    return sorted({m["source_file"] for m in all_meta}) if all_meta else []

def delete_document(source_file: str):
    _collection.delete(where={"source_file":source_file})


def get_section_chunks(source_files, kind: str, number: int):
    """All chunks of one chapter/unit, in reading order, per document (metadata filter, not similarity)."""
    out = []
    for sf in (source_files or []):
        raw = _collection.get(where={"$and": [{"source_file": sf}, {"section_kind": kind}, {"section_number": number}]},
                              include=["documents", "metadatas"])
        for text, m in zip(raw.get("documents") or [], raw.get("metadatas") or []):
            out.append({"text": text, "source_file": m["source_file"], "page_number": int(m["page_number"]),
                        "chunk_id": m["chunk_id"], "chunk_index": int(m.get("chunk_index", 0)),
                        "section_label": m.get("section_label", ""), "similarity": 1.0})
    return sorted(out, key=lambda h: (h["source_file"], h["chunk_index"]))

def get_document_chunks(source_files):
    out = []
    for sf in (source_files or []):
        raw = _collection.get(where={"source_file": sf}, include=["documents", "metadatas"])
        for text, m in zip(raw.get("documents") or [], raw.get("metadatas") or []):
            out.append({"text": text, "source_file": m["source_file"], "page_number": int(m["page_number"]),
                        "chunk_id": m["chunk_id"], "chunk_index": int(m.get("chunk_index", 0)),
                        "section_label": m.get("section_label", ""), "similarity": 1.0})
    return sorted(out, key=lambda h: (h["source_file"], h["chunk_index"]))
