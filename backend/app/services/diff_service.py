"""Diff Comparison Service"""
import difflib, re
from typing import List
from app.models.schemas import DiffItem

def compute_diffs(original: str, improved: str) -> List[DiffItem]:
    os = _split(original); ims = _split(improved)
    m = difflib.SequenceMatcher(None, os, ims)
    diffs = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal":
            for s in os[i1:i2]: diffs.append(DiffItem(type="unchanged", original=s, improved=s))
        elif tag == "replace":
            a, b = os[i1:i2], ims[j1:j2]
            for k in range(max(len(a), len(b))):
                diffs.append(DiffItem(type="modified", original=a[k] if k<len(a) else "", improved=b[k] if k<len(b) else ""))
        elif tag == "delete":
            for s in os[i1:i2]: diffs.append(DiffItem(type="removed", original=s))
        elif tag == "insert":
            for s in ims[j1:j2]: diffs.append(DiffItem(type="added", improved=s))
    return diffs

def _split(t):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(\[])', t.strip()) if s.strip()] or [t.strip()]
