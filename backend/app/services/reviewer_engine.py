"""
ManuscriptReady — Reviewer Intelligence Engine
════════════════════════════════════════════════
Analyzes text for issues that peer reviewers commonly flag.
Combines rule-based pattern detection with GPT-powered analysis.

Categories:
  - Vague claims ("some researchers suggest...")
  - Overclaiming ("clearly proves", "definitively shows")
  - Unclear methodology ("the data was processed")
  - Unsupported conclusions (claims without evidence/citation)
  - Logical gaps (missing connections)
  - Weak causation ("X leads to Y" without evidence)
  - Inconsistent terminology
  - Missing hedging
"""

import re
import logging
from typing import List, Tuple
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.schemas import ReviewerAlert

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RULE-BASED PATTERN DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# (pattern, issue_type, severity, explanation, suggestion_template)
PATTERNS: List[Tuple[str, str, str, str, str]] = [
    # Overclaiming
    (r'\b(?:clearly|obviously|undoubtedly|undeniably|definitively)\s+(?:proves?|shows?|demonstrates?)\b',
     "overclaiming", "high",
     "Strong claim without hedging — reviewers will question the certainty level",
     "Use hedging: 'strongly suggests' or 'provides compelling evidence for'"),

    (r'\b(?:proves?\s+(?:that|beyond))\b',
     "overclaiming", "high",
     "'Prove' is almost never appropriate in empirical research — reviewers will challenge this",
     "Replace with 'demonstrates', 'indicates', or 'provides evidence that'"),

    (r'\bfor the first time\b',
     "overclaiming", "medium",
     "Novelty claims are heavily scrutinized — reviewers will check if this is truly first",
     "Soften to 'to our knowledge, this is the first...' or verify the claim thoroughly"),

    # Vague claims
    (r'\b(?:some|several|many|various|numerous)\s+(?:researchers?|studies|authors?|reports?)\s+(?:have\s+)?(?:shown?|suggest|indicate|report)',
     "vague_claim", "medium",
     "Vague attribution — reviewers expect specific citations",
     "Replace with specific citations: 'Smith et al. (2023) demonstrated...'"),

    (r'\b(?:it is (?:well )?known that|as is well known|it is generally accepted)',
     "vague_claim", "medium",
     "Unsupported common-knowledge claim — reviewers may dispute this",
     "Add a citation or rephrase with specific evidence"),

    (r'\b(?:etc|and so on|and so forth|among others)\b',
     "vague_claim", "low",
     "'etc.' is imprecise — reviewers prefer exhaustive lists or explicit scope",
     "Either list all items or use 'including X, Y, and Z'"),

    # Unclear methodology
    (r'\bdata (?:was|were) (?:collected|gathered|obtained|processed|analyzed)\b(?!.*(?:using|via|by|with|through))',
     "unclear_method", "high",
     "Method description lacks specificity — reviewers need to know HOW",
     "Specify the method/tool/technique used for data collection/analysis"),

    (r'\b(?:standard|conventional|typical|usual|normal)\s+(?:method|procedure|protocol|technique)\b(?!.*(?:\(|\[|described))',
     "unclear_method", "medium",
     "References a 'standard' method without naming it — reviewers will ask which one",
     "Name the specific method and cite the reference protocol"),

    (r'\b(?:appropriate|suitable|proper|adequate)\s+(?:statistical|analysis|method)',
     "unclear_method", "medium",
     "Too vague — reviewers need to know the specific method used",
     "Name the exact statistical test or analytical method"),

    # Unsupported conclusions
    (r'\b(?:therefore|thus|hence|consequently|accordingly),?\s+(?:we|it|this)\s+(?:can|may|could)\s+(?:conclude|state|claim)',
     "unsupported_conclusion", "medium",
     "Conclusion should be directly tied to presented evidence",
     "Ensure the preceding sentence(s) contain supporting data or references"),

    # Logical gaps
    (r'\b(?:interestingly|surprisingly|unexpectedly|remarkably|notably),?\s',
     "logical_gap", "low",
     "Subjective qualifier — reviewers prefer objective statements",
     "Remove the qualifier or explain WHY this is interesting/surprising with evidence"),

    # Weak causation
    (r'\b(?:leads?\s+to|causes?|results?\s+in|gives?\s+rise\s+to)\b(?!.*(?:suggest|may|might|could|possibly))',
     "weak_causation", "medium",
     "Causal claim without hedging — unless proven, this may be challenged",
     "Add hedging: 'may lead to', 'is associated with', 'appears to contribute to'"),

    # Missing hedging
    (r'\b(?:will|always|never|all|none|every|no)\s+(?:result|show|demonstrate|produce|cause|prevent)\b',
     "missing_hedging", "medium",
     "Absolute language — academic writing requires hedging for empirical claims",
     "Soften: 'will' → 'is expected to', 'always' → 'typically', 'never' → 'rarely'"),
]


