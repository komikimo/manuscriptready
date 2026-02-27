from __future__ import annotations

from typing import Dict, Any
from sqlalchemy.orm import Session

from .plan_service import get_org_plan, get_limits
from .usage_period_service import get_billing_period, aggregate_org_usage_for_period

def check_org_quota_after_increment(
    db: Session,
    org_id: str,
    add_words_rewrite: int = 0,
    add_words_translate: int = 0,
    add_docs_processed: int = 0,
    add_tokens_prompt: int = 0,
    add_tokens_completion: int = 0,
    add_cost_usd_est: float = 0.0,
) -> Dict[str, Any]:
    plan = get_org_plan(db, org_id)
    limits = get_limits(plan) if plan else {}
    period = get_billing_period(db, org_id)
    usage = aggregate_org_usage_for_period(db, org_id, period)

    projected = {
        "words_rewrite": usage["words_rewrite"] + int(add_words_rewrite or 0),
        "words_translate": usage["words_translate"] + int(add_words_translate or 0),
        "docs_processed": usage["docs_processed"] + int(add_docs_processed or 0),
        "tokens_prompt": usage["tokens_prompt"] + int(add_tokens_prompt or 0),
        "tokens_completion": usage["tokens_completion"] + int(add_tokens_completion or 0),
        "cost_usd_est": usage["cost_usd_est"] + float(add_cost_usd_est or 0.0),
    }

    words_month = int(limits.get("words_month", 10_000_000))
    docs_month = int(limits.get("docs_month", 10_000))

    projected_total_words = projected["words_rewrite"] + projected["words_translate"]

    ok = True
    reasons = []
    if projected_total_words > words_month:
        ok = False
        reasons.append("words_month_exceeded")
    if projected["docs_processed"] > docs_month:
        ok = False
        reasons.append("docs_month_exceeded")

    return {
        "ok": ok,
        "reasons": reasons,
        "plan": (plan.name if plan else "free"),
        "limits": limits,
        "period": {"start_date": str(period.start_date), "end_date": str(period.end_date)},
        "usage": usage,
        "projected": projected,
        "projected_total_words": projected_total_words,
    }
