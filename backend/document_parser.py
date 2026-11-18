"""PDF/TXT/Markdown extraction; preserve paragraph and list structure."""
import re
from pathlib import Path
from typing import List, TypedDict
import fitz

class PageText(TypedDict):
    page_number: int
    text: str

def clean_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw.replace("\x00", "").replace("\x0c", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=[a-z]{2,}-)", "-", text)
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z]{2,}(?![a-z-]))", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out, paragraph = [], []
    def flush():
        if paragraph:
            out.append(" ".join(paragraph).strip())
            paragraph.clear()
    for line in lines:
        if not line:
            flush()
            if out and out[-1] != "":
                out.append("")
        elif re.match(r"^(?:[-*•]|\d+[.)])\s+", line):
            flush()
            out.append(line)
        elif line.endswith(":") or (len(line) < 45 and not line.endswith(".")):
            flush()
            out.append(line)
        else:
            paragraph.append(line)
    flush()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

def parse_pdf(file_path: Path) -> List[PageText]:
    pages = []
    with fitz.open(file_path) as doc:
        for i, page in enumerate(doc):
            raw = page.get_text("text", sort=True)
            if not raw.strip():
                try:
                    import pytesseract
                    from PIL import Image
                    import io
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    raw = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))))
                except Exception:
                    raw = ""
            cleaned = clean_text(raw)
            if cleaned:
                pages.append({"page_number": i + 1, "text": cleaned})
    return pages

def parse_txt(file_path: Path) -> List[PageText]:
    cleaned = clean_text(Path(file_path).read_text(encoding="utf-8", errors="ignore"))
    return [{"page_number": 1, "text": cleaned}] if cleaned else []

def parse_document(file_path: Path) -> List[PageText]:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(file_path)
    if suffix in (".txt", ".md"):
        return parse_txt(file_path)
    raise ValueError(f"Unsupported file type: {suffix}. Supported: .pdf, .txt, .md")
