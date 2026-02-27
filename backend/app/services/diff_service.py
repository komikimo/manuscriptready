"""Diff Service"""
import difflib, re
from typing import List
from app.models.schemas import DiffItem

def compute_diffs(orig: str, impr: str) -> List[DiffItem]:
    os = _split(orig); ims = _split(impr)
    m = difflib.SequenceMatcher(None, os, ims)
    d = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal":
            for s in os[i1:i2]: d.append(DiffItem(type="unchanged", original=s, improved=s))
        elif tag == "replace":
            a, b = os[i1:i2], ims[j1:j2]
            for k in range(max(len(a), len(b))):
                d.append(DiffItem(type="modified", original=a[k] if k<len(a) else "", improved=b[k] if k<len(b) else ""))
        elif tag == "delete":
            for s in os[i1:i2]: d.append(DiffItem(type="removed", original=s))
        elif tag == "insert":
            for s in ims[j1:j2]: d.append(DiffItem(type="added", improved=s))
    return d

def _split(t):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(\[])', t.strip()) if s.strip()] or [t.strip()]
