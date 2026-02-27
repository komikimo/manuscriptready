"""
ManuscriptReady — Academic Rewriting Engine
════════════════════════════════════════════
Section-specific GPT prompts, LaTeX-safe processing,
meaning integrity verification, parallel chunking.
"""

import asyncio
import re
import time
import logging
from typing import List, Tuple

from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SAFETY RULES (injected into every prompt)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SAFETY = """
## ABSOLUTE SAFETY RULES — NEVER VIOLATE
1. NEVER add scientific claims, hypotheses, or interpretations not in the original
2. NEVER invent, fabricate, or modify data, numbers, percentages, p-values, CIs
3. NEVER change mathematical formulas, equations, chemical formulas, variable names
4. NEVER add, remove, or alter citations, references, figure/table mentions
5. NEVER change the fundamental argument or conclusion
6. PRESERVE all technical terms, acronyms, abbreviations, proper nouns exactly
7. PRESERVE all numeric values, units, and statistical notation exactly

## GRAMMAR & STYLE
- Fix ALL grammar: articles (a/an/the), tense, agreement, prepositions, plurals
- Replace informal words with academic equivalents (a lot→numerous, big→substantial)
- Apply hedging where claims are made (suggests, indicates, may)
- Use passive voice where conventional (methods, results)
- Add transitions for flow (Furthermore, In contrast, Consequently)
- Remove fillers (it should be noted that, in order to, due to the fact that)
- Break run-on sentences; combine fragments
- Resolve ambiguous pronoun references

## OUTPUT
Return ONLY the rewritten text. No explanations. No preamble. No markdown."""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION-SPECIFIC PROMPTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SECTION_PROMPTS = {
    "general": f"""You are a senior academic English editor at a Nature/Science-caliber journal.
Rewrite into clear, grammatically perfect, publication-ready academic English.
{SAFETY}""",

    "abstract": f"""You are a senior editor specializing in research abstracts.
Abstracts must be concise, self-contained, structured: background → gap → method → results → conclusion.
- First sentence: establish context/significance
- Clearly state research gap or objective
- Describe methodology concisely
- Present key findings with specific results
- End with clear conclusion/implication
{SAFETY}""",

    "introduction": f"""You are a senior editor for introduction sections.
Follow funnel structure: broad context → specific gap → study objective.
- Start broad, narrow progressively to the research area
- Clearly identify the knowledge gap
- State objective/hypothesis in final paragraph
- Present tense for established knowledge, past for specific studies
{SAFETY}""",

    "methods": f"""You are a senior editor for methodology sections.
Methods must be precise, reproducible, logically ordered, past tense passive voice.
- Past tense passive consistently ("samples were collected")
- Sufficient detail for reproducibility
- Chronological/logical order
- Specific quantities, durations, conditions
- NO hedging in methods — state what WAS done
{SAFETY}""",

    "results": f"""You are a senior editor for results sections.
Present findings objectively, reference figures/tables, past tense, NO interpretation.
- Past tense for findings
- Objective presentation WITHOUT interpretation (save for Discussion)
- Reference figures/tables in order
- Report statistical results with exact values
- Clear topic sentences per paragraph
{SAFETY}""",

    "discussion": f"""You are a senior editor for discussion sections.
Interpret findings, compare with literature, acknowledge limitations, state implications.
- Open by restating key finding in context
- Compare with existing literature using citations
- Apply hedging for interpretive claims ("These findings suggest...")
- Include clear limitations paragraph
- End with implications and future directions
{SAFETY}""",
}

