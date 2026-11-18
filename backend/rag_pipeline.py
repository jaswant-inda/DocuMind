"""RAG orchestration: intent detection -> (chapter | overview | hybrid) retrieval -> context assembly -> LLM."""
import logging, re, time
from functools import lru_cache
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from config import (LLM_PROVIDER, LLM_MODEL_NAME, LLM_TEMPERATURE, LLM_BASE_URL, OPENAI_API_KEY, ANTHROPIC_API_KEY,
                    GOOGLE_API_KEY, TOP_K_RESULTS, MIN_SIMILARITY, CONTEXT_MAX_CHARS)
import vector_store
from structure import parse_intent, inherit_from_history

log = logging.getLogger("documind.rag")


@lru_cache(maxsize=1)
def _get_llm():
    """Provider-independent: switch via LLM_PROVIDER / LLM_MODEL_NAME / LLM_BASE_URL in .env only."""
    if LLM_PROVIDER == "openai":      # also any OpenAI-compatible server through LLM_BASE_URL (e.g. Groq)
        from langchain_openai import ChatOpenAI
        kw = {"base_url": LLM_BASE_URL} if LLM_BASE_URL else {}
        return ChatOpenAI(model=LLM_MODEL_NAME, temperature=LLM_TEMPERATURE, api_key=OPENAI_API_KEY, timeout=90, max_retries=2, **kw)
    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=LLM_MODEL_NAME, temperature=LLM_TEMPERATURE, api_key=ANTHROPIC_API_KEY, timeout=90, max_retries=2)
    if LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs = {"model": LLM_MODEL_NAME, "google_api_key": GOOGLE_API_KEY}
        if not LLM_MODEL_NAME.startswith("gemini-3"):
            kwargs["temperature"] = LLM_TEMPERATURE
        return ChatGoogleGenerativeAI(**kwargs)
    if LLM_PROVIDER == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(model=LLM_MODEL_NAME, temperature=LLM_TEMPERATURE)
    raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


SYSTEM = (
    "You are DocuMind, an expert assistant that answers questions about the user's uploaded documents.\n"
    "Rules:\n"
    "1. Use the supplied excerpts as your evidence. The excerpts are in reading order and may come from several pages: "
    "combine them into one coherent answer instead of describing each excerpt separately.\n"
    "2. A heading by itself is not the content. If some excerpts are only headings or fragments but others contain the actual text, "
    "answer from the ones that do. Say information is missing ONLY when no excerpt supports it, and then state exactly what is missing.\n"
    "3. When the excerpts cover a whole chapter or section, give an appropriately scoped explanation of it (plot / argument / key points, "
    "in order). Do not invent events, facts or names that are not in the excerpts.\n"
    "4. Cite pages like [Source N] after the claims they support.\n"
    "5. Match the requested length: {length_hint}\n"
    "6. Use plain, clear language; add a short example only when it helps understanding."
)
LENGTH_HINT = {"short": "a brief answer (about 3-5 sentences).",
               "medium": "a clear answer of one to three short paragraphs.",
               "detailed": "a thorough, well-structured answer; follow any word count the user gives."}
prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human", "Conversation so far:\n{history}\n\nScope: {scope}\n\nExcerpts:\n{context}\n\nQuestion: {question}")])


def _standalone_question(question, history):
    """Rewrite a follow-up into a self-contained query. Only called when there is history, and only
    this chat's own history is passed (the caller loads it by chat_id), so chats cannot contaminate each other."""
    if not history:
        return question
    try:
        turns = "\n".join(f"{x.get('role', 'user')}: {x.get('content', '')[:400]}" for x in history[-6:])
        rewrite = ChatPromptTemplate.from_messages([
            ("system", "Rewrite the latest user question as a self-contained search query using the conversation. "
                       "Replace pronouns ('it', 'its', 'that') with the specific topic. If the question is already "
                       "self-contained, return it unchanged. Return ONLY the query."),
            ("human", "{history}\nuser: {question}")])
        out = (_get_llm() | StrOutputParser()).invoke(rewrite.invoke({"history": turns, "question": question})).strip()
        return out or question
    except Exception as e:                                   # never silent: log, then fall back
        log.warning("query rewrite failed, using original question: %s", e)
        return question


