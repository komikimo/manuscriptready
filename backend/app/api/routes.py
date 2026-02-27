"""ManuscriptReady — API Routes (v2 — Complete)"""
import time, io, logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db, User, Subscription, Document
from app.models.schemas import *
from app.services.auth_service import create_user, auth_user, create_token, get_sub, current_user, require_sub
from app.services.rewrite_engine import get_rewriter
from app.services.translation_service import get_translator
from app.services.reviewer_engine import analyze_text, check_terminology
from app.services.scoring_engine import compute_score
from app.services.diff_service import compute_diffs
from app.services.docx_service import extract_docx, create_docx, extract_latex
from app.services.journal_styles import check_journal_compliance, get_available_styles
from app.services.version_history import get_version_history
from app.services.analytics import get_analytics

logger = logging.getLogger(__name__)

# ── Auth ─────────────────────────────────
auth = APIRouter(prefix="/auth", tags=["Auth"])

@auth.post("/signup", response_model=AuthResp)
async def signup(req: SignupReq, db: AsyncSession = Depends(get_db)):
    try: u = await create_user(db, req.email, req.password, req.full_name, req.institution)
    except ValueError as e: raise HTTPException(400, str(e))
    get_analytics().track(u.id, "signup", {"institution": req.institution})
    return AuthResp(access_token=create_token(u.id),
                    user=UserOut(id=u.id, email=u.email, full_name=u.full_name, institution=u.institution))

@auth.post("/login", response_model=AuthResp)
async def login(req: LoginReq, db: AsyncSession = Depends(get_db)):
    u = await auth_user(db, req.email, req.password)
    if not u: raise HTTPException(401, "Invalid credentials")
    return AuthResp(access_token=create_token(u.id),
                    user=UserOut(id=u.id, email=u.email, full_name=u.full_name, institution=u.institution))

@auth.get("/me", response_model=UserOut)
async def me(u: User = Depends(current_user)):
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, institution=u.institution)

# ── Billing ──────────────────────────────
billing = APIRouter(prefix="/billing", tags=["Billing"])

