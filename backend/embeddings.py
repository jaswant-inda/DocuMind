"""Sentence-transformer embedding helpers and model-tokenizer length measurement."""
from functools import lru_cache
from typing import List
from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL_NAME, CHUNK_SIZE_TOKENS

@lru_cache(maxsize=1)
def _get_model():
    return SentenceTransformer(EMBEDDING_MODEL_NAME)

def embedding_model():
    return _get_model()

def token_len(text: str) -> int:
    # Measure with the exact tokenizer used by the embedding model.
    model = _get_model()
    encoded = model.tokenize([text])
    return int(encoded["attention_mask"].sum().item())

def embed_texts(texts: List[str]) -> List[List[float]]:
    return _get_model().encode(texts, batch_size=32, show_progress_bar=False,
                               normalize_embeddings=True).tolist()

def embed_query(query: str) -> List[float]:
    return _get_model().encode([query], normalize_embeddings=True)[0].tolist()

def check_chunk_limit():
    model = _get_model()
    limit = int(model.max_seq_length)
    if CHUNK_SIZE_TOKENS > limit - 2:
        import warnings
        warnings.warn(f"CHUNK_SIZE_TOKENS={CHUNK_SIZE_TOKENS} exceeds embedding model max_seq_length={limit}; chunks will be truncated.", RuntimeWarning)
    return limit
