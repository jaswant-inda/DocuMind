import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Stub heavy modules so these tests run without torch/PyMuPDF installed.
emb = types.ModuleType("embeddings"); emb.token_len = lambda s: len(s.split()); sys.modules.setdefault("embeddings", emb)
dp = types.ModuleType("document_parser"); dp.PageText = dict; sys.modules.setdefault("document_parser", dp)
try:
    import langchain_text_splitters  # real splitter when installed
except ImportError:                  # minimal stand-in: only used so section/heading logic can be tested offline
    lts = types.ModuleType("langchain_text_splitters")
    class RecursiveCharacterTextSplitter:
        def __init__(self, chunk_size, **kw): self.n = chunk_size
        def split_text(self, t):
            w = t.split(" "); return [" ".join(w[i:i + self.n]) for i in range(0, len(w), self.n)]
    lts.RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter; sys.modules["langchain_text_splitters"] = lts
import structure, chunking
from structure import detect_sections, parse_intent, inherit_from_history

PAGES = [
    {"page_number": 1, "text": "Title page"},
    {"page_number": 2, "text": "Contents\nChapter One\nChapter Two\nChapter Three\nChapter Four"},
    {"page_number": 6, "text": "Chapter One"},
    {"page_number": 7, "text": "Lily walked up the stairs. " * 30 + "As discussed in Chapter 2 we go on."},
    {"page_number": 20, "text": "Chapter 2\nThe Move\n" + "Text here. " * 30},
]

def test_sections_ignore_toc_and_inline_mentions():
    s = detect_sections(PAGES)
    assert [(x.number, x.start_page, x.end_page) for x in s] == [(1, 6, 19), (2, 20, 20)]

def test_heading_only_page_is_not_an_isolated_chunk():
    chunks = chunking.chunk_pages(PAGES, "b.pdf", "h")
    ch1 = [c for c in chunks if c.section_number == 1]
    assert ch1 and not any(c.text.strip() == "Chapter One" for c in chunks)
    assert ch1[0].text.startswith("Chapter One") and len(ch1[0].text) > 60
    assert all(c.section_kind == "chapter" for c in ch1)

def test_intents():
    assert parse_intent("explain in brief chapter 1").number == 1
    assert parse_intent("explain in brief chapter 1").detail == "short"
    assert parse_intent("Summarize Chapter Three in 500 words").number == 3
    assert parse_intent("Give me an overview of the first chapter").number == 1
    assert parse_intent("what are topics in Unit 2").section_kind == "unit"
    assert parse_intent("explain section 4.2").sub_ref == "4.2"
    assert parse_intent("summarize this book").kind == "overview"
    assert parse_intent("who is Atlas?").kind == "general"

def test_follow_up_inherits_chapter():
    it = inherit_from_history(parse_intent("Explain its second topic in more detail"),
                              [{"role": "user", "content": "Explain Chapter 1"}, {"role": "assistant", "content": "..."}])
    assert (it.kind, it.number) == ("section", 1)
