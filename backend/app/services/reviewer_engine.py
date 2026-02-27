"""
ManuscriptReady — Reviewer Intelligence Engine
════════════════════════════════════════════════
Detects issues that peer reviewers commonly flag:
  - Vague claims without citations
  - Overclaiming / absolute language
  - Unclear methodology
  - Unsupported conclusions
  - Logical gaps
  - Weak causation
  - Inconsistent terminology
  - Missing academic hedging

Two layers:
  1. Rule-based pattern matching (fast, always runs)
  2. GPT-powered deep analysis (Pro/Team tiers)
"""

import re
import json
import logging
from typing import List, Tuple
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.schemas import ReviewerAlert, TermIssue

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RULE-BASED DETECTION (always runs)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Each rule: (regex, issue_type, severity, explanation, suggestion)
RULES = [
    # ── Overclaiming ──
    (r'\b(?:clearly|obviously|undoubtedly|definitively)\s+(?:proves?|shows?|demonstrates?)\b',
     "overclaiming", "high",
     "Strong certainty claim — reviewers challenge absolute language in empirical research",
     "Use hedging: 'strongly suggests' or 'provides compelling evidence'"),

    (r'\bproves?\s+(?:that|beyond)\b',
     "overclaiming", "high",
     "'Prove' is nearly never appropriate in empirical research",
     "Replace with 'demonstrates', 'indicates', or 'provides evidence that'"),

    (r'\bfor the first time\b',
     "overclaiming", "medium",
     "Novelty claims are heavily scrutinized by reviewers",
     "Add qualifier: 'to our knowledge, for the first time...'"),

    (r'\bnovel\b(?!\s+(?:approach|method|technique|strategy))(?<!may\s+indicate\s+a\s+novel)(?<!could\s+represent\s+a\s+novel)',
     "overclaiming", "low",
     "Overuse of 'novel' — reviewers are skeptical of novelty claims",
     "Remove or justify with specific comparison to prior work"),

    # ── Vague Claims ──
    (r'\b(?:some|several|many|various)\s+(?:researchers?|studies|authors?|reports?)\s+(?:have\s+)?(?:shown?|suggest|indicate)',
     "vague_claim", "medium",
     "Vague attribution without specific citations — reviewers expect references",
     "Replace with specific citations: 'Smith et al. (2023) demonstrated...'"),

    (r'\b(?:it is (?:well )?known that|as is well known|it is generally accepted)',
     "vague_claim", "medium",
     "Unsupported common-knowledge claim — a reviewer may dispute this",
     "Add a citation or rephrase with specific evidence"),

    (r'\betc\.?\b|\band so on\b|\band so forth\b',
     "vague_claim", "low",
     "'etc.' is imprecise — reviewers prefer specificity",
     "List all items or use 'including X, Y, and Z'"),

    (r'\b(?:recent|previous|prior)\s+(?:studies?|research|work|investigations?)\b(?!.*[\[\(])',
     "vague_claim", "medium",
     "References prior work without citation",
     "Add specific citation after this claim"),

    # ── Unclear Methodology ──
    (r'\bdata (?:was|were) (?:collected|gathered|obtained|processed|analyzed)\b(?!.*(?:using|via|by|with|through))',
     "unclear_method", "high",
     "Method description lacks specificity — reviewers need HOW",
     "Specify the technique, instrument, or software used"),

    (r'\b(?:standard|conventional|typical|usual)\s+(?:method|procedure|protocol)\b(?!.*[\(\[])',
     "unclear_method", "medium",
     "References 'standard' method without naming it",
     "Name the specific method and cite the reference protocol"),

    (r'\b(?:appropriate|suitable|proper)\s+(?:statistical|analysis|method)',
     "unclear_method", "medium",
     "Vague method description — reviewers need specifics",
     "Name the exact statistical test or analytical method"),

    # ── Logical Gaps ──
    (r'\b(?:interestingly|surprisingly|unexpectedly|remarkably|notably),?\s',
     "logical_gap", "low",
     "Subjective qualifier — reviewers prefer objective statements",
     "Remove or explain WHY this is interesting with evidence"),

    # ── Weak Causation ──
    (r'\b(?:leads?\s+to|causes?|results?\s+in|gives?\s+rise\s+to)\b(?!.*(?:suggest|may|might|could))',
     "weak_causation", "medium",
     "Causal claim without hedging — may be challenged unless proven",
     "Add hedging: 'may lead to', 'is associated with', 'appears to contribute to'"),

    # ── Missing Hedging ──
    (r'\b(?:will|always|never|all|none|every|no)\s+(?:result|show|demonstrate|produce|cause|prevent)\b',
     "missing_hedging", "medium",
     "Absolute language — academic writing requires hedging for empirical claims",
     "Soften: 'will' → 'is expected to', 'always' → 'typically', 'never' → 'rarely'"),

    # ── Unsupported Conclusion ──
    (r'\b(?:therefore|thus|hence),?\s+(?:we|it|this)\s+(?:can\s+)?conclude',
     "unsupported_conclusion", "medium",
     "Conclusion statement should be directly tied to presented evidence",
     "Ensure preceding data directly supports this conclusion"),
]