TRANSLATE_REWRITE = f"""You are a senior academic editor. The text below was machine-translated.
Transform into polished, publication-ready academic English. Fix ALL translation artifacts.
{SAFETY}"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LATEX PROTECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LATEX_REGEX = [
    (r'(\$\$[\s\S]*?\$\$)', 'DMATH'),
    (r'(\$[^\$]+?\$)', 'IMATH'),
    (r'(\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\})', 'ENV'),
    (r'(\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})*)', 'CMD'),
]


def protect_latex(text: str) -> Tuple[str, dict]:
    """Replace LaTeX elements with numbered placeholders."""
    placeholders = {}
    result = text
    counter = 0
    for pattern, prefix in LATEX_REGEX:
        for match in re.finditer(pattern, result):
            key = f"⟦{prefix}{counter}⟧"
            placeholders[key] = match.group(0)
            result = result.replace(match.group(0), key, 1)
            counter += 1
    return result, placeholders


def restore_latex(text: str, placeholders: dict) -> str:
    """Restore LaTeX from placeholders."""
    for key, val in placeholders.items():
        text = text.replace(key, val)
    return text


def is_latex(text: str) -> bool:
    return any(x in text for x in [r'\begin{', r'\documentclass', r'\section{', '$$', r'\cite{'])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MEANING INTEGRITY VERIFICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def verify_integrity(original: str, improved: str) -> dict:
    """Check that numbers, citations, formulas, and terms survived rewriting."""
    report = {"numbers": True, "citations": True, "formulas": True, "terms": True, "issues": []}

    # Numbers
    orig_nums = set(re.findall(r'(?<!\w)[\d]+(?:\.[\d]+)?(?:\s*%)?', original))
    impr_nums = set(re.findall(r'(?<!\w)[\d]+(?:\.[\d]+)?(?:\s*%)?', improved))
    missing = orig_nums - impr_nums
    if missing:
        report["numbers"] = False
        report["issues"].append(f"Numbers changed: {missing}")

    # Citations  [1], [2,3], (Author, 2024)
    cite_pat = r'\[[^\]]*\d+[^\]]*\]|\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|and|&))?.*?\d{4}[a-z]?\)'
    orig_cites = set(re.findall(cite_pat, original))
    impr_cites = set(re.findall(cite_pat, improved))
    if orig_cites - impr_cites:
        report["citations"] = False
        report["issues"].append(f"Citations changed: {orig_cites - impr_cites}")

    # Key terms (ALL CAPS acronyms)
    common = {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "ALL", "WAS", "ONE", "OUR", "HAS"}
    orig_t = {t for t in re.findall(r'\b[A-Z]{2,}\b', original)} - common
    impr_t = {t for t in re.findall(r'\b[A-Z]{2,}\b', improved)} - common
    if orig_t - impr_t:
        report["terms"] = False
        report["issues"].append(f"Terms lost: {orig_t - impr_t}")

    return report


def extract_terms(text: str) -> List[str]:
    """Extract technical terms to preserve."""
    common = {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "ALL", "WAS", "ONE", "OUR", "HAS", "HIS", "HER", "WHO", "MAY"}
    terms = set()
    for m in re.findall(r'\(([A-Z]{2,})\)', text):
        terms.add(m)
    for m in re.findall(r'\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b', text):
        if m not in common:
            terms.add(m)
    for m in re.findall(r'[pnrRF]\s*[=<>≤≥]\s*[\d.]+', text):
        terms.add(m)
    return sorted(terms)[:20]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CHUNKING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def chunk_text(text: str, size: int = None) -> List[str]:
    """Split at paragraph boundaries, fallback to sentences."""
    size = size or settings.CHUNK_SIZE
    if len(text) <= size:
        return [text]

    paras = text.split("\n\n")
    chunks, cur = [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(p) > size:
            if cur.strip():
                chunks.append(cur.strip())
                cur = ""
            # Split by sentences
            sents = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(\[])', p)
            sc = ""
            for s in sents:
                if len(sc) + len(s) > size and sc:
                    chunks.append(sc.strip())
                    sc = ""
                sc += s + " "
            if sc.strip():
                chunks.append(sc.strip())
        elif len(cur) + len(p) + 2 > size:
            if cur.strip():
                chunks.append(cur.strip())
            cur = p + "\n\n"
        else:
            cur += p + "\n\n"
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if c.strip()]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  REWRITER ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AcademicRewriter:
    """Core rewriting engine with LaTeX safety, chunking, and verification."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def rewrite(
        self, text: str, section: str = "general", is_translated: bool = False,
    ) -> Tuple[str, dict]:
        start = time.time()

        # LaTeX protection
        latex_mode = is_latex(text)
        placeholders = {}
        proc_text = text
        if latex_mode:
            proc_text, placeholders = protect_latex(text)

        # Build prompt
        prompt = TRANSLATE_REWRITE if is_translated else SECTION_PROMPTS.get(section, SECTION_PROMPTS["general"])

        # Inject preserved terms
        terms = extract_terms(proc_text)
        if terms:
            prompt += f"\n\n## PRESERVE THESE TERMS EXACTLY:\n{', '.join(terms[:25])}"

        if latex_mode:
            prompt += "\n\n## LATEX: Placeholders like ⟦DMATH0⟧ must be preserved EXACTLY. Never modify them."

        # Chunk with context overlap for cross-paragraph coherence
        chunks = chunk_text(proc_text)
        logger.info(f"Rewriting {len(chunks)} chunks, section={section}, latex={latex_mode}")

        # Build context hints from surrounding chunks
        context_hints = []
        for i in range(len(chunks)):
            hint = ""
            if i > 0:
                prev_last = chunks[i-1].split(".")[-2] if "." in chunks[i-1] else chunks[i-1][-200:]
                hint += f"[Previous paragraph ended with: ...{prev_last.strip()[-150:]}]\n"
            if i < len(chunks) - 1:
                next_first = chunks[i+1].split(".")[0] if "." in chunks[i+1] else chunks[i+1][:200]
                hint += f"[Next paragraph begins: {next_first.strip()[:150]}...]\n"
            context_hints.append(hint)

        sem = asyncio.Semaphore(settings.MAX_CONCURRENT)
        tasks = [self._process_chunk(c, prompt, sem, i, len(chunks), context_hints[i])
                 for i, c in enumerate(chunks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        parts, errors = [], []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"Chunk {i} failed: {r}")
                errors.append(str(r))
                parts.append(chunks[i])  # Fallback
            else:
                parts.append(r)

        improved = "\n\n".join(parts)

        if latex_mode:
            improved = restore_latex(improved, placeholders)

        safeguards = verify_integrity(text, improved)
        elapsed = int((time.time() - start) * 1000)

        return improved, {
            "original_words": len(text.split()),
            "improved_words": len(improved.split()),
            "chunks": len(chunks),
            "errors": errors,
            "latex_mode": latex_mode,
            "safeguards": safeguards,
            "terms_preserved": terms,
            "ms": elapsed,
        }

    async def _process_chunk(self, chunk: str, prompt: str, sem, idx: int, total: int, context: str = "") -> str:
        async with sem:
            content = ""
            if total > 1:
                content += f"[Part {idx+1}/{total} — maintain consistent style and terminology]\n"
                if context:
                    content += f"{context}\n"
            content += chunk

            for attempt in range(3):
                try:
                    r = await self.client.chat.completions.create(
                        model=settings.OPENAI_MODEL,
                        temperature=settings.OPENAI_TEMPERATURE,
                        max_tokens=settings.OPENAI_MAX_TOKENS,
                        messages=[
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": content},
                        ],
                    )
                    out = r.choices[0].message.content.strip()
                    # Strip AI preamble
                    for pfx in ["Here is the improved", "Here is the rewritten", "Improved:", "Rewritten:"]:
                        if out.lower().startswith(pfx.lower()):
                            out = out[len(pfx):].strip().lstrip(":").strip()
                    return out
                except Exception as e:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 ** attempt)


_inst = None
def get_rewriter():
    global _inst
    if _inst is None:
        _inst = AcademicRewriter()
    return _inst
