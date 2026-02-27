"""
ManuscriptReady — Evaluation Framework v2
══════════════════════════════════════════

METRIC DEFINITIONS
══════════════════
1. Reviewer Detection Recall: % of known issues correctly identified.
   Formula: (true positives) / (total known issues per sample)
   Threshold: ≥50% to pass

2. False Positive Rate: Alerts on clean, well-written academic text.
   Formula: (alerts on clean sample) / (clean samples)
   Threshold: 0 false positives on clean samples to pass

3. Tone Score Accuracy: Whether computed tone falls within expert-calibrated range.
   Method: Each sample has a human-determined tone range (e.g., informal=10-40, academic=60-100)
   Threshold: Score must fall within the range

4. Readability Calibration: FRE score within expected academic range.
   Method: Expert-determined FRE range per sample
   Threshold: FRE within range

5. Meaning Integrity: All numbers, citations, and terms survive a simulated rewrite.
   Method: Apply known-good transformations, verify preservation
   Threshold: 100% preservation required

6. LaTeX Roundtrip: protect → restore produces identical output.
   Threshold: Byte-perfect match

7. Terminology Detection: Acronym and unit consistency issues caught.
   Threshold: Known issues detected

8. Journal Compliance: Style violations detected for known-wrong formats.
   Threshold: Violations detected

METHODOLOGY
═══════════
- Each sample is a short academic text with KNOWN characteristics
- Expected values determined by domain expert analysis
- Tests are deterministic (no AI calls) — reproducible on every run
- Samples cover: pure overclaiming, clean text, methods issues,
  informal writing, terminology problems, LaTeX, citations,
  journal format violations, well-written abstracts, mixed problems

RUN: python -m app.services.evaluation_v2
"""

import re
from typing import List, Tuple


# ═══════════════════════════════════════════════════
#  INLINE ENGINE (no imports — standalone executable)
# ═══════════════════════════════════════════════════

def _syl(w):
    w = w.lower().strip(".,!?;:()")
    if not w: return 0
    c, p = 0, False
    for ch in w:
        v = ch in "aeiouy"
        if v and not p: c += 1
        p = v
    if w.endswith("e") and c > 1: c -= 1
    return max(1, c)

def _readability(t):
    ss = [s for s in re.split(r'[.!?]+', t) if s.strip()]
    ws = t.split()
    if not ss or not ws: return 0
    sy = sum(_syl(w) for w in ws)
    return round(max(0, min(100, 206.835 - 1.015 * (len(ws) / len(ss)) - 84.6 * (sy / len(ws)))), 1)

ACAD = ["furthermore", "moreover", "consequently", "therefore", "demonstrates", "indicates",
        "suggests", "methodology", "hypothesis", "significant", "investigated", "analyzed",
        "conducted", "exhibited", "attributed", "subsequently", "nevertheless", "identified",
        "previously", "characterized", "modulates", "underlying", "observed", "assessed", "preliminary"]

def _tone(t):
    lc, ws = t.lower(), t.lower().split()
    s = 50
    for w in ACAD:
        if w in lc: s += 2.5
    for w in ["may", "might", "could", "appears", "suggests", "potentially", "likely"]:
        if w in ws: s += 1.5
    for w in ["however", "furthermore", "moreover", "consequently", "therefore", "in contrast",
              "additionally", "nevertheless", "subsequently", "for example", "as a result"]:
        if w in lc: s += 2
    for w in ["a lot", "lots of", "kind of", "sort of", "basically", "obviously", "stuff", "gonna", "really"]:
        if w in lc: s -= 4
    s += len(re.findall(r'\b(?:was|were|is|are|been)\s+\w+ed\b', lc))
    s += len(re.findall(r'\([^)]*(?:\d|p\s*[<>=]|r\s*=|FDR)', t)) * 2
    s += len(re.findall(r'\[\d+\]|\([A-Z][a-z]+.*?\d{4}\)', t)) * 1.5
    s += len(re.findall(r'\b\w+(?:tion|ment|ance|ence|ity|ism|ogy|ics)\b', lc)) * 0.5
    return max(0, min(100, round(s)))

