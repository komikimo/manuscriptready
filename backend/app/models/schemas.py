"""
API Schemas — Pydantic Models
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime


# ── Auth ─────────────────────────────────
class SignupReq(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = ""
    institution: str = ""

class LoginReq(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: str; email: str; full_name: str; institution: str
    class Config:
        from_attributes = True

class AuthResp(BaseModel):
    access_token: str; token_type: str = "bearer"; user: UserOut

# ── Subscription ─────────────────────────
class SubInfo(BaseModel):
    tier: str; status: str; words_used: int; words_limit: int; words_remaining: int

class CheckoutReq(BaseModel):
    tier: Literal["starter","pro","team"]; success_url: str; cancel_url: str

# ── Reviewer Alert ───────────────────────
class ReviewerAlert(BaseModel):
    sentence: str
    issue_type: Literal["vague_claim","overclaiming","unclear_method","unsupported_conclusion",
                         "logical_gap","weak_causation","inconsistent_term","missing_hedging"]
    severity: Literal["high","medium","low"]
    explanation: str
    suggestion: str

# ── Terminology Issue ────────────────────
class TermIssue(BaseModel):
    term: str
    issue: str  # e.g. "Acronym not introduced", "Inconsistent usage"
    suggestion: str

# ── Publication Readiness Score ──────────
class PubScore(BaseModel):
    overall: float = 0        # 0-100
    clarity: float = 0        # 0-100
    academic_tone: float = 0  # 0-100
    coherence: float = 0      # 0-100
    term_consistency: float = 0
    reviewer_risk: float = 0  # 0-100 (lower = better)
    readability_fre: float = 0
    grade_level: float = 0
    label: str = ""

# ── Processing ───────────────────────────
class TextProcessReq(BaseModel):
    text: str = Field(..., min_length=10, max_length=100_000)
    mode: Literal["enhance","translate_enhance"] = "enhance"
    source_language: str = "auto"
    section_type: Literal["general","abstract","methods","results","discussion","introduction"] = "general"

class DiffItem(BaseModel):
    type: Literal["unchanged","added","removed","modified"]
    original: str = ""
    improved: str = ""

class ProcessResult(BaseModel):
    original_text: str
    improved_text: str
    diffs: List[DiffItem] = []
    score_before: PubScore = PubScore()
    score_after: PubScore = PubScore()
    reviewer_alerts: List[ReviewerAlert] = []
    terminology_issues: List[TermIssue] = []
    terms_preserved: List[str] = []
    meaning_safeguards: dict = {}  # {numbers_preserved, citations_preserved, etc.}
    section_type: str = "general"
    stats: dict = {}
    processing_time_ms: int = 0

# ── Dashboard ────────────────────────────
class DocSummary(BaseModel):
    id: str; title: str; section_type: str; word_count: int; status: str
    score_before: dict; score_after: dict; created_at: str
    class Config:
        from_attributes = True

class DashboardData(BaseModel):
    user: UserOut; subscription: SubInfo
    recent_documents: List[DocSummary] = []
    total_documents: int = 0; total_words: int = 0
