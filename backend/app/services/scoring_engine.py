"""
ManuscriptReady — Publication Readiness Scoring
════════════════════════════════════════════════
Multi-dimensional quality assessment:
  - Clarity & Readability (Flesch-based)
  - Academic Tone (lexical analysis)
  - Logical Coherence (transition density)
  - Terminology Consistency
  - Reviewer Risk Level (from alerts)
"""

import re
from typing import List
from app.models.schemas import PubScore, ReviewerAlert


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  READABILITY (Flesch metrics)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _syllables(word: str) -> int:
    w = word.lower().strip(".,!?;:'\"()-[]")
    if not w: return 0
    c, prev = 0, False
    for ch in w:
        v = ch in "aeiouy"
        if v and not prev: c += 1
        prev = v
    if w.endswith("e") and c > 1: c -= 1
    return max(1, c)


def readability_metrics(text: str) -> dict:
    sents = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    words = text.split()
    if not sents or not words:
        return {"fre": 0, "grade": 0, "label": "N/A"}
    ns, nw = len(sents), len(words)
    syls = sum(_syllables(w) for w in words)
    fre = max(0, min(100, 206.835 - 1.015 * (nw/ns) - 84.6 * (syls/nw)))
    fk = max(0, 0.39 * (nw/ns) + 11.8 * (syls/nw) - 15.59)
    label = "Easy" if fre >= 70 else "Moderate" if fre >= 50 else "College" if fre >= 30 else "Graduate" if fre >= 10 else "Very Complex"
    return {"fre": round(fre, 1), "grade": round(fk, 1), "label": label}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ACADEMIC TONE SCORE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ACADEMIC_MARKERS = [
    "furthermore", "moreover", "consequently", "therefore", "thus", "hence",
    "nevertheless", "notwithstanding", "demonstrates", "indicates", "suggests",
    "reveals", "elucidates", "methodology", "hypothesis", "correlation",
    "respectively", "attributed", "observed", "investigated", "analyzed",
    "conducted", "yielded", "facilitated", "exhibited", "significant",
    "substantive", "subsequent", "preceding", "aforementioned", "hereafter",
]
HEDGING = ["may", "might", "could", "appears", "suggests", "seemingly", "potentially", "likely", "possibly"]
TRANSITIONS = ["however", "in contrast", "conversely", "additionally", "subsequently", "accordingly",
               "furthermore", "moreover", "nevertheless", "consequently", "meanwhile"]
INFORMAL = ["a lot", "lots of", "kind of", "sort of", "pretty much", "basically", "actually",
            "obviously", "stuff", "things", "gonna", "wanna", "really", "very much", "big deal"]

def academic_tone_score(text: str) -> float:
    lc = text.lower()
    words = lc.split()
    if not words: return 0
    s = 50.0
    for m in ACADEMIC_MARKERS:
        if m in lc: s += 2.5
    for h in HEDGING:
        if h in words: s += 1.5
    for t in TRANSITIONS:
        if t in lc: s += 2.0
    for inf in INFORMAL:
        if inf in lc: s -= 4.0
    contractions = len(re.findall(r"\b\w+n't\b|\b\w+'re\b|\b\w+'ve\b|\b\w+'ll\b|\bI'm\b", text))
    s -= contractions * 5
    passives = len(re.findall(r'\b(?:was|were|is|are|been|being)\s+\w+ed\b', lc))
    s += passives * 0.8
    return max(0, min(100, round(s)))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LOGICAL COHERENCE SCORE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ALL_TRANSITIONS = TRANSITIONS + [
    "first", "second", "third", "finally", "in addition", "for example",
    "for instance", "in particular", "specifically", "as a result",
    "on the other hand", "in summary", "in conclusion", "to summarize",
    "given that", "provided that", "assuming", "with respect to",
]