RULES = [
    (r'\b(?:clearly|obviously|undoubtedly|definitively)\s+(?:proves?|shows?|demonstrates?)\b', "overclaiming", "high"),
    (r'\bproves?\s+(?:that|beyond)\b', "overclaiming", "high"),
    (r'\bfor the first time\b', "overclaiming", "medium"),
    (r'\bnovel\b', "overclaiming", "low"),
    (r'\b(?:some|several|many|various)\s+(?:researchers?|studies|authors?)\s+(?:have\s+)?(?:shown?|suggest|indicate)', "vague_claim", "medium"),
    (r'\b(?:it is (?:well )?known that|as is well known)', "vague_claim", "medium"),
    (r'\betc\.?\b|\band so on\b', "vague_claim", "low"),
    (r'\b(?:recent|previous|prior)\s+(?:studies?|research|work)\b(?!.*[\[\(])', "vague_claim", "medium"),
    (r'\bdata (?:was|were) (?:collected|gathered|obtained|processed|analyzed)\b(?!.*(?:using|via|by|with|through))', "unclear_method", "high"),
    (r'\b(?:standard|conventional|typical|usual)\s+(?:method|procedure|protocol)\b(?!.*[\(\[])', "unclear_method", "medium"),
    (r'\b(?:appropriate|suitable|proper)\s+(?:statistical|analysis|method)', "unclear_method", "medium"),
    (r'\b(?:interestingly|surprisingly|unexpectedly|remarkably|notably),?\s', "logical_gap", "low"),
    (r'\b(?:leads?\s+to|causes?|results?\s+in)\b(?!.*(?:suggest|may|might|could))', "weak_causation", "medium"),
    (r'\b(?:will|always|never|all|none|every|no)\s+(?:result|show|demonstrate|produce|cause|prevent)\b', "missing_hedging", "medium"),
]
HEDGE_RE = re.compile(r'\b(?:may|might|could|suggest|appears?|potentially|possibly|indicate)\b', re.I)

def _detect(t):
    sents = re.split(r'(?<=[.!?])\s+(?=[A-Z])', t)
    alerts = []
    for s in sents:
        s = s.strip()
        if len(s) < 15: continue
        hedged = bool(HEDGE_RE.search(s))
        for pat, ty, sv in RULES:
            if re.search(pat, s, re.I):
                if ty == "overclaiming" and sv == "low" and hedged: continue
                alerts.append((ty, sv))
                break
    return alerts

def _verify_nums(o, i):
    on = set(re.findall(r'(?<!\w)[\d]+(?:\.[\d]+)?', o))
    mn = set(re.findall(r'(?<!\w)[\d]+(?:\.[\d]+)?', i))
    return on.issubset(mn)

def _verify_cites(o, i):
    cp = r'\[[^\]]*\d+[^\]]*\]|\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|and|&))?.*?\d{4}[a-z]?\)'
    oc, mc = set(re.findall(cp, o)), set(re.findall(cp, i))
    return oc.issubset(mc)

def _check_acr(t):
    common = {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "ALL", "WAS", "ONE", "OUR", "HAS"}
    acrs = {a for a in re.findall(r'\b([A-Z]{2,})\b', t) if a not in common}
    return [a for a in acrs if not re.search(rf'\w[\w\s]{{2,40}}\({re.escape(a)}\)', t) and t.count(a) > 1]

def _check_units(t):
    units = re.findall(r'\d\s*(mg|mL|ml|µL|uL|kg|g|cm|mm|µm|um|nm|°C|K)\b', t)
    seen = {}
    for u in units:
        lo = u.lower()
        if lo not in seen: seen[lo] = set()
        seen[lo].add(u)
    return {lo: vs for lo, vs in seen.items() if len(vs) > 1}

def _check_journal(t, style, section):
    issues = []
    if section == "abstract":
        wc = len(t.split())
        mx = {"nature": 150, "ieee": 200, "apa": 250, "vancouver": 250, "ama": 250, "general": 300}.get(style, 300)
        if wc > mx: issues.append(f"abstract_limit_{wc}>{mx}")
    if style in ("ieee", "vancouver"):
        if re.findall(r'[A-Z][a-z]+\s+\(\d{4}\)', t) or re.findall(r'\([A-Z][a-z]+.*?\d{4}\)', t):
            issues.append("author_date_in_numeric")
    if style == "apa":
        if re.findall(r'\[\d+\]', t):
            issues.append("numeric_in_apa")
    if re.findall(r'[pP]\s*=\s*\.\d', t):
        issues.append("pval_no_leading_zero")
    return issues

