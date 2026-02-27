# ManuscriptReady

**AI-powered academic manuscript enhancement platform.**

ManuscriptReady helps researchers improve their papers before submission by detecting issues that journal reviewers commonly flag — overclaiming, vague methods, missing hedging, citation gaps — and suggesting precise fixes while preserving scientific integrity.

## Key Features

- **Reviewer Intelligence** — 15 detection patterns (overclaiming, vague citations, unclear methods, missing hedging) with zero false positives on well-hedged text
- **Journal Compliance** — Style checking for Nature, IEEE, APA, Vancouver, AMA, Chicago
- **Scientific Integrity** — Every number, citation, formula, and technical term verified; AI never adds claims or alters data
- **LaTeX Support** — Upload .tex/.zip, process with math preservation, export back to .tex
- **Accept/Reject Workflow** — Review each AI suggestion individually
- **Multi-Tenant SaaS** — Organization-based tenancy with role-based access (admin, lab admin, researcher)
- **Usage Metering** — Daily ledger aggregation with per-org quota enforcement
- **Stripe Billing** — Subscription checkout, webhook-verified lifecycle, invoice tracking
- **Async Processing** — Celery workers for non-blocking document processing
- **Version History** — Full document revision tracking with restore capability

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (async Python) |
| Database | PostgreSQL + SQLAlchemy |
| Worker | Celery + Redis |
| Billing | Stripe (Checkout + Webhooks) |
| Storage | S3-compatible (AWS S3 / MinIO) |
| Auth | JWT + bcrypt |
| Frontend | Next.js + React |
| Deployment | Docker Compose |

## Project Structure

```
manuscriptready/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── saas.py              # Core SaaS endpoints (docs, process, versions, download)
│   │   │   ├── billing.py           # Stripe checkout + billing portal
│   │   │   ├── stripe_webhook.py    # Webhook signature verification + subscription sync
│   │   │   ├── routes.py            # Auth + legacy processing routes
│   │   │   ├── sso.py               # Enterprise SSO scaffold (OIDC)
│   │   │   └── scim.py              # SCIM user provisioning
│   │   ├── core/
│   │   │   └── config.py            # All settings from environment variables
│   │   ├── models/
│   │   │   ├── database.py          # SQLAlchemy models + constraints + engines
│   │   │   └── schemas.py           # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── rewrite_engine.py    # GPT-4o rewrite pipeline with context chunking
│   │   │   ├── reviewer_engine.py   # 15-pattern academic reviewer intelligence
│   │   │   ├── scoring_engine.py    # 6-dimension publication readiness score
│   │   │   ├── journal_styles.py    # Journal-specific style rules (6 formats)
│   │   │   ├── latex_service.py     # LaTeX protect/restore (15 patterns)
│   │   │   ├── quota_service.py     # Org-level quota enforcement
│   │   │   ├── auth_service.py      # JWT auth + user management
│   │   │   ├── storage_service.py   # S3 upload/presigned URL generation
│   │   │   ├── analytics.py         # Usage tracking + feedback
│   │   │   └── ...
│   │   ├── worker/
│   │   │   ├── celery_app.py        # Celery configuration + beat schedule
│   │   │   └── tasks.py             # Processing tasks + retention purge
│   │   └── main.py                  # FastAPI app entry point
│   ├── alembic/                     # Database migrations
│   ├── migrations/                  # Additional migration scripts
│   ├── requirements.txt
│   ├── Dockerfile
│   └── alembic.ini
├── frontend/
│   ├── app.jsx                      # Main React application
│   ├── src/
│   │   └── api.js                   # API client (zero processing logic)
│   ├── next.config.js
│   ├── package.json
│   └── Dockerfile
├── docker/
│   └── 001_extensions.sql           # PostgreSQL extensions (pgcrypto)
├── docker-compose.yml
├── .env.example                     # ← Copy to .env and configure
├── .gitignore
└── README.md
```

## Quick Start

### Prerequisites

- Docker + Docker Compose
- An OpenAI API key (for AI processing)

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/manuscriptready.git
cd manuscriptready
cp .env.example .env
```

Edit `.env` and fill in at minimum:

```
OPENAI_API_KEY=sk-your-key
JWT_SECRET=any-random-64-character-string
SECRET_KEY=any-random-64-character-string
```

### 2. Start with Docker

```bash
docker compose up -d
```

This starts: PostgreSQL, Redis, FastAPI API, Celery worker, and Next.js frontend.

### 3. Access

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API Docs | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |

### Without Docker (local development)

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Worker (separate terminal)
celery -A app.worker.celery_app:celery_app worker --loglevel=info

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Requires PostgreSQL and Redis running locally.

## Architecture Highlights

### Security

- **Tenant isolation**: Every query filtered by `org_id`; S3 keys validated against org prefix
- **Double-enqueue prevention**: PostgreSQL partial unique index on active jobs per document
- **Stripe webhook verification**: `stripe.Webhook.construct_event()` with signature check
- **Idempotent usage metering**: `INSERT ON CONFLICT` prevents duplicate ledger entries
- **No secrets in code**: All credentials via environment variables

### Database Constraints

- `UniqueConstraint("org_id", "user_id")` on memberships
- `UniqueConstraint("org_id", "user_id", "date")` on usage ledger
- `UniqueConstraint("document_id", "version_number")` on document versions
- Partial unique index on active processing jobs per document
- `ON DELETE CASCADE` on all foreign keys

### Processing Pipeline

```
Upload .docx/.tex → Extract text → Quota precheck →
  Enqueue Celery job (ID only, no text in Redis) →
    Worker reads text from DB → GPT-4o rewrite →
      Reviewer analysis (15 patterns) → Score computation →
        Save results → Bump usage ledger (success only)
```

## API Endpoints (Key)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/saas/docs` | Create document |
| POST | `/api/v1/saas/docs/{id}/upload` | Upload .docx/.tex |
| POST | `/api/v1/saas/process` | Enqueue AI processing |
| GET | `/api/v1/saas/jobs/{id}` | Check job status |
| POST | `/api/v1/saas/download` | Get signed download URL |
| GET | `/api/v1/saas/docs/{id}/versions` | Version history |
| GET | `/api/v1/saas/orgs/{id}/usage` | Org usage stats |
| POST | `/api/v1/billing/checkout-session` | Stripe checkout |
| POST | `/stripe/webhook` | Stripe webhook receiver |

Full interactive docs available at `/docs` when running.

## Environment Variables

See `.env.example` for the complete list. Required variables:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o |
| `JWT_SECRET` | Random string for JWT signing |
| `SECRET_KEY` | App secret key |
| `DATABASE_URL` | PostgreSQL connection string |

## Evaluation

The project includes a 25-test evaluation framework (`app/services/evaluation_v2.py`) covering:

- Reviewer detection recall (overclaiming, vague methods, missing hedging)
- False positive rate (zero tolerance on clean text)
- Tone score calibration (informal / academic / mixed)
- Readability calibration (Flesch Reading Ease)
- Meaning integrity (number + citation preservation)
- LaTeX roundtrip fidelity
- Terminology detection (acronyms, units)
- Journal compliance detection

## License

Proprietary. All rights reserved.