def coherence_score(text: str) -> float:
    """Score based on transition density and paragraph structure."""
    lc = text.lower()
    sents = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if len(sents) < 2: return 50.0
    trans_count = sum(1 for t in ALL_TRANSITIONS if t in lc)
    density = trans_count / len(sents)
    # Good academic writing: ~0.2-0.5 transitions per sentence
    if density < 0.05: s = 20
    elif density < 0.15: s = 40
    elif density < 0.3: s = 65
    elif density < 0.5: s = 85
    else: s = 75  # Too many transitions is also problematic
    # Bonus for paragraph structure
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paras) > 1: s += 5
    return min(100, s)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TERMINOLOGY CONSISTENCY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def terminology_consistency_score(text: str) -> tuple:
    """Check for inconsistent terminology usage. Returns (score, issues)."""
    from app.models.schemas import TermIssue
    issues = []
    score = 100.0

    # Check acronym introduction: first use should be "Full Name (ACRONYM)"
    acronyms = re.findall(r'\b([A-Z]{2,})\b', text)
    acronyms_set = set(a for a in acronyms if a not in {"THE","AND","FOR","ARE","BUT","NOT","ALL"})
    for acr in acronyms_set:
        intro_pattern = rf'\b\w[\w\s]{{2,40}}\({re.escape(acr)}\)'
        if not re.search(intro_pattern, text) and text.count(acr) > 1:
            issues.append(TermIssue(term=acr, issue="Acronym used without introduction", suggestion=f"First mention should be 'Full Name ({acr})'"))
            score -= 5

    # Check tense consistency within paragraphs
    paras = [p for p in text.split("\n\n") if p.strip()]
    for para in paras:
        past = len(re.findall(r'\b(?:was|were|had|did|showed|found|demonstrated|observed|analyzed|measured)\b', para, re.I))
        present = len(re.findall(r'\b(?:is|are|has|does|shows?|finds?|demonstrates?|observes?)\b', para, re.I))
        if past > 0 and present > 0 and abs(past - present) < max(past, present) * 0.5:
            # Mixed tense detected
            score -= 3

    # Check unit formatting consistency
    units = re.findall(r'\d\s*(mg|mL|ml|µL|uL|kg|g|cm|mm|µm|um|nm|°C|K)\b', text)
    unit_variants = {}
    for u in units:
        normalized = u.lower()
        if normalized not in unit_variants:
            unit_variants[normalized] = set()
        unit_variants[normalized].add(u)
    for norm, variants in unit_variants.items():
        if len(variants) > 1:
            issues.append(TermIssue(term=", ".join(variants), issue="Inconsistent unit formatting", suggestion=f"Standardize to one format"))
            score -= 5

    return max(0, min(100, score)), issues


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COMPOSITE PUBLICATION READINESS SCORE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_pub_score(text: str, reviewer_alerts: List[ReviewerAlert] = None) -> PubScore:
    """Compute full publication readiness score."""
    if not text.strip():
        return PubScore()

    rm = readability_metrics(text)
    tone = academic_tone_score(text)
    coh = coherence_score(text)
    term_score, _ = terminology_consistency_score(text)

    # Reviewer risk from alerts
    risk = 0
    if reviewer_alerts:
        for a in reviewer_alerts:
            if a.severity == "high": risk += 15
            elif a.severity == "medium": risk += 8
            else: risk += 3
    risk = min(100, risk)

    # Map readability to clarity score (academic sweet spot: FRE 20-50)
    fre = rm["fre"]
    if 20 <= fre <= 50:
        clarity = 80 + (30 - abs(35 - fre))  # Peak at FRE=35
    elif fre < 20:
        clarity = max(30, 60 + fre)
    else:
        clarity = max(40, 100 - (fre - 50))

    clarity = min(100, clarity)

    # Overall = weighted average
    overall = (
        clarity * 0.25 +
        tone * 0.25 +
        coh * 0.20 +
        term_score * 0.15 +
        (100 - risk) * 0.15
    )

    return PubScore(
        overall=round(overall, 1),
        clarity=round(clarity, 1),
        academic_tone=round(tone, 1),
        coherence=round(coh, 1),
        term_consistency=round(term_score, 1),
        reviewer_risk=round(risk, 1),
        readability_fre=rm["fre"],
        grade_level=rm["grade"],
        label=rm["label"],
    )
