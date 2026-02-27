"""
ManuscriptReady — Journal Style Compliance Engine
══════════════════════════════════════════════════
Checks manuscript against journal-specific formatting rules.
Supports: Nature, IEEE, APA, Vancouver, AMA, Chicago, General.
"""

import re
from typing import List, Tuple
from app.models.schemas import TermIssue


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  JOURNAL STYLE DEFINITIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

JOURNAL_STYLES = {
    "nature": {
        "name": "Nature",
        "citation_format": "numeric_superscript",  # superscript numbers
        "citation_regex": r'\b(?:\d+(?:,\s*\d+)*)\b',  # simplified
        "abstract_max_words": 150,
        "title_max_words": None,
        "rules": [
            ("no_first_person_abstract", r'\b(?:we|our|I)\b', "abstract",
             "Nature abstracts avoid first person", "Use passive voice or 'this study'"),
            ("active_voice_preferred", None, "general",
             "Nature prefers active voice in main text", "Consider active voice where appropriate"),
            ("no_jargon_abstract", None, "abstract",
             "Nature requires accessible abstract language", "Simplify technical jargon"),
        ],
    },
    "ieee": {
        "name": "IEEE",
        "citation_format": "numeric_bracket",  # [1], [2-4]
        "citation_regex": r'\[\d+(?:\s*[-–,]\s*\d+)*\]',
        "abstract_max_words": 200,
        "title_max_words": None,
        "rules": [
            ("ieee_citation_format", r'\(\s*\d+\s*\)', None,
             "IEEE uses bracketed citations [1], not parenthetical (1)", "Change to [n] format"),
            ("equation_numbering", r'\$\$.*\$\$(?!.*\(\d+\))', None,
             "IEEE requires numbered equations", "Add equation numbers in parentheses"),
        ],
    },
    "apa": {
        "name": "APA 7th Edition",
        "citation_format": "author_date",  # (Author, 2024)
        "citation_regex": r'\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&|and)\s+[A-Z][a-z]+)?,\s*\d{4}[a-z]?\)',
        "abstract_max_words": 250,
        "title_max_words": 12,
        "rules": [
            ("apa_no_numeric_citations", r'\[\d+\]', None,
             "APA uses author-date format, not numeric", "Change to (Author, Year) format"),
            ("apa_et_al_rule", r'\([A-Z][a-z]+,\s+[A-Z][a-z]+,\s+[A-Z][a-z]+.*?,\s*\d{4}\)', None,
             "APA: 3+ authors should use 'et al.' from first citation", "Use 'FirstAuthor et al., Year'"),
            ("apa_serial_comma", None, None,
             "APA requires serial (Oxford) comma", "Add comma before 'and' in lists of 3+"),
        ],
    },
    "vancouver": {
        "name": "Vancouver",
        "citation_format": "numeric_bracket",  # same as IEEE
        "citation_regex": r'\[\d+(?:\s*[-–,]\s*\d+)*\]',
        "abstract_max_words": 250,
        "title_max_words": None,
        "rules": [
            ("vancouver_numeric", r'\([A-Z][a-z]+.*?\d{4}\)', None,
             "Vancouver uses numeric citations [1], not author-date", "Change to [n] format"),
        ],
    },
    "ama": {
        "name": "AMA (Medical)",
        "citation_format": "numeric_superscript",
        "citation_regex": r'\b\d+\b',
        "abstract_max_words": 250,
        "title_max_words": None,
        "rules": [
            ("ama_abbreviation_first_use", None, None,
             "AMA requires abbreviation spelled out at first use", "Expand abbreviation on first mention"),
            ("ama_p_value_format", r'p\s*=\s*\.\d', None,
             "AMA: p-values should have leading zero (p = 0.05, not p = .05)",
             "Add leading zero: P = 0.05"),
        ],
    },
    "general": {
        "name": "General Academic",
        "citation_format": "any",
        "citation_regex": r'\[\d+\]|\([A-Z][a-z]+.*?\d{4}\)',
        "abstract_max_words": 300,
        "title_max_words": None,
        "rules": [],
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COMPLIANCE CHECKER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_journal_compliance(
    text: str, journal: str = "general", section: str = "general"
) -> Tuple[float, List[TermIssue]]:
    """
    Check text against journal-specific style rules.
    Returns (score 0-100, list of issues).
    """
    style = JOURNAL_STYLES.get(journal, JOURNAL_STYLES["general"])
    issues = []
    score = 100.0

    # ── Abstract word limit ──
    if section == "abstract":
        wc = len(text.split())
        max_wc = style.get("abstract_max_words")
        if max_wc and wc > max_wc:
            issues.append(TermIssue(
                term=f"{wc} words",
                issue=f"{style['name']} abstracts should be ≤{max_wc} words (you have {wc})",
                suggestion=f"Reduce abstract to {max_wc} words or fewer",
            ))
            score -= 10

    # ── Citation format check ──
    if style["citation_format"] != "any":
        wrong_cites = _check_citation_format(text, style)
        for wc in wrong_cites:
            issues.append(wc)
            score -= 5

    # ── Journal-specific rules ──
    for rule_name, pattern, rule_section, explanation, suggestion in style.get("rules", []):
        if rule_section and rule_section != section and rule_section != "general":
            continue
        if pattern and re.search(pattern, text, re.IGNORECASE):
            issues.append(TermIssue(
                term=rule_name.replace("_", " ").title(),
                issue=explanation,
                suggestion=suggestion,
            ))
            score -= 5

    # ── Universal checks ──
    universal = _check_universal(text, section)
    issues.extend(universal)
    score -= len(universal) * 3

    # ── P-value formatting ──
    bad_pvals = re.findall(r'[pP]\s*=\s*\.\d', text)
    if bad_pvals:
        issues.append(TermIssue(
            term="p-value format",
            issue="p-values should include leading zero (0.05 not .05)",
            suggestion="Change to P = 0.05 format",
        ))
        score -= 5

    # ── Figure/Table reference format ──
    if re.search(r'\b(?:fig|figure)\b(?!ure)', text, re.I):
        issues.append(TermIssue(
            term="Figure abbreviation",
            issue="Inconsistent figure abbreviation ('Fig' vs 'Figure')",
            suggestion="Use 'Figure' in full or 'Fig.' consistently",
        ))
        score -= 3

    return max(0, min(100, score)), issues


def _check_citation_format(text: str, style: dict) -> List[TermIssue]:
    """Check if citations match the expected format."""
    issues = []
    fmt = style["citation_format"]

    if fmt in ("numeric_bracket", "numeric_superscript"):
        # Should NOT have author-date: (Author, Year) or Author (Year)
        author_date = re.findall(
            r'\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&|and)\s+[A-Z][a-z]+)?,\s*\d{4}[a-z]?\)', text
        )
        # Also catch "Author (Year)" format (no comma inside parens)
        author_paren = re.findall(r'[A-Z][a-z]+\s+\(\d{4}[a-z]?\)', text)
        all_author = author_date + author_paren
        if all_author:
            issues.append(TermIssue(
                term=all_author[0][:50],
                issue=f"{style['name']} uses numeric citations, not author-date",
                suggestion="Change to numeric format: [1] or superscript",
            ))

    elif fmt == "author_date":
        # Should NOT have numeric brackets
        numeric = re.findall(r'\[\d+(?:\s*[-–,]\s*\d+)*\]', text)
        if numeric:
            issues.append(TermIssue(
                term=numeric[0],
                issue=f"{style['name']} uses author-date citations, not numeric",
                suggestion="Change to (Author, Year) format",
            ))

    return issues


def _check_universal(text: str, section: str) -> List[TermIssue]:
    """Checks that apply regardless of journal."""
    issues = []

    # Orphan citation check
    cites_in_text = set(re.findall(r'\[(\d+)\]', text))
    if cites_in_text and len(cites_in_text) > 0:
        nums = sorted(int(c) for c in cites_in_text)
        for i in range(1, max(nums)):
            if i not in set(nums) and i < max(nums):
                issues.append(TermIssue(
                    term=f"[{i}]",
                    issue=f"Citation [{i}] appears to be missing (gap in sequence)",
                    suggestion=f"Check that citation [{i}] exists in the text",
                ))
                break  # Report only first gap

    # Double space check
    if "  " in text.replace("\n", ""):
        issues.append(TermIssue(
            term="Double spaces",
            issue="Multiple consecutive spaces found",
            suggestion="Replace with single spaces",
        ))

    return issues


def get_available_styles() -> List[dict]:
    """Return list of supported journal styles for UI dropdown."""
    return [
        {"id": k, "name": v["name"], "citation": v["citation_format"],
         "abstract_limit": v.get("abstract_max_words")}
        for k, v in JOURNAL_STYLES.items()
    ]
