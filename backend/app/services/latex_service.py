"""
ManuscriptReady — LaTeX Processing Service (Production)
═══════════════════════════════════════════════════════
Phase 1 capabilities:
  1. .tex upload (single file or extracted from .zip)
  2. Safe processing — ALL LaTeX commands/math preserved via placeholders
  3. LaTeX export — returns valid .tex with improvements applied
  4. Diff-safe output — improvements only in prose, structure untouched

Architecture:
  - protect_full_latex(): extracts preamble/postamble, protects ALL commands
  - restore_full_latex(): reassembles complete .tex document
  - export_latex(): returns complete .tex file as bytes
"""

import re
import io
import zipfile
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LATEX DOCUMENT PARSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_from_upload(data: bytes, filename: str) -> Tuple[str, dict]:
    """
    Extract text from .tex or .zip upload.
    Returns (body_text, metadata) where metadata includes preamble/postamble for reconstruction.
    """
    if filename.endswith(".zip"):
        return _extract_from_zip(data)
    elif filename.endswith(".tex"):
        return _extract_from_tex(data.decode("utf-8", errors="replace"))
    else:
        raise ValueError(f"Unsupported file type: {filename}")


def _extract_from_zip(data: bytes) -> Tuple[str, dict]:
    """Find the main .tex file in a zip archive."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        tex_files = [f for f in zf.namelist() if f.endswith(".tex")]
        if not tex_files:
            raise ValueError("No .tex file found in archive")

        # Prefer main.tex or the largest .tex file
        main_file = None
        for name in tex_files:
            if "main" in name.lower():
                main_file = name
                break
        if not main_file:
            # Pick the largest .tex file (likely the main document)
            main_file = max(tex_files, key=lambda f: zf.getinfo(f).file_size)

        content = zf.read(main_file).decode("utf-8", errors="replace")
        text, meta = _extract_from_tex(content)
        meta["source_file"] = main_file
        meta["all_tex_files"] = tex_files
        return text, meta


def _extract_from_tex(content: str) -> Tuple[str, dict]:
    """
    Parse a .tex document into:
    - body_text: the text between \begin{document} and \end{document}
    - meta: preamble and postamble for reconstruction
    """
    meta = {"full_source": content, "preamble": "", "postamble": ""}

    # Extract preamble (everything before \begin{document})
    begin_match = re.search(r'\\begin\{document\}', content)
    end_match = re.search(r'\\end\{document\}', content)

    if begin_match and end_match:
        meta["preamble"] = content[:begin_match.end()]
        meta["postamble"] = content[end_match.start():]
        body = content[begin_match.end():end_match.start()].strip()
    else:
        # No document environment — treat entire content as body
        body = content.strip()

    return body, meta


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENHANCED LATEX PROTECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Order matters — more specific patterns first
PROTECT_PATTERNS = [
    # Display math: $$ ... $$
    (r'\$\$[\s\S]*?\$\$', 'DMATH'),
    # Equation environments: \begin{equation} ... \end{equation}
    (r'\\begin\{(?:equation|align|gather|multline|eqnarray)\*?\}[\s\S]*?\\end\{(?:equation|align|gather|multline|eqnarray)\*?\}', 'EQENV'),
    # Other environments (figure, table, listing, etc)
    (r'\\begin\{(?:figure|table|listing|verbatim|lstlisting|algorithm|tikzpicture)\*?\}[\s\S]*?\\end\{(?:figure|table|listing|verbatim|lstlisting|algorithm|tikzpicture)\*?\}', 'FLTENV'),
    # Inline math: $ ... $
    (r'\$[^\$\n]+?\$', 'IMATH'),
    # \[ ... \] display math
    (r'\\\[[\s\S]*?\\\]', 'BMATH'),
    # References and citations
    (r'\\(?:cite|ref|eqref|label|pageref|cref|autoref|nameref)\{[^}]+\}', 'REF'),
    (r'\\(?:citep|citet|citealp|citeauthor|citeyear)\{[^}]+\}', 'REF'),
    # Bibliographic commands
    (r'\\bibliography\{[^}]+\}', 'BIB'),
    (r'\\bibliographystyle\{[^}]+\}', 'BIB'),
    # Section commands (preserve structure)
    (r'\\(?:section|subsection|subsubsection|paragraph|chapter)\*?\{[^}]+\}', 'SEC'),
    # Other LaTeX commands with arguments
    (r'\\(?:textbf|textit|emph|underline|texttt|textrm|textsf|textsc|footnote|url|href)\{[^}]*\}', 'FMT'),
    # Commands with optional + mandatory args
    (r'\\[a-zA-Z]+(?:\[[^\]]*\])?\{[^}]*\}', 'CMD'),
    # Bare commands (no args)
    (r'\\(?:maketitle|tableofcontents|newpage|clearpage|appendix|noindent|medskip|bigskip|smallskip|\\)', 'BCMD'),
    # Comments
    (r'%[^\n]*', 'CMT'),
]


def protect_full_latex(text: str) -> Tuple[str, dict]:
    """
    Replace ALL LaTeX elements with numbered placeholders.
    Returns (cleaned_text, placeholder_map).
    The cleaned text contains only prose for the AI to improve.
    """
    placeholders = {}
    result = text
    counter = 0

    for pattern, prefix in PROTECT_PATTERNS:
        # Use finditer on the CURRENT state of result (important for ordering)
        matches = list(re.finditer(pattern, result))
        for match in reversed(matches):  # Reverse to preserve indices
            key = f"⟦{prefix}{counter}⟧"
            original = match.group(0)
            if key not in placeholders.values():  # Avoid duplicates
                placeholders[key] = original
                result = result[:match.start()] + key + result[match.end():]
                counter += 1

    return result, placeholders


def restore_full_latex(text: str, placeholders: dict) -> str:
    """Restore all LaTeX from placeholders."""
    result = text
    # Sort by key length descending to avoid partial replacements
    for key in sorted(placeholders.keys(), key=len, reverse=True):
        result = result.replace(key, placeholders[key])
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LATEX EXPORT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def export_latex(improved_body: str, meta: dict) -> bytes:
    """
    Reconstruct a complete .tex document from improved body + original metadata.
    Preserves preamble, document class, packages, bibliography exactly.
    """
    preamble = meta.get("preamble", "")
    postamble = meta.get("postamble", r"\end{document}")

    if preamble:
        # Reconstruct with original preamble
        output = f"{preamble}\n\n{improved_body}\n\n{postamble}\n"
    else:
        # No preamble — return just the improved body
        output = improved_body

    return output.encode("utf-8")


def generate_latex_diff(original: str, improved: str) -> str:
    """
    Generate a LaTeX document showing changes using latexdiff-style markup.
    Uses \DIFdel{} and \DIFadd{} for visual diffing.
    """
    diff_preamble = r"""