@billing.get("/subscription", response_model=SubInfo)
async def sub_info(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = await get_sub(db, u.id)
    if not s: raise HTTPException(404)
    return SubInfo(tier=s.tier, status=s.status, words_used=s.words_used,
                   words_limit=s.words_limit, words_remaining=s.words_remaining)

# ── Processing ───────────────────────────
process = APIRouter(prefix="/process", tags=["Processing"])

@process.post("/text", response_model=ProcessResult)
async def process_text(req: TextProcessReq, auth_data: tuple = Depends(require_sub),
                       db: AsyncSession = Depends(get_db)):
    user, sub = auth_data
    start = time.time()
    text = req.text.strip()
    wc = len(text.split())
    if wc > sub.words_remaining:
        raise HTTPException(403, f"Need {wc} words, have {sub.words_remaining}")

    rewriter = get_rewriter()
    translator = get_translator()
    try:
        if req.mode == "translate_enhance":
            translated, detected = await translator.translate(text, req.source_language)
            improved, stats = await rewriter.rewrite(translated, req.section_type, is_translated=True)
            stats["detected_language"] = detected
        else:
            improved, stats = await rewriter.rewrite(text, req.section_type)
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {e}")

    alerts = await analyze_text(improved, deep=sub.tier in ("pro", "team"))
    term_score, term_issues = check_terminology(improved)
    score_before = compute_score(text)
    score_after = compute_score(improved, alerts)
    score_after.term_consistency = term_score
    diffs = compute_diffs(text, improved)
    safeguards = stats.get("safeguards", {})
    elapsed_ms = int((time.time() - start) * 1000)

    sub.words_used += wc
    doc = Document(user_id=user.id, title=text[:60] + "..." if len(text) > 60 else text,
                   section_type=req.section_type, original_text=text, improved_text=improved,
                   mode=req.mode, word_count=wc,
                   score_before=score_before.model_dump(), score_after=score_after.model_dump(),
                   reviewer_alerts=[a.model_dump() for a in alerts], processing_time_ms=elapsed_ms)
    db.add(doc); await db.commit(); await db.refresh(doc)

    vh = get_version_history()
    vh.add_version(doc.id, text, "user")
    vh.add_version(doc.id, improved, f"ai_{req.mode}")
    vh.add_changes(doc.id, [d.model_dump() for d in diffs])
    get_analytics().track_processing(user.id, req.mode, req.section_type,
                                     score_before.overall, score_after.overall, len(alerts), wc, elapsed_ms)

    return ProcessResult(
        original_text=text, improved_text=improved, diffs=diffs,
        score_before=score_before, score_after=score_after,
        reviewer_alerts=alerts, terminology_issues=term_issues,
        terms_preserved=stats.get("terms_preserved", []),
        meaning_safeguards=safeguards, section_type=req.section_type,
        stats={**stats, "doc_id": doc.id}, processing_time_ms=elapsed_ms)

@process.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    data = await file.read()
    if file.filename.endswith(".tex"):
        text = extract_latex(data.decode("utf-8", errors="replace"))
    elif file.filename.endswith(".docx"):
        text, _ = extract_docx(data)
    else:
        raise HTTPException(400, "Only .docx and .tex supported")
    return {"text": text, "word_count": len(text.split()), "filename": file.filename}

@process.post("/download")
async def download(improved_text: str = Form(...)):
    return StreamingResponse(io.BytesIO(create_docx(improved_text)),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=manuscript_improved.docx"})

# ── Journal Compliance ───────────────────
journal = APIRouter(prefix="/journal", tags=["Journal Compliance"])

@journal.get("/styles")
async def list_styles():
    return {"styles": get_available_styles()}

@journal.post("/check")
async def check_compliance(text: str = Body(...), style: str = Body("general"), section: str = Body("general")):
    score, issues = check_journal_compliance(text, style, section)
    return {"score": score, "issues": [i.model_dump() for i in issues], "style": style}

# ── Version History ──────────────────────
ver = APIRouter(prefix="/versions", tags=["Versions"])

@ver.get("/{doc_id}/history")
async def history(doc_id: str, u: User = Depends(current_user)):
    return {"doc_id": doc_id, "versions": get_version_history().get_history(doc_id)}

@ver.get("/{doc_id}/changes")
async def changes(doc_id: str, u: User = Depends(current_user)):
    return {"doc_id": doc_id, "changes": get_version_history().get_changes(doc_id)}

@ver.post("/{doc_id}/accept/{idx}")
async def accept(doc_id: str, idx: int, u: User = Depends(current_user)):
    if not get_version_history().accept_change(doc_id, idx): raise HTTPException(404)
    return {"status": "accepted"}

@ver.post("/{doc_id}/reject/{idx}")
async def reject(doc_id: str, idx: int, u: User = Depends(current_user)):
    if not get_version_history().reject_change(doc_id, idx): raise HTTPException(404)
    return {"status": "rejected"}

@ver.post("/{doc_id}/accept_all")
async def accept_all(doc_id: str, u: User = Depends(current_user)):
    return {"accepted": get_version_history().accept_all(doc_id)}

@ver.post("/{doc_id}/apply")
async def apply(doc_id: str, u: User = Depends(current_user)):
    text = get_version_history().apply_decisions(doc_id)
    if not text: raise HTTPException(404)
    return {"final_text": text, "word_count": len(text.split())}

# ── Feedback ─────────────────────────────
fb = APIRouter(prefix="/feedback", tags=["Feedback"])

@fb.post("/rate")
async def rate(doc_id: str = Body(...), rating: int = Body(..., ge=1, le=5),
               helpful: bool = Body(True), comment: str = Body(""),
               u: User = Depends(current_user)):
    r = get_analytics().submit_feedback(doc_id, u.id, rating, helpful, comment)
    return {"status": "received", "feedback": r.to_dict()}

# ── Analytics ────────────────────────────
analytics_router = APIRouter(prefix="/stats", tags=["Analytics"])

@analytics_router.get("/me")
async def my_stats(u: User = Depends(current_user)):
    return get_analytics().get_stats(u.id)

# ── Evaluation ───────────────────────────
eval_router = APIRouter(prefix="/eval", tags=["Evaluation"])

@eval_router.get("/run")
async def run_eval():
    from app.services.evaluation import run_benchmarks
    passed, failed, details = run_benchmarks()
    return {"passed": passed, "failed": failed, "score_pct": round(100 * passed / max(1, passed + failed)), "details": details}

# ── Dashboard ────────────────────────────
dash = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@dash.get("/", response_model=DashboardData)
async def dashboard(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    sub = await get_sub(db, u.id)
    docs = (await db.execute(select(Document).where(Document.user_id == u.id)
            .order_by(Document.created_at.desc()).limit(20))).scalars().all()
    total = (await db.execute(select(func.count(Document.id)).where(Document.user_id == u.id))).scalar() or 0
    words = (await db.execute(select(func.sum(Document.word_count)).where(Document.user_id == u.id))).scalar() or 0
    return DashboardData(
        user=UserOut(id=u.id, email=u.email, full_name=u.full_name, institution=u.institution),
        subscription=SubInfo(tier=sub.tier, status=sub.status, words_used=sub.words_used,
                             words_limit=sub.words_limit, words_remaining=sub.words_remaining) if sub else
                     SubInfo(tier="free", status="active", words_used=0, words_limit=1000, words_remaining=1000),
        recent_documents=[DocSummary(id=d.id, title=d.title, section_type=d.section_type, word_count=d.word_count,
                                     score_before=d.score_before or {}, score_after=d.score_after or {},
                                     created_at=d.created_at.isoformat()) for d in docs],
        total_documents=total, total_words=words)
