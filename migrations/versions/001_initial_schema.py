"""Initial schema — all tables.

This migration creates all tables if they don't already exist.
For databases already created via db.create_all(), the startup code
will stamp to 'head' and this migration will be skipped.

Revision ID: 001_initial
Revises:
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables if they don't exist.

    We check for existing tables so this migration is safe to run on
    databases that were previously managed by db.create_all().
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'users' not in existing_tables:
        op.create_table('users',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('username', sa.String(80), unique=True, nullable=False),
            sa.Column('email', sa.String(120), unique=True, nullable=False),
            sa.Column('password_hash', sa.String(256), nullable=False),
            sa.Column('role', sa.Enum('admin', 'data_entry', 'reporting', 'read_only', name='userrole'), nullable=False),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('last_login', sa.DateTime()),
        )

    if 'donors' not in existing_tables:
        op.create_table('donors',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('donor_type', sa.Enum('individual', 'organization', 'foundation', 'trust', 'estate', 'other', name='donortype'), nullable=False),
            sa.Column('first_name', sa.String(100)),
            sa.Column('last_name', sa.String(100)),
            sa.Column('organization', sa.String(200)),
            sa.Column('display_name', sa.String(250), nullable=False),
            sa.Column('email', sa.String(200)),
            sa.Column('email_secondary', sa.String(200)),
            sa.Column('phone', sa.String(30)),
            sa.Column('phone_secondary', sa.String(30)),
            sa.Column('address_line1', sa.String(200)),
            sa.Column('address_line2', sa.String(200)),
            sa.Column('city', sa.String(100)),
            sa.Column('state', sa.String(50)),
            sa.Column('zip_code', sa.String(20)),
            sa.Column('country', sa.String(80)),
            sa.Column('notes', sa.Text()),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        )

    if 'investment_pools' not in existing_tables:
        op.create_table('investment_pools',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(150), unique=True, nullable=False),
            sa.Column('description', sa.Text()),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.DateTime()),
        )

    if 'investment_vehicles' not in existing_tables:
        op.create_table('investment_vehicles',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('pool_id', sa.Integer(), sa.ForeignKey('investment_pools.id'), nullable=False),
            sa.Column('name', sa.String(150), nullable=False),
            sa.Column('description', sa.Text()),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.DateTime()),
        )

    if 'vehicle_monthly_activity' not in existing_tables:
        op.create_table('vehicle_monthly_activity',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('investment_vehicles.id'), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('beginning_balance', sa.Numeric(18, 4)),
            sa.Column('additions', sa.Numeric(18, 4)),
            sa.Column('withdrawals', sa.Numeric(18, 4)),
            sa.Column('management_expenses', sa.Numeric(18, 4)),
            sa.Column('interest_dividends', sa.Numeric(18, 4)),
            sa.Column('unrealized_gains', sa.Numeric(18, 4)),
            sa.Column('realized_gains', sa.Numeric(18, 4)),
            sa.Column('ending_balance', sa.Numeric(18, 4)),
            sa.Column('is_approved', sa.Boolean(), default=False),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('approved_at', sa.DateTime()),
            sa.Column('is_voided', sa.Boolean(), default=False),
            sa.Column('notes', sa.Text()),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.UniqueConstraint('vehicle_id', 'year', 'month', name='uq_vehicle_month'),
        )

    if 'pool_monthly_snapshots' not in existing_tables:
        op.create_table('pool_monthly_snapshots',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('pool_id', sa.Integer(), sa.ForeignKey('investment_pools.id'), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('total_value', sa.Numeric(18, 4)),
            sa.Column('total_units', sa.Numeric(18, 6)),
            sa.Column('unit_price', sa.Numeric(18, 6)),
            sa.Column('is_closed', sa.Boolean(), default=False),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
            sa.UniqueConstraint('pool_id', 'year', 'month', name='uq_pool_snapshot'),
        )

    if 'pool_adjustments' not in existing_tables:
        op.create_table('pool_adjustments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('pool_snapshot_id', sa.Integer(), sa.ForeignKey('pool_monthly_snapshots.id'), nullable=False),
            sa.Column('description', sa.String(300), nullable=False),
            sa.Column('amount', sa.Numeric(18, 4), nullable=False),
            sa.Column('adjustment_type', sa.String(50)),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        )

    if 'funds' not in existing_tables:
        op.create_table('funds',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('pool_id', sa.Integer(), sa.ForeignKey('investment_pools.id'), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('fund_number', sa.String(50), unique=True),
            sa.Column('restriction', sa.Enum('permanently_restricted', 'temporarily_restricted', 'unrestricted', name='fundrestriction'), nullable=False),
            sa.Column('restriction_purpose', sa.Text()),
            sa.Column('spend_rate', sa.Numeric(5, 4)),
            sa.Column('allow_underwater_spend', sa.Boolean(), default=False),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('inception_date', sa.Date(), nullable=False),
            sa.Column('beginning_corpus', sa.Numeric(18, 4), default=0),
            sa.Column('beginning_earnings', sa.Numeric(18, 4), default=0),
            sa.Column('notes', sa.Text()),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        )
    else:
        # Add beginning balance columns if they don't exist on the funds table
        existing_cols = {c['name'] for c in inspector.get_columns('funds')}
        if 'beginning_corpus' not in existing_cols:
            op.add_column('funds', sa.Column('beginning_corpus', sa.Numeric(18, 4), server_default='0'))
        if 'beginning_earnings' not in existing_cols:
            op.add_column('funds', sa.Column('beginning_earnings', sa.Numeric(18, 4), server_default='0'))

    if 'fund_contributions' not in existing_tables:
        op.create_table('fund_contributions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('fund_id', sa.Integer(), sa.ForeignKey('funds.id'), nullable=False),
            sa.Column('donor_id', sa.Integer(), sa.ForeignKey('donors.id')),
            sa.Column('donor_name', sa.String(200), nullable=False),
            sa.Column('gift_type', sa.Enum('cash', 'check', 'wire', 'stock', 'real_estate', 'in_kind', 'pledge', 'bequest', 'other', name='gifttype')),
            sa.Column('amount', sa.Numeric(18, 4), nullable=False),
            sa.Column('contribution_date', sa.Date(), nullable=False),
            sa.Column('notes', sa.Text()),
            sa.Column('is_voided', sa.Boolean(), default=False),
            sa.Column('voided_reason', sa.Text()),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('buy_in_year', sa.Integer()),
            sa.Column('buy_in_month', sa.Integer()),
            sa.Column('units_purchased', sa.Numeric(18, 6)),
            sa.Column('unit_price_paid', sa.Numeric(18, 6)),
        )
    else:
        # Add gift_type column if missing
        existing_cols = {c['name'] for c in inspector.get_columns('fund_contributions')}
        if 'gift_type' not in existing_cols:
            op.add_column('fund_contributions', sa.Column('gift_type', sa.Enum('cash', 'check', 'wire', 'stock', 'real_estate', 'in_kind', 'pledge', 'bequest', 'other', name='gifttype'), server_default='check'))

    if 'fund_monthly_snapshots' not in existing_tables:
        op.create_table('fund_monthly_snapshots',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('fund_id', sa.Integer(), sa.ForeignKey('funds.id'), nullable=False),
            sa.Column('pool_snapshot_id', sa.Integer(), sa.ForeignKey('pool_monthly_snapshots.id')),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('units_held', sa.Numeric(18, 6)),
            sa.Column('unit_price', sa.Numeric(18, 6)),
            sa.Column('fund_value', sa.Numeric(18, 4)),
            sa.Column('corpus_balance', sa.Numeric(18, 4)),
            sa.Column('created_at', sa.DateTime()),
            sa.UniqueConstraint('fund_id', 'year', 'month', name='uq_fund_snapshot'),
        )

    if 'distributions' not in existing_tables:
        op.create_table('distributions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('fund_id', sa.Integer(), sa.ForeignKey('funds.id'), nullable=False),
            sa.Column('amount', sa.Numeric(18, 4), nullable=False),
            sa.Column('distribution_date', sa.Date(), nullable=False),
            sa.Column('purpose', sa.Text()),
            sa.Column('recipient', sa.String(200)),
            sa.Column('is_voided', sa.Boolean(), default=False),
            sa.Column('voided_reason', sa.Text()),
            sa.Column('voided_at', sa.DateTime()),
            sa.Column('voided_by_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('notes', sa.Text()),
        )

    if 'documents' not in existing_tables:
        op.create_table('documents',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('entity_type', sa.String(20), nullable=False),
            sa.Column('entity_id', sa.Integer(), nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('description', sa.String(255)),
            sa.Column('mime_type', sa.String(100)),
            sa.Column('file_size', sa.Integer()),
            sa.Column('file_data', sa.LargeBinary(), nullable=False),
            sa.Column('uploaded_at', sa.DateTime()),
            sa.Column('uploaded_by_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('is_deleted', sa.Boolean(), default=False),
        )

    if 'audit_log' not in existing_tables:
        op.create_table('audit_log',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('action', sa.Enum('create', 'update', 'delete', 'login', 'logout', 'approve', 'void', name='auditaction'), nullable=False),
            sa.Column('entity_type', sa.String(100)),
            sa.Column('entity_id', sa.Integer()),
            sa.Column('description', sa.Text()),
            sa.Column('ip_address', sa.String(50)),
            sa.Column('timestamp', sa.DateTime()),
        )


def downgrade() -> None:
    """Drop all tables (destructive — use with caution)."""
    op.drop_table('audit_log')
    op.drop_table('documents')
    op.drop_table('distributions')
    op.drop_table('fund_monthly_snapshots')
    op.drop_table('fund_contributions')
    op.drop_table('funds')
    op.drop_table('pool_adjustments')
    op.drop_table('pool_monthly_snapshots')
    op.drop_table('vehicle_monthly_activity')
    op.drop_table('investment_vehicles')
    op.drop_table('investment_pools')
    op.drop_table('donors')
    op.drop_table('users')
