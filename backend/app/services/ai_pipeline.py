"""
ManuscriptReady — Academic Rewriting Engine
═══════════════════════════════════════════
Production-grade pipeline with:
- Section-specific optimization (Abstract/Methods/Results/Discussion)
- LaTeX-safe processing (preserves commands, math, environments)
- Meaning integrity safeguards
- Chunking with context awareness
- Retry logic with exponential backoff
"""

import asyncio
import re
import time
import logging
from typing import List, Tuple

from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION-SPECIFIC SYSTEM PROMPTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BASE_RULES = """
## ABSOLUTE SAFETY RULES — VIOLATIONS ARE UNACCEPTABLE
1. NEVER add scientific claims, hypotheses, or interpretations not in the original
2. NEVER invent, fabricate, or modify data, numbers, percentages, p-values, confidence intervals
3. NEVER change mathematical formulas, equations, chemical formulas, or variable names
4. NEVER add, remove, or alter citations, references, or figure/table mentions
5. NEVER change the fundamental argument, conclusion, or finding
6. PRESERVE all technical terminology, acronyms, abbreviations, and proper nouns exactly
7. PRESERVE all numeric values, units, and statistical notation exactly

## GRAMMAR & STYLE REQUIREMENTS
- Fix ALL grammar: subject-verb agreement, articles (a/an/the), tense consistency, prepositions, plurals
- Replace informal vocabulary with precise academic equivalents
- Apply proper academic hedging where claims are made ("suggests", "indicates", "may")
- Use passive voice where conventional (methods, results)
- Add transition words for logical flow (Furthermore, In contrast, Consequently)
- Remove filler phrases ("it should be noted that", "in order to", "due to the fact that")
- Break run-on sentences; combine fragments
- Resolve ambiguous pronoun references

## OUTPUT FORMAT
Return ONLY the rewritten text. No explanations, no preamble, no markdown, no "Here is..."."""

PROMPTS = {
    "general": f"""You are a senior academic English editor at a Nature/Science-caliber journal.
Rewrite the text into clear, grammatically perfect, publication-ready academic English.
{BASE_RULES}""",

    "abstract": f"""You are a senior editor specializing in research abstracts for top-tier journals.
Abstracts must be: concise, self-contained, precisely structured (background→gap→method→results→conclusion).
Rewrite into a publication-ready abstract that is clear, impactful, and within typical word limits.
- Ensure the first sentence establishes context/significance
- State the research gap or objective clearly
- Describe methodology concisely
- Present key findings with specific results
- End with a clear conclusion/implication statement
{BASE_RULES}""",

    "methods": f"""You are a senior editor specializing in methodology sections for top-tier journals.
Methods must be: precise, reproducible, logically ordered, written primarily in past tense passive voice.
Rewrite into a publication-ready methods section:
- Use past tense passive voice consistently ("samples were collected", "data were analyzed")
- Ensure each step is described with sufficient detail for reproducibility
- Present procedures in chronological/logical order
- Include specific quantities, durations, temperatures, and conditions
- Reference established protocols correctly
- Avoid unnecessary hedging in methods (state what WAS done, not what "may have been" done)
{BASE_RULES}""",

    "results": f"""You are a senior editor specializing in results sections for top-tier journals.
Results must: present findings objectively, reference figures/tables, use past tense, avoid interpretation.
Rewrite into a publication-ready results section:
- Use past tense to describe findings
- Present data objectively WITHOUT interpretation (save for Discussion)
- Reference all figures and tables in order
- Report statistical results with exact values
- Use clear topic sentences for each paragraph
- Organize from most to least important findings (or by experimental sequence)
{BASE_RULES}""",

    "discussion": f"""You are a senior editor specializing in discussion sections for top-tier journals.
Discussions must: interpret findings, compare with literature, acknowledge limitations, state implications.
Rewrite into a publication-ready discussion:
- Open by restating the key finding in context of the research question
- Compare findings with existing literature using proper citations
- Explain mechanisms or reasons behind unexpected results
- Apply appropriate hedging for interpretive claims ("These findings suggest...", "One possible explanation is...")
- Include a clear limitations paragraph
- End with implications and future directions
- Distinguish clearly between the authors' findings and previously published work
{BASE_RULES}""",

    "introduction": f"""You are a senior editor specializing in introduction sections for top-tier journals.
Introductions must follow the "funnel" structure: broad context → specific gap → study objective.
Rewrite into a publication-ready introduction:
- Start with broad context establishing significance
- Narrow progressively to the specific research area
- Clearly identify the gap in current knowledge
- State the study objective/hypothesis in the final paragraph
- Maintain proper citation flow
- Use present tense for established knowledge, past tense for specific studies
{BASE_RULES}""",
}

