"""0004_add_stripe_events_invoices"""
from sqlalchemy import text

def upgrade(db):
    db.execute(text("""
    CREATE TABLE IF NOT EXISTS stripe_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        stripe_event_id VARCHAR(128) UNIQUE NOT NULL,
        event_type VARCHAR(128) NOT NULL,
        org_id UUID,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """))
    db.execute(text("""
    CREATE TABLE IF NOT EXISTS invoices (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID NOT NULL,
        stripe_invoice_id VARCHAR(128) UNIQUE NOT NULL,
        status VARCHAR(64),
        amount_due NUMERIC(12,2),
        amount_paid NUMERIC(12,2),
        currency VARCHAR(8),
        hosted_invoice_url VARCHAR(512),
        invoice_pdf VARCHAR(512),
        billing_reason VARCHAR(64),
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """))
def downgrade(db):
    db.execute(text("DROP TABLE IF EXISTS invoices;"))
    db.execute(text("DROP TABLE IF EXISTS stripe_events;"))
