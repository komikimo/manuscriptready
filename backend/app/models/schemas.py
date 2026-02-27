"""API Schemas"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal

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

class SubInfo(BaseModel):
    tier: str; status: str; words_used: int; words_limit: int; words_remaining: int

class ReviewerAlert(BaseModel):
    sentence: str
    issue_type: str
    severity: Literal["high", "medium", "low"]
    explanation: str
    suggestion: str

class TermIssue(BaseModel):
    term: str; issue: str; suggestion: str

class PubScore(BaseModel):
    overall: float = 0
    clarity: float = 0
    academic_tone: float = 0
    coherence: float = 0
    term_consistency: float = 0
    reviewer_risk: float = 0
    readability_fre: float = 0
    grade_level: float = 0
    label: str = ""

class TextProcessReq(BaseModel):
    text: str = Field(..., min_length=10, max_length=100_000)
    mode: Literal["enhance", "translate_enhance"] = "enhance"
    source_language: str = "auto"
    section_type: Literal["general", "abstract", "methods", "results",
                           "discussion", "introduction"] = "general"

class DiffItem(BaseModel):
    type: Literal["unchanged", "added", "removed", "modified"]
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
    meaning_safeguards: dict = {}
    section_type: str = "general"
    stats: dict = {}
    processing_time_ms: int = 0

class DocSummary(BaseModel):
    id: str; title: str; section_type: str; word_count: int
    score_before: dict; score_after: dict; created_at: str
    class Config:
        from_attributes = True

class DashboardData(BaseModel):
    user: UserOut; subscription: SubInfo
    recent_documents: List[DocSummary] = []
    total_documents: int = 0; total_words: int = 0