def detect_reviewer_issues_rules(text: str) -> List[ReviewerAlert]:
    """Fast rule-based detection of common reviewer concerns."""
    alerts = []
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(\[])', text)

    for sent in sentences:
        sent = sent.strip()
        if not sent or len(sent) < 15:
            continue

        for pattern, issue_type, severity, explanation, suggestion in PATTERNS:
            if re.search(pattern, sent, re.IGNORECASE):
                alerts.append(ReviewerAlert(
                    sentence=sent[:200],
                    issue_type=issue_type,
                    severity=severity,
                    explanation=explanation,
                    suggestion=suggestion,
                ))
                break  # One alert per sentence to avoid noise

    return alerts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GPT-POWERED DEEP ANALYSIS (for Pro/Team tiers)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REVIEWER_ANALYSIS_PROMPT = """You are an experienced peer reviewer for a top-tier international journal.
Analyze the following academic text and identify SPECIFIC sentences or phrases that would likely trigger reviewer criticism.

For each issue found, provide:
1. The exact problematic sentence (first 150 chars)
2. Issue type: one of [vague_claim, overclaiming, unclear_method, unsupported_conclusion, logical_gap, weak_causation, inconsistent_term, missing_hedging]
3. Severity: high, medium, or low
4. Brief explanation of why a reviewer would flag this
5. A specific suggestion for improvement

Format your response as a JSON array:
[
  {
    "sentence": "...",
    "issue_type": "...",
    "severity": "...",
    "explanation": "...",
    "suggestion": "..."
  }
]

If no significant issues found, return: []

Analyze ONLY what's written — do not flag correct hedged statements or well-supported claims.
Return ONLY the JSON array, nothing else."""


async def detect_reviewer_issues_ai(text: str) -> List[ReviewerAlert]:
    """GPT-powered deep analysis for reviewer concerns."""
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        # Truncate to avoid token limits
        analysis_text = text[:6000]

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            temperature=0.1,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": REVIEWER_ANALYSIS_PROMPT},
                {"role": "user", "content": analysis_text},
            ],
        )

        content = response.choices[0].message.content.strip()
        # Clean JSON
        content = content.strip("`").strip()
        if content.startswith("json"):
            content = content[4:].strip()

        import json
        items = json.loads(content)
        alerts = []
        valid_types = {"vague_claim","overclaiming","unclear_method","unsupported_conclusion",
                       "logical_gap","weak_causation","inconsistent_term","missing_hedging"}
        for item in items[:15]:  # Cap at 15 alerts
            it = item.get("issue_type", "vague_claim")
            if it not in valid_types:
                it = "vague_claim"
            alerts.append(ReviewerAlert(
                sentence=item.get("sentence", "")[:200],
                issue_type=it,
                severity=item.get("severity", "medium"),
                explanation=item.get("explanation", ""),
                suggestion=item.get("suggestion", ""),
            ))
        return alerts

    except Exception as e:
        logger.error(f"AI reviewer analysis failed: {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COMBINED ANALYSIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def analyze_reviewer_risks(text: str, deep: bool = False) -> List[ReviewerAlert]:
    """
    Combined reviewer risk analysis.
    Rules-based always runs. AI analysis for deep=True (Pro/Team tiers).
    """
    # Always run fast rules
    rule_alerts = detect_reviewer_issues_rules(text)

    if deep:
        ai_alerts = await detect_reviewer_issues_ai(text)
        # Merge, deduplicate by similarity
        seen_sentences = {a.sentence[:60] for a in rule_alerts}
        for a in ai_alerts:
            if a.sentence[:60] not in seen_sentences:
                rule_alerts.append(a)
                seen_sentences.add(a.sentence[:60])

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    rule_alerts.sort(key=lambda a: severity_order.get(a.severity, 2))

    return rule_alerts[:20]  # Cap at 20
