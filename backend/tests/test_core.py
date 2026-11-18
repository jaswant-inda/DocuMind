import sys, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chunking, database, rag_pipeline
from document_parser import clean_text

def test_clean_text_preserves_paragraphs_and_lists():
    text=clean_text("First paragraph\ncontinues here.\n\n- item one\n- item two")
    assert "paragraph continues" in text
    assert "\n\n" in text
    assert "- item one" in text and "- item two" in text

def test_clean_text_soft_hyphenation():
    assert "information" in clean_text("infor-\nmation")
    assert "state-of-the-art" in clean_text("state-\\nof-the-art")

def test_chunk_ids_are_deterministic(monkeypatch):
    monkeypatch.setattr(chunking,"token_len",lambda s:len(s.split()))
    pages=[{"page_number":1,"text":"one two three four five six"}]
    a=chunking.chunk_pages(pages,"x.pdf","hash")
    b=chunking.chunk_pages(pages,"x.pdf","hash")
    assert [x.chunk_id for x in a]==[x.chunk_id for x in b]
    assert a and all(x.token_count for x in a)

def test_document_upsert_and_delete(tmp_path,monkeypatch):
    monkeypatch.setattr(database,"SQLITE_DB_PATH",tmp_path/"test.db")
    database.init_db()
    database.add_document("x.pdf","/tmp/old",1,2,"old")
    database.add_document("x.pdf","/tmp/new",2,3,"new")
    assert len(database.list_documents())==1
    assert database.get_document("x.pdf")["content_hash"]=="new"
    assert database.delete_document("x.pdf")=="/tmp/new"
    assert database.list_documents()==[]

def test_similarity_threshold_skips_llm(monkeypatch):
    monkeypatch.setattr(rag_pipeline,"MIN_SIMILARITY",0.9)
    monkeypatch.setattr(rag_pipeline.vector_store,"similarity_search",lambda *a,**k:[
        {"text":"weak","source_file":"a.pdf","page_number":1,"chunk_id":"1","similarity":0.2}])
    result=rag_pipeline.answer_question("question")
    assert result["no_relevant_content"] is True
    assert result["sources"]==[]
