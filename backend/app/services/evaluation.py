"""
ManuscriptReady — Evaluation & Benchmarking Framework
═════════════════════════════════════════════════════
Contains:
  1. Sample academic texts with known issues (ground truth)
  2. Scoring validation framework
  3. Reviewer detection accuracy measurement
  4. Rewrite quality checks

Run: python -m app.services.evaluation
"""

from typing import List, Tuple
from app.services.scoring_engine import compute_score, readability, tone_score
from app.services.reviewer_engine import detect_rule_based
from app.services.rewrite_engine import verify_integrity, extract_terms, protect_latex, restore_latex


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EVALUATION DATASET — Known academic text samples
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EVAL_SAMPLES = [
    {
        "id": "E01",
        "name": "Heavy overclaiming + vague citations",
        "text": "Our method clearly proves that the new algorithm is superior. Some researchers have shown similar results. The data was collected and analyzed. This obviously demonstrates that our approach is the best.",
        "expected_issues": ["overclaiming", "vague_claim", "unclear_method", "overclaiming"],
        "expected_tone_range": (20, 55),  # Should be low-mid (informal + overclaiming)
        "expected_fre_range": (40, 90),   # Relatively readable
    },
    {
        "id": "E02",
        "name": "Well-hedged academic text",
        "text": "The results suggest a possible correlation (r = 0.72, p < 0.01) between the observed variables [12]. Furthermore, the methodology employed in this investigation demonstrates consistency with previous findings reported by Smith et al. (2023). These preliminary observations may indicate a novel mechanism underlying the process.",
        "expected_issues": [],  # Should NOT trigger false positives
        "expected_tone_range": (55, 95),  # Should be high (proper academic)
        "expected_fre_range": (10, 45),   # Academic difficulty
    },
    {
        "id": "E03",
        "name": "Mixed issues — methods + causation",
        "text": "Data was collected from 150 subjects. The standard method was used for analysis. The treatment leads to improved outcomes in all patients. Interestingly, the results will always show this pattern.",
        "expected_issues": ["unclear_method", "unclear_method", "weak_causation", "missing_hedging"],
        "expected_tone_range": (30, 60),
        "expected_fre_range": (50, 90),
    },
    {
        "id": "E04",
        "name": "LaTeX content preservation",
        "text": r"The equation $E = mc^2$ demonstrates the relationship. Given $\alpha = 0.05$, we computed the confidence interval. The result $p < 0.001$ was significant.",
        "expected_terms": ["E", "mc"],
        "latex_test": True,
    },
    {
        "id": "E05",
        "name": "Number/citation preservation",
        "text": "The accuracy was 95.3% (n = 150) with a specificity of 87.2% [12, 15]. The mean temperature was 37.5°C across all conditions.",
        "expected_numbers": ["95.3", "150", "87.2", "12", "15", "37.5"],
        "integrity_test": True,
    },
    {
        "id": "E06",
        "name": "Informal writing needing rewrite",
        "text": "Basically, we found a lot of stuff that was kind of interesting. The big thing is that this obviously shows the method is really good. In order to make use of the data, we carried out some experiments.",
        "expected_issues": ["vague_claim", "missing_hedging"],
        "expected_tone_range": (10, 40),  # Very informal
    },
    {
        "id": "E07",
        "name": "Terminology consistency issues",
        "text": "We used PCR to amplify the target DNA. The PCR results showed high yield. Later, polymerase chain reaction was mentioned again. Measurements were 10 mg and 15 mL and 20 ml.",
        "expected_term_issues": ["PCR"],  # Used without introduction
        "expected_unit_issues": True,  # mL vs ml
    },
    {
        "id": "E08",
        "name": "Perfect academic abstract",
        "text": "Cellular response to environmental stress involves complex signaling cascades that remain incompletely understood. This study investigated the role of heat shock protein 70 (HSP70) in mediating thermotolerance in Arabidopsis thaliana. Using a combination of transcriptomic profiling and targeted mutagenesis, we identified a previously uncharacterized regulatory pathway. Our findings demonstrate that HSP70 modulates the expression of 47 downstream genes (FDR < 0.05), suggesting a broader role than previously appreciated. These results provide a foundation for future studies on stress adaptation mechanisms in crop species.",
        "expected_issues": [],  # Well-written, should pass clean
        "expected_tone_range": (65, 100),
        "expected_fre_range": (5, 35),
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BENCHMARK RUNNER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BenchmarkResult:
    def __init__(self, sample_id: str, name: str):
        self.sample_id = sample_id
        self.name = name
        self.passed = []
        self.failed = []

    @property
    def success(self):
        return len(self.failed) == 0

    def to_dict(self):
        return {
            "id": self.sample_id,
            "name": self.name,
            "passed": self.passed,
            "failed": self.failed,
            "success": self.success,
        }


def run_benchmarks() -> Tuple[int, int, List[dict]]:
    """Run all evaluation benchmarks. Returns (passed, failed, details)."""
    results = []
    total_pass, total_fail = 0, 0

    for sample in EVAL_SAMPLES:
        r = BenchmarkResult(sample["id"], sample["name"])
        text = sample["text"]

        # ── Reviewer detection accuracy ──
        if "expected_issues" in sample:
            alerts = detect_rule_based(text)
            detected_types = [a.issue_type for a in alerts]
            expected = sample["expected_issues"]

            if not expected:  # Expect clean — no false positives
                if len(detected_types) == 0:
                    r.passed.append(f"No false positives (correct)")
                else:
                    r.failed.append(f"False positives: {detected_types}")
            else:
                found = 0
                for exp in expected:
                    if any(exp in dt for dt in detected_types):
                        found += 1
                recall = found / len(expected) if expected else 1
                if recall >= 0.5:
                    r.passed.append(f"Issue detection recall: {recall:.0%} ({found}/{len(expected)})")
                else:
                    r.failed.append(f"Low recall: {recall:.0%} ({found}/{len(expected)}) — missed: {set(expected) - set(detected_types)}")

        # ── Tone scoring ──
        if "expected_tone_range" in sample:
            tone = tone_score(text)
            lo, hi = sample["expected_tone_range"]
            if lo <= tone <= hi:
                r.passed.append(f"Tone score {tone} in expected range [{lo}-{hi}]")
            else:
                r.failed.append(f"Tone score {tone} outside range [{lo}-{hi}]")

        # ── Readability ──
        if "expected_fre_range" in sample:
            fre = readability(text)["fre"]
            lo, hi = sample["expected_fre_range"]
            if lo <= fre <= hi:
                r.passed.append(f"FRE {fre} in expected range [{lo}-{hi}]")
            else:
                r.failed.append(f"FRE {fre} outside range [{lo}-{hi}]")

        # ── LaTeX protection ──
        if sample.get("latex_test"):
            protected, placeholders = protect_latex(text)
            restored = restore_latex(protected, placeholders)
            if text == restored:
                r.passed.append(f"LaTeX protect/restore roundtrip OK ({len(placeholders)} placeholders)")
            else:
                r.failed.append("LaTeX roundtrip FAILED — text changed after restore")

        # ── Integrity check ──
        if sample.get("integrity_test"):
            # Simulate a good rewrite that preserves numbers
            good_rewrite = text.replace("The accuracy", "The observed accuracy").replace("The mean", "The average mean")
            report = verify_integrity(text, good_rewrite)
            if report["numbers"]:
                r.passed.append("Number preservation check passed")
            else:
                r.failed.append(f"Numbers lost: {report['issues']}")

        # ── Terminology ──
        if "expected_term_issues" in sample:
            from app.services.reviewer_engine import check_terminology
            score, issues = check_terminology(text)
            expected_terms = sample["expected_term_issues"]
            found_terms = [i.term for i in issues]
            for et in expected_terms:
                if any(et in ft for ft in found_terms):
                    r.passed.append(f"Terminology issue '{et}' detected")
                else:
                    r.failed.append(f"Terminology issue '{et}' NOT detected")

        if sample.get("expected_unit_issues"):
            from app.services.reviewer_engine import check_terminology
            _, issues = check_terminology(text)
            unit_issues = [i for i in issues if "unit" in i.issue.lower()]
            if unit_issues:
                r.passed.append("Unit inconsistency detected")
            else:
                r.failed.append("Unit inconsistency NOT detected")

        total_pass += len(r.passed)
        total_fail += len(r.failed)
        results.append(r.to_dict())

    return total_pass, total_fail, results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  READABILITY CALIBRATION FOR ACADEMIC TEXT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Academic-calibrated readability labels
# Standard Flesch is misleading for academic text
# These ranges are calibrated from analysis of published papers:
ACADEMIC_FRE_LABELS = {
    (0, 15): ("Expert-level", "Typical for medical/legal journals — appropriate for specialists"),
    (15, 30): ("Graduate", "Standard for most research journals — appropriate for field experts"),
    (30, 45): ("Advanced Undergrad", "Accessible to senior students — good for review articles"),
    (45, 60): ("Accessible", "Readable by broad audience — good for science communication"),
    (60, 100): ("General Audience", "May be too simple for a research journal"),
}


def academic_readability_label(fre: float) -> Tuple[str, str]:
    """Return academic-calibrated readability label and description."""
    for (lo, hi), (label, desc) in ACADEMIC_FRE_LABELS.items():
        if lo <= fre < hi:
            return label, desc
    return "Unknown", ""


if __name__ == "__main__":
    passed, failed, details = run_benchmarks()
    print(f"\n{'='*50}")
    print(f"  ManuscriptReady Evaluation Benchmark")
    print(f"{'='*50}\n")
    for d in details:
        status = "✅" if d["success"] else "❌"
        print(f"{status} {d['id']}: {d['name']}")
        for p in d["passed"]:
            print(f"    ✓ {p}")
        for f in d["failed"]:
            print(f"    ✗ {f}")
        print()
    print(f"{'='*50}")
    print(f"  TOTAL: {passed} passed, {failed} failed")
    print(f"  Score: {passed}/{passed+failed} ({100*passed/(passed+failed):.0f}%)")
    print(f"{'='*50}")