\usepackage{color}
\providecommand{\DIFdel}[1]{{\color{red}\sout{#1}}}
\providecommand{\DIFadd}[1]{{\color{blue}\textbf{#1}}}
"""

    # Sentence-level diff
    orig_sents = re.split(r'(?<=[.!?])\s+', original)
    impr_sents = re.split(r'(?<=[.!?])\s+', improved)

    output_parts = []
    max_len = max(len(orig_sents), len(impr_sents))

    for i in range(max_len):
        o = orig_sents[i] if i < len(orig_sents) else ""
        m = impr_sents[i] if i < len(impr_sents) else ""

        if o == m:
            output_parts.append(o)
        elif not o:
            output_parts.append(r"\DIFadd{" + m + "}")
        elif not m:
            output_parts.append(r"\DIFdel{" + o + "}")
        else:
            output_parts.append(r"\DIFdel{" + o + "} " + r"\DIFadd{" + m + "}")

    return " ".join(output_parts), diff_preamble


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def validate_latex_integrity(original_body: str, improved_body: str, placeholders: dict) -> dict:
    """
    Verify that all LaTeX placeholders survived the AI rewrite.
    Returns a report of any lost/corrupted placeholders.
    """
    report = {
        "all_preserved": True,
        "total_placeholders": len(placeholders),
        "preserved": 0,
        "lost": [],
    }

    for key in placeholders:
        if key in improved_body:
            report["preserved"] += 1
        else:
            report["all_preserved"] = False
            report["lost"].append({
                "placeholder": key,
                "original_latex": placeholders[key][:80],
            })

    return report
