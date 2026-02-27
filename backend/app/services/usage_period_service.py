from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from ..models.database import UsageLedgerDaily, Subscription

@dataclass(frozen=True)
class BillingPeriod:
    start_date: date
    end_date: date  # inclusive

def _calendar_month_period(now: Optional[datetime] = None) -> BillingPeriod:
    now = now or datetime.now(timezone.utc)
    start = date(now.year, now.month, 1)
    if now.month == 12:
        next_month = date(now.year + 1, 1, 1)
    else:
        next_month = date(now.year, now.month + 1, 1)
    end = date.fromordinal(next_month.toordinal() - 1)
    return BillingPeriod(start_date=start, end_date=end)

def get_billing_period(db: Session, org_id: str) -> BillingPeriod:
    # Scaffold: UTC calendar month. Replace with Stripe period once subscription table exists.
    return _calendar_month_period()

def aggregate_org_usage_for_period(db: Session, org_id: str, period: BillingPeriod):
    q = db.query(
        func.coalesce(func.sum(UsageLedgerDaily.words_rewrite), 0),
        func.coalesce(func.sum(UsageLedgerDaily.words_translate), 0),
        func.coalesce(func.sum(UsageLedgerDaily.docs_processed), 0),
        func.coalesce(func.sum(UsageLedgerDaily.tokens_prompt), 0),
        func.coalesce(func.sum(UsageLedgerDaily.tokens_completion), 0),
        func.coalesce(func.sum(UsageLedgerDaily.cost_usd_est), 0),
    ).filter(
        UsageLedgerDaily.org_id == org_id,
        UsageLedgerDaily.date >= period.start_date,
        UsageLedgerDaily.date <= period.end_date,
    )
    wr, wt, docs, tp, tc, cost = q.one()
    return {
        "words_rewrite": int(wr),
        "words_translate": int(wt),
        "docs_processed": int(docs),
        "tokens_prompt": int(tp),
        "tokens_completion": int(tc),
        "cost_usd_est": float(cost or 0),
    }
