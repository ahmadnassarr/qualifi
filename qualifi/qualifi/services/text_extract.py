"""Turn uploaded PDF, Word and text files into plain text (kept per page for citations)."""
import os
import re

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def allowed_file(filename):
    return os.path.splitext(filename or "")[1].lower() in ALLOWED_EXTENSIONS


def extract_pages(path):
    """Return a list of page texts. Word and text files count as one page."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            try:
                pages.append(_clean(page.extract_text() or ""))
            except Exception:  # a damaged page should not break the whole upload
                pages.append("")
        return pages
    if ext == ".docx":
        import docx
        document = docx.Document(path)
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return [_clean("\n".join(parts))]
    if ext in (".txt", ".md"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            return [_clean(f.read())]
    raise ValueError("Unsupported file type: " + ext)


def extract_text(path):
    return "\n\n".join(p for p in extract_pages(path) if p)


def _clean(text):
    text = text.replace(" ", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