TRANSLATE_REWRITE_PROMPT = f"""You are a senior academic editor. The text below was machine-translated from another language.
Transform it into polished, publication-ready academic English. Fix ALL translation artifacts,
awkward phrasing, and grammar errors. The result must read as if originally written by a native speaker.
{BASE_RULES}"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LATEX-SAFE PROCESSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Patterns to protect during processing
LATEX_PATTERNS = [
    (r'(\$\$[\s\S]*?\$\$)', 'MATHBLOCK'),         # Display math $$...$$
    (r'(\$[^\$]+?\$)', 'MATHINLINE'),              # Inline math $...$
    (r'(\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\})', 'ENVBLOCK'),  # Environments
    (r'(\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})*)', 'TEXCMD'),  # Commands
    (r'(%[^\n]*)', 'TEXCOMMENT'),                  # Comments
]


def protect_latex(text: str) -> Tuple[str, dict]:
    """Replace LaTeX commands with placeholders before AI processing."""
    placeholders = {}
    counter = 0
    protected = text

    for pattern, prefix in LATEX_PATTERNS:
        for match in re.finditer(pattern, protected):
            key = f"⟦{prefix}_{counter}⟧"
            placeholders[key] = match.group(0)
            protected = protected.replace(match.group(0), key, 1)
            counter += 1

    return protected, placeholders


def restore_latex(text: str, placeholders: dict) -> str:
    """Restore LaTeX commands from placeholders after AI processing."""
    restored = text
    for key, original in placeholders.items():
        restored = restored.replace(key, original)
    return restored


def is_latex(text: str) -> bool:
    """Detect if text contains LaTeX content."""
    indicators = [r'\begin{', r'\end{', r'\documentclass', r'\usepackage',
                  r'\section{', r'\textbf{', r'\cite{', r'\ref{', '$$']
    return any(ind in text for ind in indicators)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MEANING INTEGRITY SAFEGUARDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def verify_meaning_integrity(original: str, improved: str) -> dict:
    """
    Verify that critical elements are preserved in the rewrite.
    Returns a report of what was preserved/flagged.
    """
    report = {
        "numbers_preserved": True,
        "citations_preserved": True,
        "formulas_preserved": True,
        "terms_preserved": True,
        "issues": [],
    }

    # Check numbers
    orig_numbers = set(re.findall(r'(?<!\w)[\d]+(?:\.[\d]+)?(?:%|\s*%)?', original))
    impr_numbers = set(re.findall(r'(?<!\w)[\d]+(?:\.[\d]+)?(?:%|\s*%)?', improved))
    missing_nums = orig_numbers - impr_numbers
    if missing_nums:
        report["numbers_preserved"] = False
        report["issues"].append(f"Numbers potentially modified: {missing_nums}")

    # Check citations [1], [2,3], (Author, 2024)
    orig_cites = set(re.findall(r'\[[^\]]*\d+[^\]]*\]|\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|and|&)\s+[A-Z][a-z]+)*,?\s*\d{4}[a-z]?\)', original))
    impr_cites = set(re.findall(r'\[[^\]]*\d+[^\]]*\]|\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|and|&)\s+[A-Z][a-z]+)*,?\s*\d{4}[a-z]?\)', improved))
    missing_cites = orig_cites - impr_cites
    if missing_cites:
        report["citations_preserved"] = False
        report["issues"].append(f"Citations potentially modified: {missing_cites}")

    # Check math/formulas
    orig_formulas = set(re.findall(r'\$[^\$]+\$|\\(?:frac|sqrt|sum|int|alpha|beta|gamma|delta|sigma|mu|theta)\b', original))
    impr_formulas = set(re.findall(r'\$[^\$]+\$|\\(?:frac|sqrt|sum|int|alpha|beta|gamma|delta|sigma|mu|theta)\b', improved))
    missing = orig_formulas - impr_formulas
    if missing:
        report["formulas_preserved"] = False
        report["issues"].append(f"Formulas potentially modified: {missing}")

    # Check key technical terms (ALL CAPS, abbreviations)
    orig_terms = set(re.findall(r'\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b', original))
    impr_terms = set(re.findall(r'\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b', improved))
    common_words = {"THE","AND","FOR","ARE","BUT","NOT","ALL","WAS","ONE","OUR","HAS","HIS","HER",
                    "WHO","DID","MAY","NEW","TWO","ITS","ANY"}
    orig_terms -= common_words
    impr_terms -= common_words
    missing_terms = orig_terms - impr_terms
    if missing_terms:
        report["terms_preserved"] = False
        report["issues"].append(f"Terms potentially lost: {missing_terms}")

    return report


def extract_preserved_terms(text: str) -> List[str]:
    """Extract technical terms that should be preserved."""
    terms = set()
    for m in re.findall(r'\(([A-Z]{2,})\)', text):
        terms.add(m)
    for m in re.findall(r'\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b', text):
        if m not in {"THE","AND","FOR","ARE","BUT","NOT","ALL","WAS","ONE","OUR","HAS"}:
            terms.add(m)
    for m in re.findall(r'[pnrRF]\s*[=<>≤≥]\s*[\d.]+', text):
        terms.add(m)
    return sorted(terms)[:25]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CHUNKING ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def chunk_text(text: str, size: int = None) -> List[str]:
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  REWRITER ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AcademicRewriter:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def rewrite(
        self, text: str, section: str = "general", is_translated: bool = False,
    ) -> Tuple[str, dict]:
        """Full rewrite pipeline with LaTeX safety and meaning verification."""
        start = time.time()

        # LaTeX protection
        latex_mode = is_latex(text)
        placeholders = {}
        process_text = text
        if latex_mode:
            process_text, placeholders = protect_latex(text)

        # Select prompt
        if is_translated:
            prompt = TRANSLATE_REWRITE_PROMPT
        else:
            prompt = PROMPTS.get(section, PROMPTS["general"])

        # Add term preservation instruction
        terms = extract_preserved_terms(process_text)
        if terms:
            prompt += f"\n\n## TERMS TO PRESERVE EXACTLY:\n{', '.join(terms[:30])}"

        if latex_mode:
            prompt += "\n\n## LATEX HANDLING:\nThe text contains placeholders like ⟦MATHBLOCK_0⟧. PRESERVE these placeholders EXACTLY as-is. Do NOT modify, translate, or remove them."

        # Chunk and process
        chunks = chunk_text(process_text)
        sem = asyncio.Semaphore(settings.MAX_CONCURRENT_CHUNKS)
        tasks = [self._chunk(c, prompt, sem, i, len(chunks)) for i, c in enumerate(chunks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        parts, errors = [], []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"Chunk {i} failed: {r}")
                errors.append(str(r))
                parts.append(chunks[i])
            else:
                parts.append(r)

        improved = "\n\n".join(parts)

        # Restore LaTeX
        if latex_mode:
            improved = restore_latex(improved, placeholders)

        # Verify meaning integrity
        safeguards = verify_meaning_integrity(text, improved)

        elapsed = int((time.time() - start) * 1000)
        stats = {
            "original_words": len(text.split()),
            "improved_words": len(improved.split()),
            "chunks": len(chunks),
            "errors": errors,
            "latex_mode": latex_mode,
            "ms": elapsed,
        }

        return improved, {**stats, "safeguards": safeguards, "terms_preserved": terms}

    async def _chunk(self, chunk, prompt, sem, idx, total):
        async with sem:
            content = chunk
            if total > 1:
                content = f"[Part {idx+1}/{total} — maintain consistent style and tone]\n\n{chunk}"
            for attempt in range(3):
                try:
                    r = await self.client.chat.completions.create(
                        model=settings.OPENAI_MODEL,
                        temperature=settings.OPENAI_TEMPERATURE,
                        max_tokens=settings.OPENAI_MAX_TOKENS,
                        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": content}],
                    )
                    out = r.choices[0].message.content.strip()
                    # Strip common AI preambles
                    for pfx in ["Here is the improved","Here is the rewritten","Improved version:","Rewritten:"]:
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
