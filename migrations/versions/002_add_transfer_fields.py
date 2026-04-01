"""Add transfers_in and transfers_out columns to vehicle_monthly_activity.

Revision ID: 002
Revises: 001
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # Add new transfer columns — safe to run even if columns already exist
    with op.get_bind().connect() as conn:
        # Check which columns already exist
        result = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'vehicle_monthly_activity'"
        ))
        existing = {row[0] for row in result}

    if 'transfers_in' not in existing:
        op.add_column('vehicle_monthly_activity',
            sa.Column('transfers_in', sa.Numeric(18, 4), server_default='0'))
    if 'transfers_out' not in existing:
        op.add_column('vehicle_monthly_activity',
            sa.Column('transfers_out', sa.Numeric(18, 4), server_default='0'))


def downgrade():
    op.drop_column('vehicle_monthly_activity', 'transfers_out')
    op.drop_column('vehicle_monthly_activity', 'transfers_in')