LATEX_PATTERNS = [
    (r'\$\$[\s\S]*?\$\$', 'DM'), (r'\$[^\$\n]+?\$', 'IM'),
    (r'\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}', 'ENV'),
    (r'\\(?:cite|ref|label)\{[^}]+\}', 'REF'),
    (r'\\[a-zA-Z]+(?:\{[^}]*\})*', 'CMD'),
]

def _protect_latex(t):
    ph = {}; r = t; c = 0
    for pat, pfx in LATEX_PATTERNS:
        for m in re.finditer(pat, r):
            k = f"PH{pfx}{c}"; ph[k] = m.group(0); r = r.replace(m.group(0), k, 1); c += 1
    return r, ph

def _restore_latex(t, ph):
    for k, v in ph.items(): t = t.replace(k, v)
    return t


# ═══════════════════════════════════════════════════
#  25 TEST CASES
# ═══════════════════════════════════════════════════

SAMPLES = [
    # ── Reviewer Detection: Overclaiming ──
    {"id": "R01", "cat": "reviewer", "name": "Pure overclaiming",
     "text": "Our method clearly proves that the hypothesis is correct beyond doubt.",
     "expect_issues": ["overclaiming"], "expect_no_fp": False},

    {"id": "R02", "cat": "reviewer", "name": "Subtle overclaiming with 'prove'",
     "text": "The experimental data proves that this mechanism is responsible for the observed effect.",
     "expect_issues": ["overclaiming"], "expect_no_fp": False},

    {"id": "R03", "cat": "reviewer", "name": "Novelty claim unhedged",
     "text": "We report for the first time a novel approach to gene editing in mammals.",
     "expect_issues": ["overclaiming"], "expect_no_fp": False},

    # ── Reviewer Detection: Vague Claims ──
    {"id": "R04", "cat": "reviewer", "name": "Vague attribution",
     "text": "Several researchers have shown that this technique is effective. Previous studies demonstrate its utility.",
     "expect_issues": ["vague_claim"], "expect_no_fp": False},

    {"id": "R05", "cat": "reviewer", "name": "Common knowledge without citation",
     "text": "It is well known that oxidative stress contributes to cellular damage.",
     "expect_issues": ["vague_claim"], "expect_no_fp": False},

    # ── Reviewer Detection: Unclear Methods ──
    {"id": "R06", "cat": "reviewer", "name": "Method without specificity",
     "text": "Data was collected from clinical samples. The standard method was used for analysis.",
     "expect_issues": ["unclear_method"], "expect_no_fp": False},

    # ── Reviewer Detection: Causation + Hedging ──
    {"id": "R07", "cat": "reviewer", "name": "Unhedged causation",
     "text": "Exposure to the compound leads to apoptosis in treated cells.",
     "expect_issues": ["weak_causation"], "expect_no_fp": False},

    {"id": "R08", "cat": "reviewer", "name": "Absolute language",
     "text": "This treatment will always show complete remission in patients.",
     "expect_issues": ["missing_hedging"], "expect_no_fp": False},

    # ── False Positive Tests (must NOT flag) ──
    {"id": "FP01", "cat": "false_positive", "name": "Well-hedged academic prose",
     "text": "The results suggest a possible correlation (r = 0.72, p < 0.01) between the observed variables [12]. Furthermore, the methodology employed demonstrates consistency with findings reported by Smith et al. (2023).",
     "expect_issues": [], "expect_no_fp": True},

    {"id": "FP02", "cat": "false_positive", "name": "Hedged novel claim",
     "text": "These preliminary observations may indicate a novel mechanism underlying the process.",
     "expect_issues": [], "expect_no_fp": True},

    {"id": "FP03", "cat": "false_positive", "name": "Proper methods description",
     "text": "Data was collected using high-performance liquid chromatography (HPLC) with a C18 column at 37°C [3].",
     "expect_issues": [], "expect_no_fp": True},

    {"id": "FP04", "cat": "false_positive", "name": "Complete academic abstract",
     "text": "Cellular response to environmental stress involves complex signaling cascades that remain incompletely understood. This study investigated the role of HSP70 in mediating thermotolerance in Arabidopsis thaliana. Our findings demonstrate that HSP70 modulates the expression of 47 downstream genes (FDR < 0.05), suggesting a broader role than previously appreciated.",
     "expect_issues": [], "expect_no_fp": True},

    # ── Tone Scoring ──
    {"id": "T01", "cat": "tone", "name": "Highly informal",
     "text": "Basically, we found a lot of stuff that was kind of interesting. The big thing is that this obviously shows the method is really good.",
     "tone_range": (10, 42)},

    {"id": "T02", "cat": "tone", "name": "Strong academic",
     "text": "Furthermore, the methodology demonstrates a statistically significant correlation. Subsequently, these findings suggest a previously uncharacterized pathway underlying the observed phenomenon.",
     "tone_range": (62, 100)},

    {"id": "T03", "cat": "tone", "name": "Mixed informal/academic",
     "text": "Our method is kind of new. The results showed a significant improvement in accuracy. However, more data is needed.",
     "tone_range": (35, 65)},

    # ── Readability ──
    {"id": "FR01", "cat": "readability", "name": "Simple text",
     "text": "The cat sat on the mat. The dog ran fast. The sun was hot.",
     "fre_range": (80, 100)},

    {"id": "FR02", "cat": "readability", "name": "Graduate-level academic",
     "text": "The methodology employed in this investigation demonstrates significant correlation between the observed parameters and the hypothesized outcome variables through multivariate regression analysis.",
     "fre_range": (0, 30)},

    # ── Meaning Integrity ──
    {"id": "MI01", "cat": "integrity", "name": "Number preservation",
     "text": "The accuracy was 95.3% (n = 150) with specificity of 87.2% [12, 15]. Mean temperature was 37.5°C.",
     "integrity": True},

    {"id": "MI02", "cat": "integrity", "name": "Citation preservation",
     "text": "Previous work [12] showed results consistent with findings by Chen et al. (2023).",
     "cite_check": True},

    # ── LaTeX ──
    {"id": "LX01", "cat": "latex", "name": "Inline math roundtrip",
     "text": r"The equation $E = mc^2$ and $\alpha = 0.05$ demonstrate the relationship.",
     "latex": True},

    {"id": "LX02", "cat": "latex", "name": "Display math + commands",
     "text": r"Consider $$\sum_{i=1}^{n} x_i = S$$ with \cite{smith2023} as reference. \textbf{Results} were significant.",
     "latex": True},

    # ── Terminology ──
    {"id": "TM01", "cat": "terminology", "name": "Unintroduced acronym",
     "text": "We used PCR to amplify the target DNA. The PCR results showed high yield.",
     "expect_acr": ["PCR"]},

    {"id": "TM02", "cat": "terminology", "name": "Unit inconsistency",
     "text": "Measurements were 10 mg and 15 mL and 20 ml at room temperature.",
     "expect_units": True},

    # ── Journal Compliance ──
    {"id": "JC01", "cat": "journal", "name": "IEEE wrong citation format",
     "text": "Smith (2023) showed that the algorithm works well in this context.",
     "journal": ("ieee", "general"), "expect_jnl": True},

    {"id": "JC02", "cat": "journal", "name": "APA wrong citation format",
     "text": "The method achieved 95% accuracy [12] compared to baselines.",
     "journal": ("apa", "general"), "expect_jnl": True},
]


