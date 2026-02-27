"""0005_add_sso_scim"""
from sqlalchemy import text

def upgrade(db):
    db.execute(text("""
    CREATE TABLE IF NOT EXISTS sso_connections (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID UNIQUE NOT NULL,
        provider VARCHAR(32) NOT NULL,
        oidc_config JSONB,
        saml_config JSONB,
        is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """))
    db.execute(text("""
    CREATE TABLE IF NOT EXISTS external_identities (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        provider VARCHAR(32) NOT NULL,
        subject VARCHAR(256) NOT NULL,
        email VARCHAR(256),
        org_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_external_identity UNIQUE (provider, subject)
    );
    """))
    db.execute(text("""
    CREATE TABLE IF NOT EXISTS scim_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID UNIQUE NOT NULL,
        token_hash VARCHAR(256) NOT NULL,
        created_by_user_id UUID NOT NULL,
        is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """))
def downgrade(db):
    db.execute(text("DROP TABLE IF EXISTS scim_tokens;"))
    db.execute(text("DROP TABLE IF EXISTS external_identities;"))
    db.execute(text("DROP TABLE IF EXISTS sso_connections;"))