def detect_rule_based(text: str) -> List[ReviewerAlert]:
    """Fast pattern-based detection of reviewer issues."""
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(\[])', text)
    alerts = []
    hedging_words = re.compile(r'\b(?:may|might|could|suggest|appears?|potentially|possibly|indicate)\b', re.I)

    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15:
            continue
        has_hedging = bool(hedging_words.search(sent))

        for pattern, itype, severity, expl, sug in RULES:
            if re.search(pattern, sent, re.IGNORECASE):
                # Skip low-severity overclaiming if sentence already has hedging
                if itype == "overclaiming" and severity == "low" and has_hedging:
                    continue
                alerts.append(ReviewerAlert(
                    sentence=sent[:200],
                    issue_type=itype,
                    severity=severity,
                    explanation=expl,
                    suggestion=sug,
                ))
                break  # One alert per sentence

    return alerts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GPT-POWERED DEEP ANALYSIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REVIEWER_PROMPT = """You are an experienced peer reviewer for a top international journal.
Identify SPECIFIC sentences that would trigger reviewer criticism.

For each issue, return JSON:
[{"sentence":"first 150 chars","issue_type":"one of: vague_claim|overclaiming|unclear_method|unsupported_conclusion|logical_gap|weak_causation|inconsistent_term|missing_hedging","severity":"high|medium|low","explanation":"why a reviewer flags this","suggestion":"how to fix"}]

If no issues: return []
Only flag genuine problems. Don't flag correct hedged statements.
Return ONLY the JSON array."""


async def detect_ai_powered(text: str) -> List[ReviewerAlert]:
    """GPT deep analysis of reviewer concerns."""
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        r = await client.chat.completions.create(
            model=settings.OPENAI_MODEL, temperature=0.1, max_tokens=2000,
            messages=[
                {"role": "system", "content": REVIEWER_PROMPT},
                {"role": "user", "content": text[:6000]},
            ],
        )
        content = r.choices[0].message.content.strip().strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
        items = json.loads(content)
        valid_types = {"vague_claim", "overclaiming", "unclear_method", "unsupported_conclusion",
                       "logical_gap", "weak_causation", "inconsistent_term", "missing_hedging"}
        return [
            ReviewerAlert(
                sentence=it.get("sentence", "")[:200],
                issue_type=it["issue_type"] if it.get("issue_type") in valid_types else "vague_claim",
                severity=it.get("severity", "medium"),
                explanation=it.get("explanation", ""),
                suggestion=it.get("suggestion", ""),
            )
            for it in items[:15]
        ]
    except Exception as e:
        logger.error(f"AI reviewer analysis failed: {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TERMINOLOGY CONSISTENCY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_terminology(text: str) -> Tuple[float, List[TermIssue]]:
    """Check acronym introduction, term consistency, units, tense."""
    issues = []
    score = 100.0

    # Acronym introduction check
    common_words = {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "ALL", "WAS", "ONE", "OUR", "HAS"}
    acronyms = {a for a in re.findall(r'\b([A-Z]{2,})\b', text) if a not in common_words}

    for acr in acronyms:
        intro = rf'\b\w[\w\s]{{2,40}}\({re.escape(acr)}\)'
        if not re.search(intro, text) and text.count(acr) > 1:
            issues.append(TermIssue(
                term=acr,
                issue="Acronym used without introduction",
                suggestion=f"First mention should be 'Full Name ({acr})'",
            ))
            score -= 5

    # Tense consistency within paragraphs
    for para in text.split("\n\n"):
        if not para.strip():
            continue
        past = len(re.findall(r'\b(?:was|were|had|showed|found|demonstrated|analyzed|measured)\b', para, re.I))
        present = len(re.findall(r'\b(?:is|are|has|shows?|finds?|demonstrates?|analyzes?)\b', para, re.I))
        if past > 2 and present > 2:
            score -= 3

    # Unit formatting consistency
    units = re.findall(r'\d\s*(mg|mL|ml|µL|uL|kg|g|cm|mm|µm|um|nm|°C|K)\b', text)
    seen = {}
    for u in units:
        low = u.lower()
        if low not in seen:
            seen[low] = set()
        seen[low].add(u)
    for low, variants in seen.items():
        if len(variants) > 1:
            issues.append(TermIssue(
                term=", ".join(sorted(variants)),
                issue="Inconsistent unit formatting",
                suggestion="Standardize to one format throughout",
            ))
            score -= 5

    return max(0, min(100, score)), issues


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COMBINED ANALYSIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def analyze_text(text: str, deep: bool = False) -> List[ReviewerAlert]:
    """Run reviewer analysis. Rules always; GPT for deep=True."""
    alerts = detect_rule_based(text)

    if deep:
        ai_alerts = await detect_ai_powered(text)
        seen = {a.sentence[:60] for a in alerts}
        for a in ai_alerts:
            if a.sentence[:60] not in seen:
                alerts.append(a)
                seen.add(a.sentence[:60])

    sev = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: sev.get(a.severity, 2))
    return alerts[:20]
