"""0003_add_subscriptions"""
from sqlalchemy import text

def upgrade(db):
    db.execute(text("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id UUID UNIQUE NOT NULL,
        stripe_customer_id VARCHAR(128),
        stripe_subscription_id VARCHAR(128),
        status VARCHAR(32) NOT NULL DEFAULT 'inactive',
        current_period_start TIMESTAMPTZ,
        current_period_end TIMESTAMPTZ,
        cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """))
def downgrade(db):
    db.execute(text("DROP TABLE IF EXISTS subscriptions;"))
