"""Document Processing — DOCX and LaTeX"""
import io, re
from typing import Tuple
from docx import Document

def extract_docx(file_bytes: bytes) -> Tuple[str, dict]:
    doc = Document(io.BytesIO(file_bytes))
    data = []
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip():
            data.append({"i": i, "text": p.text.strip(), "style": p.style.name if p.style else "Normal",
                         "runs": [{"text":r.text,"bold":r.bold,"italic":r.italic} for r in p.runs]})
    text = "\n\n".join(d["text"] for d in data)
    return text, {"paragraphs": data}

def create_docx(text: str, meta: dict = None) -> bytes:
    doc = Document(); meta = meta or {}
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    orig = (meta.get("paragraphs") or [])
    for i, t in enumerate(paras):
        if i < len(orig):
            try: p = doc.add_paragraph(style=orig[i].get("style","Normal"))
            except: p = doc.add_paragraph()
        else: p = doc.add_paragraph()
        r = p.add_run(t)
        if i < len(orig) and orig[i].get("runs") and orig[i]["runs"][0].get("bold"): r.bold = True
    buf = io.BytesIO(); doc.save(buf); buf.seek(0); return buf.read()

def extract_latex(text: str) -> str:
    """Extract text content from LaTeX, preserving structure."""
    # Remove preamble
    body_match = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', text, re.DOTALL)
    if body_match: text = body_match.group(1)
    return text.strip()

def is_latex_file(text: str) -> bool:
    return any(x in text for x in [r'\begin{', r'\documentclass', r'\usepackage', r'\section{'])
