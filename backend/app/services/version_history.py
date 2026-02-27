"""
ManuscriptReady — Version History & Change Tracking
════════════════════════════════════════════════════
Stores document revisions, enables accept/reject per change,
and maintains full edit history.
"""

import time
from typing import List, Optional
from datetime import datetime, timezone


class Change:
    """Single tracked change with accept/reject state."""
    def __init__(self, idx: int, original: str, improved: str, change_type: str = "modified"):
        self.idx = idx
        self.original = original
        self.improved = improved
        self.change_type = change_type  # modified, added, removed
        self.status = "pending"  # pending, accepted, rejected
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def accept(self):
        self.status = "accepted"

    def reject(self):
        self.status = "rejected"

    def to_dict(self):
        return {
            "idx": self.idx,
            "original": self.original,
            "improved": self.improved,
            "change_type": self.change_type,
            "status": self.status,
            "timestamp": self.timestamp,
        }


class DocumentVersion:
    """A single version/revision of a document."""
    def __init__(self, version_id: int, text: str, source: str = "user"):
        self.version_id = version_id
        self.text = text
        self.source = source  # user, ai_enhance, ai_translate, user_edit
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.changes: List[Change] = []

    def to_dict(self):
        return {
            "version_id": self.version_id,
            "text_preview": self.text[:200] + ("..." if len(self.text) > 200 else ""),
            "word_count": len(self.text.split()),
            "source": self.source,
            "created_at": self.created_at,
            "changes_count": len(self.changes),
            "accepted": sum(1 for c in self.changes if c.status == "accepted"),
            "rejected": sum(1 for c in self.changes if c.status == "rejected"),
            "pending": sum(1 for c in self.changes if c.status == "pending"),
        }


class VersionHistory:
    """
    Manages version history for a document.
    In production: backed by DB. Here: in-memory for MVP.
    """
    def __init__(self):
        self.versions: dict[str, List[DocumentVersion]] = {}  # doc_id -> versions

    def add_version(self, doc_id: str, text: str, source: str = "user") -> DocumentVersion:
        if doc_id not in self.versions:
            self.versions[doc_id] = []
        vid = len(self.versions[doc_id]) + 1
        v = DocumentVersion(vid, text, source)
        self.versions[doc_id].append(v)
        return v

    def add_changes(self, doc_id: str, diffs: list) -> Optional[DocumentVersion]:
        """Add tracked changes from a diff result."""
        if doc_id not in self.versions or not self.versions[doc_id]:
            return None
        latest = self.versions[doc_id][-1]
        for i, d in enumerate(diffs):
            if d.get("type") in ("modified", "added", "removed"):
                latest.changes.append(Change(
                    idx=i,
                    original=d.get("original", ""),
                    improved=d.get("improved", ""),
                    change_type=d.get("type", "modified"),
                ))
        return latest

    def accept_change(self, doc_id: str, change_idx: int) -> bool:
        if doc_id not in self.versions or not self.versions[doc_id]:
            return False
        latest = self.versions[doc_id][-1]
        for c in latest.changes:
            if c.idx == change_idx:
                c.accept()
                return True
        return False

    def reject_change(self, doc_id: str, change_idx: int) -> bool:
        if doc_id not in self.versions or not self.versions[doc_id]:
            return False
        latest = self.versions[doc_id][-1]
        for c in latest.changes:
            if c.idx == change_idx:
                c.reject()
                return True
        return False

    def accept_all(self, doc_id: str) -> int:
        if doc_id not in self.versions or not self.versions[doc_id]:
            return 0
        count = 0
        for c in self.versions[doc_id][-1].changes:
            if c.status == "pending":
                c.accept()
                count += 1
        return count

    def apply_decisions(self, doc_id: str) -> str:
        """Build final text by applying accepted changes, keeping original for rejected."""
        if doc_id not in self.versions or not self.versions[doc_id]:
            return ""
        latest = self.versions[doc_id][-1]
        parts = []
        change_map = {c.idx: c for c in latest.changes}

        for c in latest.changes:
            if c.status == "accepted":
                parts.append(c.improved)
            else:  # rejected or pending
                parts.append(c.original)

        return " ".join(p for p in parts if p)

    def get_history(self, doc_id: str) -> List[dict]:
        if doc_id not in self.versions:
            return []
        return [v.to_dict() for v in self.versions[doc_id]]

    def get_changes(self, doc_id: str) -> List[dict]:
        if doc_id not in self.versions or not self.versions[doc_id]:
            return []
        return [c.to_dict() for c in self.versions[doc_id][-1].changes]


# Singleton
_history = None
def get_version_history() -> VersionHistory:
    global _history
    if _history is None:
        _history = VersionHistory()
    return _history
