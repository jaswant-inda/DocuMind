"""Page-preserving overlapping chunks measured with the embedding tokenizer."""
from dataclasses import dataclass
from typing import List
import hashlib
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS
from document_parser import PageText
from embeddings import token_len
from structure import detect_sections, section_for_page, HEADING_RE

@dataclass
class Chunk:
    chunk_id: str
    source_file: str
    page_number: int
    text: str
    token_count: int
    content_hash: str = ""
    chunk_index: int = 0
    section_kind: str = ""
    section_number: int = 0
    section_label: str = ""

def _merge_heading_only_pages(pages):
    """A page holding only 'Chapter One' (very common) is folded into the next page, so the heading
    is never an isolated chunk. The merged text keeps the next page's number."""
    out, carry = [], ""
    for p in pages:
        body = p["text"].strip()
        lines = [l for l in body.split("\n") if l.strip()]
        if len(body) < 60 and len(lines) <= 2 and lines and HEADING_RE.match(lines[0]):
            carry = (carry + "\n" + body).strip(); continue
        out.append({**p, "text": (carry + "\n\n" + body).strip() if carry else body}); carry = ""
    if carry and out: out[-1]["text"] += "\n\n" + carry
    return out

def chunk_pages(pages: List[PageText], source_file: str, content_hash: str = "") -> List[Chunk]:
    sections = detect_sections(pages)          # detect on the raw pages (heading page start is the true boundary)
    pages = _merge_heading_only_pages(pages)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE_TOKENS, chunk_overlap=min(CHUNK_OVERLAP_TOKENS, CHUNK_SIZE_TOKENS - 1),
        length_function=token_len, separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = []
    for page in pages:
        for piece in splitter.split_text(page["text"]):
            if not piece.strip():
                continue
            index = len(chunks)
            stable = hashlib.sha256(f"{source_file}:{content_hash}:{page['page_number']}:{index}:{piece}".encode()).hexdigest()
            sec = section_for_page(sections, page["page_number"])
            chunks.append(Chunk(stable, source_file, page["page_number"], piece, token_len(piece), content_hash,
                                index, sec.kind if sec else "", sec.number if sec else 0, sec.label if sec else ""))
    return chunks
