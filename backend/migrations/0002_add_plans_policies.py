"""0002_add_plans_policies"""
from sqlalchemy import text

def upgrade(db):
    db.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))

    db.execute(text("""
    CREATE TABLE IF NOT EXISTS plans (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(64) UNIQUE NOT NULL,
        stripe_price_id VARCHAR(128),
        limits_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """))

    db.execute(text("""
    CREATE TABLE IF NOT EXISTS org_settings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID UNIQUE NOT NULL,
        admins_can_access_content BOOLEAN NOT NULL DEFAULT FALSE,
        domain_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
        auto_join_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """))

    db.execute(text("""
    CREATE TABLE IF NOT EXISTS doc_admin_grants (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        document_id UUID NOT NULL,
        org_id UUID NOT NULL,
        granted_by_user_id UUID NOT NULL,
        granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_doc_admin_grant UNIQUE (document_id, org_id)
    );
    """))

    # Seed default plans (monthly limits + retention_days)
    db.execute(text("""
    INSERT INTO plans (name, limits_json)
    VALUES
      ('free', '{"words_month": 10000, "docs_month": 5, "concurrency": 1, "max_doc_words": 20000, "retention_days": 30}'::jsonb),
      ('student', '{"words_month": 80000, "docs_month": 25, "concurrency": 2, "max_doc_words": 60000, "retention_days": 180}'::jsonb),
      ('researcher', '{"words_month": 200000, "docs_month": 60, "concurrency": 3, "max_doc_words": 120000, "retention_days": 365}'::jsonb),
      ('lab', '{"words_month": 1000000, "docs_month": 300, "concurrency": 8, "max_doc_words": 200000, "retention_days": 730, "included_seats": 5}'::jsonb),
      ('institutional', '{"words_month": 10000000, "docs_month": 3000, "concurrency": 30, "max_doc_words": 400000, "retention_days": 2555, "included_seats": 50, "auto_join_supported": true}'::jsonb)
    ON CONFLICT (name) DO NOTHING;
    """))

def downgrade(db):
    db.execute(text("DROP TABLE IF EXISTS doc_admin_grants;"))
    db.execute(text("DROP TABLE IF EXISTS org_settings;"))
    db.execute(text("DROP TABLE IF EXISTS plans;"))
