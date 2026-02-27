"""
ManuscriptReady — Analytics & Feedback Service
═══════════════════════════════════════════════
Tracks feature usage, score improvements, and user quality feedback.
In production: backed by DB/analytics service. Here: in-memory for MVP.
"""

from datetime import datetime, timezone
from typing import List, Optional
from collections import defaultdict


class AnalyticsEvent:
    def __init__(self, user_id: str, event_type: str, data: dict = None):
        self.user_id = user_id
        self.event_type = event_type
        self.data = data or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return {"user_id": self.user_id, "event": self.event_type,
                "data": self.data, "ts": self.timestamp}


class QualityFeedback:
    """User feedback on AI output quality."""
    def __init__(self, doc_id: str, user_id: str, rating: int,
                 helpful: bool = True, comment: str = ""):
        self.doc_id = doc_id
        self.user_id = user_id
        self.rating = rating  # 1-5
        self.helpful = helpful
        self.comment = comment
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return {"doc_id": self.doc_id, "rating": self.rating,
                "helpful": self.helpful, "comment": self.comment, "ts": self.timestamp}


class AnalyticsService:
    def __init__(self):
        self.events: List[AnalyticsEvent] = []
        self.feedback: List[QualityFeedback] = []
        self.feature_counts: dict = defaultdict(int)

    # ── Event Tracking ──
    def track(self, user_id: str, event: str, data: dict = None):
        self.events.append(AnalyticsEvent(user_id, event, data))
        self.feature_counts[event] += 1

    def track_processing(self, user_id: str, mode: str, section: str,
                         score_before: float, score_after: float,
                         alerts_count: int, word_count: int, ms: int):
        self.track(user_id, "process", {
            "mode": mode, "section": section,
            "score_before": score_before, "score_after": score_after,
            "score_delta": round(score_after - score_before, 1),
            "alerts": alerts_count, "words": word_count, "ms": ms,
        })

    def track_change_decision(self, user_id: str, doc_id: str,
                              accepted: int, rejected: int):
        self.track(user_id, "change_decision", {
            "doc_id": doc_id, "accepted": accepted, "rejected": rejected,
            "acceptance_rate": round(accepted / max(1, accepted + rejected), 2),
        })

    # ── Quality Feedback ──
    def submit_feedback(self, doc_id: str, user_id: str, rating: int,
                        helpful: bool = True, comment: str = ""):
        fb = QualityFeedback(doc_id, user_id, rating, helpful, comment)
        self.feedback.append(fb)
        self.track(user_id, "feedback", {"rating": rating, "helpful": helpful})
        return fb

    # ── Aggregated Stats ──
    def get_stats(self, user_id: Optional[str] = None) -> dict:
        events = self.events
        if user_id:
            events = [e for e in events if e.user_id == user_id]

        process_events = [e for e in events if e.event_type == "process"]
        if not process_events:
            return {"total_processes": 0}

        deltas = [e.data.get("score_delta", 0) for e in process_events]
        sections = defaultdict(int)
        modes = defaultdict(int)
        for e in process_events:
            sections[e.data.get("section", "general")] += 1
            modes[e.data.get("mode", "enhance")] += 1

        fb_ratings = [f.rating for f in self.feedback
                      if not user_id or f.user_id == user_id]

        return {
            "total_processes": len(process_events),
            "avg_score_improvement": round(sum(deltas) / max(1, len(deltas)), 1),
            "max_score_improvement": round(max(deltas) if deltas else 0, 1),
            "total_words": sum(e.data.get("words", 0) for e in process_events),
            "avg_processing_ms": round(sum(e.data.get("ms", 0) for e in process_events) / max(1, len(process_events))),
            "section_usage": dict(sections),
            "mode_usage": dict(modes),
            "feature_usage": dict(self.feature_counts),
            "feedback_count": len(fb_ratings),
            "avg_rating": round(sum(fb_ratings) / max(1, len(fb_ratings)), 1) if fb_ratings else None,
            "most_used_section": max(sections, key=sections.get) if sections else "general",
        }


_analytics = None
def get_analytics() -> AnalyticsService:
    global _analytics
    if _analytics is None:
        _analytics = AnalyticsService()
    return _analytics
