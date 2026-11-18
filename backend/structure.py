"""Document structure: detect chapter/unit headings and parse structural user intent.

Pure Python (no model or PDF dependencies) so it is fast and unit-testable.
Root cause this addresses: novels/reports often put "Chapter One" alone on its own
page. Page-wise chunking then produces a heading-only chunk that retrieval ranks first,
and the LLM (correctly) says "only the heading was provided".
"""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
        "eighth": 8, "ninth": 9, "tenth": 10}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
          "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18,
          "xix": 19, "xx": 20}
_KINDS = r"chapter|unit|part|module|lesson"
_NUM = r"\d{1,3}|[ivxl]{1,6}|" + "|".join(_WORDS) + r"|twenty[- ]\w+"
HEADING_RE = re.compile(rf"^\s*(?P<kind>{_KINDS})\s+(?P<num>{_NUM})\b\s*[:.\-–—]?\s*(?P<title>.{{0,80}})$", re.I)


def to_number(token: str) -> Optional[int]:
    t = token.strip().lower()
    if t.isdigit():
        return int(t)
    if t in _WORDS:
        return _WORDS[t]
    if t in _ORD:
        return _ORD[t]
    if t in _ROMAN:
        return _ROMAN[t]
    m = re.fullmatch(r"twenty[- ](\w+)", t)
    if m and m.group(1) in _WORDS and _WORDS[m.group(1)] < 10:
        return 20 + _WORDS[m.group(1)]
    return None


@dataclass
class Section:
    kind: str            # chapter / unit / part ...
    number: int
    title: str
    start_page: int
    end_page: int = 0

    @property
    def label(self) -> str:
        return f"{self.kind.title()} {self.number}" + (f": {self.title}" if self.title else "")


def detect_sections(pages: List[dict]) -> List[Section]:
    """Find headings in the first lines of each page. A heading counts only if it appears
    at the top of a page (first 3 non-empty lines), which avoids matching in-text mentions
    like 'as discussed in Chapter 2'. Table-of-contents pages (many headings) are skipped."""
    found: List[Section] = []
    for p in pages:
        lines = [l.strip() for l in p["text"].split("\n") if l.strip()][:40]
        hits_on_page = sum(1 for l in lines if HEADING_RE.match(l))
        if hits_on_page > 3:          # table of contents / index page
            continue
        for l in lines[:3]:
            m = HEADING_RE.match(l)
            if not m:
                continue
            num = to_number(m.group("num"))
            if num is None:
                break
            title = m.group("title").strip()
            if title.endswith(".") or len(title.split()) > 10:
                break                 # a sentence, not a heading
            found.append(Section(m.group("kind").lower(), num, title, p["page_number"]))
            break
    # drop duplicates of the same (kind, number), keeping the first occurrence
    seen, uniq = set(), []
    for s in found:
        if (s.kind, s.number) not in seen:
            seen.add((s.kind, s.number)); uniq.append(s)
    last_page = max((p["page_number"] for p in pages), default=0)
    for i, s in enumerate(uniq):
        nxt = next((n for n in uniq[i + 1:] if n.kind == s.kind), None)
        s.end_page = (nxt.start_page - 1) if nxt else last_page
        if s.end_page < s.start_page:
            s.end_page = s.start_page
    return uniq


def section_for_page(sections: List[Section], page: int) -> Optional[Section]:
    best = None
    for s in sections:
        if s.start_page <= page <= s.end_page and (best is None or s.start_page > best.start_page):
            best = s
    return best


# ---------------- query intent ----------------
@dataclass
class Intent:
    kind: str = "general"            # general | section | overview
    section_kind: str = ""
    number: Optional[int] = None
    sub_ref: str = ""                # e.g. "4.2"
    detail: str = "medium"           # short | medium | detailed
    follow_up_ref: bool = False      # question refers back ("its", "that chapter")


_REF = re.compile(rf"\b(?P<kind>{_KINDS})\s+(?P<num>{_NUM})\b", re.I)
_REF_ORD = re.compile(rf"\b(?P<ord>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+(?P<kind>{_KINDS})\b", re.I)
_SUBREF = re.compile(r"\bsection\s+(\d+(?:\.\d+)+)\b", re.I)
_BACKREF = re.compile(r"\b(its|that chapter|this chapter|the same chapter|that unit|that section|the above)\b", re.I)


def detail_level(question: str) -> str:
    q = question.lower()
    if re.search(r"\b(in brief|briefly|short|quick|tl;?dr|one line|few lines|concise)\b", q):
        return "short"
    if re.search(r"\b(detail|detailed|in depth|in-depth|elaborate|thorough|comprehensive|\d{3,4}\s*words)\b", q):
        return "detailed"
    return "medium"


def parse_intent(question: str) -> Intent:
    it = Intent(detail=detail_level(question))
    sm = _SUBREF.search(question)
    if sm:
        it.kind, it.section_kind, it.sub_ref = "section", "section", sm.group(1)
        return it
    m = _REF.search(question)
    if m:
        n = to_number(m.group("num"))
        if n is not None:
            it.kind, it.section_kind, it.number = "section", m.group("kind").lower(), n
    else:
        m = _REF_ORD.search(question)
        if m:
            it.kind, it.section_kind, it.number = "section", m.group("kind").lower(), _ORD[m.group("ord").lower()]
    if it.kind == "general" and re.search(r"\b(summari[sz]e|summary|overview|what is (this|the) (book|document|pdf) about)\b", question, re.I) \
            and re.search(r"\b(book|document|pdf|whole|entire|report|story)\b", question, re.I):
        it.kind = "overview"
    it.follow_up_ref = bool(_BACKREF.search(question))
    return it


def inherit_from_history(intent: Intent, history: List[Dict[str, str]]) -> Intent:
    """For 'explain its second topic', reuse the chapter named in the most recent user turn that had one."""
    if intent.kind == "section" or not intent.follow_up_ref:
        return intent
    for turn in reversed(history or []):
        if turn.get("role") != "user":
            continue
        prev = parse_intent(turn.get("content", ""))
        if prev.kind == "section":
            intent.kind, intent.section_kind, intent.number, intent.sub_ref = "section", prev.section_kind, prev.number, prev.sub_ref
            return intent
    return intent
