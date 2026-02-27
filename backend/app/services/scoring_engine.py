"""
Publication Readiness Scoring — Multi-dimensional quality assessment.
"""
import re
from typing import List
from app.models.schemas import PubScore, ReviewerAlert

def _syllables(w):
    w = w.lower().strip(".,!?;:'\"()-[]")
    if not w: return 0
    c, prev = 0, False
    for ch in w:
        v = ch in "aeiouy"
        if v and not prev: c += 1
        prev = v
    if w.endswith("e") and c > 1: c -= 1
    return max(1, c)

def readability(text: str) -> dict:
    sents = [s for s in re.split(r'[.!?]+', text) if s.strip()]
    words = text.split()
    if not sents or not words:
        return {"fre": 0, "grade": 0, "label": "N/A"}
    ns, nw = len(sents), len(words)
    syls = sum(_syllables(w) for w in words)
    fre = max(0, min(100, 206.835 - 1.015 * (nw / ns) - 84.6 * (syls / nw)))
    fk = max(0, 0.39 * (nw / ns) + 11.8 * (syls / nw) - 15.59)
    # Academic-calibrated labels (standard Flesch is misleading for research papers)
    if fre >= 60: label = "General (may be too simple for journals)"
    elif fre >= 45: label = "Accessible (good for reviews)"
    elif fre >= 30: label = "Standard Academic"
    elif fre >= 15: label = "Graduate Level"
    else: label = "Expert Level (typical for top journals)"
    return {"fre": round(fre, 1), "grade": round(fk, 1), "label": label}

ACADEMIC = ["furthermore","moreover","consequently","therefore","thus","hence","nevertheless",
            "demonstrates","indicates","suggests","methodology","hypothesis","correlation",
            "investigated","analyzed","conducted","exhibited","significant","attributed","subsequently",
            "identified","previously","characterized","modulates","mediating","elucidated",
            "underlying","respectively","facilitated","preliminary","observed","assessed"]
HEDGING = ["may","might","could","appears","suggests","potentially","likely","possibly"]
TRANSITIONS = ["however","in contrast","additionally","subsequently","accordingly","furthermore",
               "moreover","nevertheless","consequently","for example","as a result"]
INFORMAL = ["a lot","lots of","kind of","sort of","basically","obviously","stuff","gonna","really"]

def tone_score(text: str) -> float:
    lc = text.lower()
    words = lc.split()
    if not words: return 0
    s = 50.0
    for m in ACADEMIC:
        if m in lc: s += 2.5
    for h in HEDGING:
        if h in words: s += 1.5
    for t in TRANSITIONS:
        if t in lc: s += 2.0
    for i in INFORMAL:
        if i in lc: s -= 4.0
    s -= len(re.findall(r"\b\w+n't\b|\b\w+'re\b|\b\w+'ve\b|\b\w+'ll\b", text)) * 5
    # Passive voice bonus (common in academic writing)
    passives = len(re.findall(r'\b(?:was|were|is|are|been|being)\s+\w+ed\b', lc))
    s += passives * 1.0
    # Parenthetical data bonus (shows quantitative rigor)
    parens = len(re.findall(r'\([^)]*(?:\d|p\s*[<>=]|r\s*=|n\s*=|FDR|CI)', text))
    s += parens * 2.0
    # Citation presence bonus
    citations = len(re.findall(r'\[\d+\]|\([A-Z][a-z]+.*?\d{4}\)', text))
    s += citations * 1.5
    # Complex nominal structure (multi-word noun phrases)
    complex_np = len(re.findall(r'\b\w+(?:tion|ment|ance|ence|ity|ism|ogy|ics)\b', lc))
    s += complex_np * 0.5
    return max(0, min(100, round(s)))

def coherence_score(text: str) -> float:
    lc = text.lower()
    sents = [s for s in re.split(r'[.!?]+', text) if s.strip()]
    if len(sents) < 2: return 50
    c = sum(1 for t in TRANSITIONS if t in lc)
    d = c / len(sents)
    return min(100, 20 if d < .05 else 40 if d < .15 else 65 if d < .3 else 85 if d < .5 else 75)

def compute_score(text: str, alerts: List[ReviewerAlert] = None) -> PubScore:
    if not text.strip():
        return PubScore()
    rm = readability(text)
    tn = tone_score(text)
    ch = coherence_score(text)
    risk = 0
    for a in (alerts or []):
        risk += {"high": 15, "medium": 8, "low": 3}.get(a.severity, 3)
    risk = min(100, risk)
    fre = rm["fre"]
    # Academic sweet spot: FRE 20-50
    cl = 80 + (30 - abs(35 - fre)) if 20 <= fre <= 50 else max(30, 60 + fre) if fre < 20 else max(40, 100 - (fre - 50))
    cl = min(100, cl)
    ov = cl * 0.25 + tn * 0.25 + ch * 0.20 + 100 * 0.15 + (100 - risk) * 0.15
    return PubScore(
        overall=round(ov, 1), clarity=round(cl, 1), academic_tone=round(tn, 1),
        coherence=round(ch, 1), term_consistency=100, reviewer_risk=round(risk, 1),
        readability_fre=rm["fre"], grade_level=rm["grade"], label=rm["label"],
    )