# ═══════════════════════════════════════════════════
#  BENCHMARK RUNNER
# ═══════════════════════════════════════════════════

def run_full_benchmark():
    """Run all 25 test cases. Returns (passed, failed, details)."""
    p, f = 0, 0
    details = []

    for s in SAMPLES:
        ok, fail = [], []
        t = s["text"]

        # ── Reviewer Detection ──
        if "expect_issues" in s:
            alerts = _detect(t)
            detected = [a[0] for a in alerts]
            expected = s["expect_issues"]
            if s.get("expect_no_fp"):
                if not detected: ok.append("No false positives")
                else: fail.append(f"False positives: {detected}")
            elif expected:
                found = sum(1 for e in expected if any(e in d for d in detected))
                recall = found / len(expected)
                if recall >= 0.5: ok.append(f"Detection: {recall:.0%} ({found}/{len(expected)})")
                else: fail.append(f"Low recall: {recall:.0%} — missed from {expected}")

        # ── Tone ──
        if "tone_range" in s:
            tn = _tone(t)
            lo, hi = s["tone_range"]
            if lo <= tn <= hi: ok.append(f"Tone {tn} in [{lo},{hi}]")
            else: fail.append(f"Tone {tn} NOT in [{lo},{hi}]")

        # ── Readability ──
        if "fre_range" in s:
            fr = _readability(t)
            lo, hi = s["fre_range"]
            if lo <= fr <= hi: ok.append(f"FRE {fr} in [{lo},{hi}]")
            else: fail.append(f"FRE {fr} NOT in [{lo},{hi}]")

        # ── Integrity ──
        if s.get("integrity"):
            rw = t.replace("The accuracy", "The observed accuracy").replace("Mean", "Average mean")
            if _verify_nums(t, rw): ok.append("Numbers preserved")
            else: fail.append("Numbers LOST")

        if s.get("cite_check"):
            rw = t.replace("Previous work", "Earlier investigations").replace("showed results", "demonstrated outcomes")
            if _verify_cites(t, rw): ok.append("Citations preserved")
            else: fail.append("Citations LOST")

        # ── LaTeX ──
        if s.get("latex"):
            protected, ph = _protect_latex(t)
            restored = _restore_latex(protected, ph)
            if t == restored: ok.append(f"LaTeX roundtrip OK ({len(ph)} placeholders)")
            else: fail.append("LaTeX roundtrip FAILED")

        # ── Terminology ──
        if "expect_acr" in s:
            found = _check_acr(t)
            for ea in s["expect_acr"]:
                if ea in found: ok.append(f"Acronym '{ea}' flagged")
                else: fail.append(f"Acronym '{ea}' MISSED")

        if s.get("expect_units"):
            ui = _check_units(t)
            if ui: ok.append(f"Unit inconsistency found: {ui}")
            else: fail.append("Unit inconsistency MISSED")

        # ── Journal ──
        if s.get("journal"):
            style, sec = s["journal"]
            ji = _check_journal(t, style, sec)
            if ji: ok.append(f"Journal issue: {ji[0]}")
            else: fail.append(f"Journal issue MISSED for {style}")

        p += len(ok); f += len(fail)
        details.append({"id": s["id"], "cat": s["cat"], "name": s["name"],
                         "passed": ok, "failed": fail, "success": len(fail) == 0})

    return p, f, details


if __name__ == "__main__":
    passed, failed, details = run_full_benchmark()
    print(f"\n{'='*60}")
    print(f"  ManuscriptReady Evaluation Benchmark v2 — 25 Test Cases")
    print(f"{'='*60}\n")

    cats = {}
    for d in details:
        c = d["cat"]
        if c not in cats: cats[c] = {"pass": 0, "fail": 0, "items": []}
        cats[c]["pass"] += len(d["passed"])
        cats[c]["fail"] += len(d["failed"])
        cats[c]["items"].append(d)

    for cat, data in cats.items():
        t = data["pass"] + data["fail"]
        print(f"  [{cat.upper()}] {data['pass']}/{t} passed ({100*data['pass']//max(1,t)}%)")
        for d in data["items"]:
            st = "✅" if d["success"] else "❌"
            print(f"    {st} {d['id']}: {d['name']}")
            for x in d["passed"]: print(f"        ✓ {x}")
            for x in d["failed"]: print(f"        ✗ {x}")
        print()

    total = passed + failed
    print(f"{'='*60}")
    print(f"  TOTAL: {passed}/{total} ({100*passed//max(1,total)}%)")
    print(f"{'='*60}")