def _fit_budget(hits, max_chars):
    """Keep reading order; if too long, take evenly spaced chunks so the whole span stays represented."""
    if sum(len(h["text"]) for h in hits) <= max_chars:
        return hits
    avg = max(1, sum(len(h["text"]) for h in hits) // len(hits))
    n = max(1, max_chars // avg)
    step = len(hits) / n
    return [hits[int(i * step)] for i in range(n)]


def retrieve(question, top_k, source_files, history):
    """Returns (hits, scope_description, retrieval_mode)."""
    intent = inherit_from_history(parse_intent(question), history)
    if intent.kind == "section" and intent.number is not None:
        hits = vector_store.get_section_chunks(source_files, intent.section_kind, intent.number)
        if hits:
            hits = _fit_budget(hits, CONTEXT_MAX_CHARS)
            pages = sorted({h["page_number"] for h in hits})
            return hits, f"{intent.section_kind.title()} {intent.number}, pages {pages[0]}-{pages[-1]} (full text in reading order)", "section", intent
        log.info("no indexed boundaries for %s %s; falling back to semantic search", intent.section_kind, intent.number)
    if intent.kind == "overview":
        hits = _fit_budget(vector_store.get_document_chunks(source_files), CONTEXT_MAX_CHARS)
        if hits:
            return hits, "evenly sampled excerpts from across the whole document", "overview", intent
    standalone = _standalone_question(question, history)
    k = max(top_k, 8) if intent.detail != "short" else top_k
    hits = vector_store.similarity_search(standalone, top_k=k, source_files=source_files)
    hits = sorted(hits, key=lambda h: (h["source_file"], h["page_number"]))   # reading order helps synthesis
    scope = "most relevant passages" + ("" if intent.kind == "general" else " (chapter boundaries not found - answer from these and say so)")
    return hits, scope, "semantic", intent


def _prepare(question, top_k, source_files, history):
    t0 = time.perf_counter()
    hits, scope, mode, intent = retrieve(question, top_k, source_files, history)
    t1 = time.perf_counter()
    log.info("retrieval mode=%s hits=%d ms=%.0f", mode, len(hits), (t1 - t0) * 1000)
    best = max((h["similarity"] for h in hits), default=0)
    if not hits or (mode == "semantic" and best < MIN_SIMILARITY):
        return {"answer": "I couldn't find relevant content in your uploaded documents for that question.", "sources": [],
                "retrieval_ms": round((t1 - t0) * 1000, 1), "generation_ms": 0.0, "total_ms": round((t1 - t0) * 1000, 1),
                "no_relevant_content": True, "invalid_citations": False}, None, t0
    context = "\n\n".join(f"[Source {i}] (file: {h['source_file']}, page: {h['page_number']})\n{h['text']}" for i, h in enumerate(hits, 1))
    history_text = "\n".join(f"{x.get('role')}: {x.get('content', '')[:600]}" for x in (history or [])[-6:])
    pv = prompt.invoke({"context": context, "question": question, "history": history_text or "(none)",
                        "scope": scope, "length_hint": LENGTH_HINT[intent.detail]})
    return {"sources": hits, "retrieval_ms": round((t1 - t0) * 1000, 1), "retrieval_mode": mode}, pv, t0


def _finish(answer, base, t0):
    ids = {int(x) for x in re.findall(r"\[Source\s+(\d+)\]", answer, re.I)}
    base["answer"] = answer
    base["invalid_citations"] = any(i < 1 or i > len(base.get("sources", [])) for i in ids)
    base["generation_ms"] = round((time.perf_counter() - t0) * 1000 - base["retrieval_ms"], 1)
    base["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    base["no_relevant_content"] = False
    return base


def answer_question(question: str, top_k: int = TOP_K_RESULTS, source_files=None, history=None):
    base, pv, t0 = _prepare(question, top_k, source_files, history)
    if pv is None:
        return base
    return _finish((_get_llm() | StrOutputParser()).invoke(pv), base, t0)


def stream_answer(question: str, top_k: int = TOP_K_RESULTS, source_files=None, history=None):
    base, pv, t0 = _prepare(question, top_k, source_files, history)
    if pv is None:
        yield {"event": "done", "data": base}; return
    parts = []
    for token in (_get_llm() | StrOutputParser()).stream(pv):
        parts.append(token); yield {"event": "token", "data": token}
    yield {"event": "done", "data": _finish("".join(parts), base, t0)}
