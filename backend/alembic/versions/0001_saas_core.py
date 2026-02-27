"""saas core tables (additive)

Revision ID: 0001_saas_core
Revises:
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_saas_core"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # These tables are created by SQLAlchemy metadata in dev via init_db().
    # In production, use Alembic to manage schema. This migration is a starter stub.
    pass

def downgrade():
    pass
