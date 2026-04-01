from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import enum

db = SQLAlchemy()

# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN       = "admin"
    DATA_ENTRY  = "data_entry"
    REPORTING   = "reporting"
    READ_ONLY   = "read_only"

class FundRestriction(str, enum.Enum):
    PERMANENTLY_RESTRICTED  = "permanently_restricted"
    TEMPORARILY_RESTRICTED  = "temporarily_restricted"
    UNRESTRICTED            = "unrestricted"

class GiftType(str, enum.Enum):
    CASH        = "cash"
    CHECK       = "check"
    WIRE        = "wire"
    STOCK       = "stock"
    REAL_ESTATE = "real_estate"
    IN_KIND     = "in_kind"
    PLEDGE      = "pledge"
    BEQUEST     = "bequest"
    OTHER       = "other"

class AuditAction(str, enum.Enum):
    CREATE  = "create"
    UPDATE  = "update"
    DELETE  = "delete"
    LOGIN   = "login"
    LOGOUT  = "logout"
    APPROVE = "approve"
    VOID    = "void"

# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.READ_ONLY)
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def can_edit(self):
        return self.role in (UserRole.ADMIN, UserRole.DATA_ENTRY)

    @property
    def can_approve(self):
        return self.role == UserRole.ADMIN

    def __repr__(self):
        return f"<User {self.username}>"

# ─────────────────────────────────────────────
# Donors
# ─────────────────────────────────────────────

class DonorType(str, enum.Enum):
    INDIVIDUAL   = "individual"
    ORGANIZATION = "organization"
    FOUNDATION   = "foundation"
    TRUST        = "trust"
    ESTATE       = "estate"
    OTHER        = "other"


class Donor(db.Model):
    __tablename__ = "donors"
    id              = db.Column(db.Integer, primary_key=True)
    donor_type      = db.Column(db.Enum(DonorType), nullable=False, default=DonorType.INDIVIDUAL)
    # Name fields
    first_name      = db.Column(db.String(100))
    last_name       = db.Column(db.String(100))
    organization    = db.Column(db.String(200))
    display_name    = db.Column(db.String(250), nullable=False)   # Computed or user-entered
    # Contact
    email           = db.Column(db.String(200))
    email_secondary = db.Column(db.String(200))
    phone           = db.Column(db.String(30))
    phone_secondary = db.Column(db.String(30))
    # Address
    address_line1   = db.Column(db.String(200))
    address_line2   = db.Column(db.String(200))
    city            = db.Column(db.String(100))
    state           = db.Column(db.String(50))
    zip_code        = db.Column(db.String(20))
    country         = db.Column(db.String(80), default="United States")
    # Meta
    notes           = db.Column(db.Text)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id   = db.Column(db.Integer, db.ForeignKey("users.id"))

    contributions   = db.relationship("FundContribution", backref="donor", lazy="dynamic")
    created_by      = db.relationship("User", foreign_keys=[created_by_id])

    @property
    def full_address(self):
        parts = [self.address_line1, self.address_line2]
        city_state = ", ".join(filter(None, [self.city, self.state]))
        if city_state and self.zip_code:
            city_state += f" {self.zip_code}"
        parts.append(city_state)
        return "\n".join(filter(None, parts))

    @property
    def total_given(self):
        from sqlalchemy import func as sqlfunc
        result = db.session.query(sqlfunc.sum(FundContribution.amount))\
            .filter_by(donor_id=self.id, is_voided=False).scalar()
        return float(result or 0)

    @property
    def gift_count(self):
        return self.contributions.filter_by(is_voided=False).count()

    def __repr__(self):
        return f"<Donor {self.display_name}>"


# ─────────────────────────────────────────────
# Investment Pools & Vehicles
# ─────────────────────────────────────────────

class InvestmentPool(db.Model):
    __tablename__ = "investment_pools"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_active   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    vehicles    = db.relationship("InvestmentVehicle", backref="pool", lazy="dynamic", cascade="all, delete-orphan")
    funds       = db.relationship("Fund", backref="pool", lazy="dynamic")
    snapshots   = db.relationship("PoolMonthlySnapshot", backref="pool", lazy="dynamic", cascade="all, delete-orphan")

    def total_units(self, year, month):
        """Total units outstanding at end of a given month."""
        snap = PoolMonthlySnapshot.query.filter_by(pool_id=self.id, year=year, month=month).first()
        return snap.total_units if snap else 0

    def unit_price(self, year, month):
        snap = PoolMonthlySnapshot.query.filter_by(pool_id=self.id, year=year, month=month).first()
        return snap.unit_price if snap else None

    def __repr__(self):
        return f"<InvestmentPool {self.name}>"


class InvestmentVehicle(db.Model):
    __tablename__ = "investment_vehicles"
    id                = db.Column(db.Integer, primary_key=True)
    pool_id           = db.Column(db.Integer, db.ForeignKey("investment_pools.id"), nullable=False)
    name              = db.Column(db.String(150), nullable=False)
    description       = db.Column(db.Text)
    is_active         = db.Column(db.Boolean, default=True)
    is_cash_clearing  = db.Column(db.Boolean, default=False)  # True = "Due To/From" vehicle
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    monthly_activity = db.relationship("VehicleMonthlyActivity", backref="vehicle", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<InvestmentVehicle {self.name}>"


class VehicleMonthlyActivity(db.Model):
    """Monthly accounting entries for a single investment vehicle."""
    __tablename__ = "vehicle_monthly_activity"
    __table_args__ = (db.UniqueConstraint("vehicle_id", "year", "month", name="uq_vehicle_month"),)

    id                  = db.Column(db.Integer, primary_key=True)
    vehicle_id          = db.Column(db.Integer, db.ForeignKey("investment_vehicles.id"), nullable=False)
    year                = db.Column(db.Integer, nullable=False)
    month               = db.Column(db.Integer, nullable=False)  # 1-12

    beginning_balance   = db.Column(db.Numeric(18, 4), default=0)
    additions           = db.Column(db.Numeric(18, 4), default=0)   # External cash added (new gifts invested)
    withdrawals         = db.Column(db.Numeric(18, 4), default=0)   # Distributions — cash leaving the pool
    transfers_in        = db.Column(db.Numeric(18, 4), default=0)   # Internal: cash moved in from another vehicle
    transfers_out       = db.Column(db.Numeric(18, 4), default=0)   # Internal: cash moved out to another vehicle
    management_expenses = db.Column(db.Numeric(18, 4), default=0)
    interest_dividends  = db.Column(db.Numeric(18, 4), default=0)
    unrealized_gains    = db.Column(db.Numeric(18, 4), default=0)
    realized_gains      = db.Column(db.Numeric(18, 4), default=0)
    ending_balance      = db.Column(db.Numeric(18, 4), default=0)

    is_approved         = db.Column(db.Boolean, default=False)
    approved_by_id      = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at         = db.Column(db.DateTime)
    is_voided           = db.Column(db.Boolean, default=False)
    notes               = db.Column(db.Text)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id       = db.Column(db.Integer, db.ForeignKey("users.id"))

    approved_by         = db.relationship("User", foreign_keys=[approved_by_id])
    created_by          = db.relationship("User", foreign_keys=[created_by_id])

    @property
    def net_activity(self):
        """Net change = cash flows + transfers + investment performance."""
        return (float(self.additions or 0)
                - float(self.withdrawals or 0)
                + float(self.transfers_in or 0)
                - float(self.transfers_out or 0)
                + float(self.interest_dividends or 0)
                + float(self.unrealized_gains or 0)
                + float(self.realized_gains or 0)
                - float(self.management_expenses or 0))

    @property
    def net_earnings(self):
        """Investment performance only — excludes cash flows and transfers."""
        return (float(self.interest_dividends or 0)
                + float(self.unrealized_gains or 0)
                + float(self.realized_gains or 0)
                - float(self.management_expenses or 0))

    def __repr__(self):
        return f"<VehicleActivity {self.vehicle_id} {self.year}-{self.month:02d}>"


class PoolMonthlySnapshot(db.Model):
    """End-of-month pool totals and unit price."""
    __tablename__ = "pool_monthly_snapshots"
    __table_args__ = (db.UniqueConstraint("pool_id", "year", "month", name="uq_pool_snapshot"),)

    id              = db.Column(db.Integer, primary_key=True)
    pool_id         = db.Column(db.Integer, db.ForeignKey("investment_pools.id"), nullable=False)
    year            = db.Column(db.Integer, nullable=False)
    month           = db.Column(db.Integer, nullable=False)

    total_value     = db.Column(db.Numeric(18, 4), default=0)
    total_units     = db.Column(db.Numeric(18, 6), default=0)
    unit_price      = db.Column(db.Numeric(18, 6), default=0)
    is_closed       = db.Column(db.Boolean, default=False)  # Once closed, fund buy-ins are locked

    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    fund_snapshots  = db.relationship("FundMonthlySnapshot", backref="pool_snapshot", lazy="dynamic")
    adjustments     = db.relationship("PoolAdjustment", backref="pool_snapshot", lazy="dynamic")

    def __repr__(self):
        return f"<PoolSnapshot {self.pool_id} {self.year}-{self.month:02d} ${self.unit_price}>"


class PoolAdjustment(db.Model):
    """Manual adjustment entries to correct timing variances and reconciliation differences."""
    __tablename__ = "pool_adjustments"

    id              = db.Column(db.Integer, primary_key=True)
    pool_snapshot_id = db.Column(db.Integer, db.ForeignKey("pool_monthly_snapshots.id"), nullable=False)
    description     = db.Column(db.String(300), nullable=False)
    amount          = db.Column(db.Numeric(18, 4), nullable=False)  # Positive = increase pool value, negative = decrease
    adjustment_type = db.Column(db.String(50), default="timing")  # timing, rounding, correction, other
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id   = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_by      = db.relationship("User", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<PoolAdjustment ${self.amount} '{self.description}'>"


# ─────────────────────────────────────────────
# Funds
# ─────────────────────────────────────────────

class Fund(db.Model):
    __tablename__ = "funds"
    id                      = db.Column(db.Integer, primary_key=True)
    pool_id                 = db.Column(db.Integer, db.ForeignKey("investment_pools.id"), nullable=False)
    name                    = db.Column(db.String(200), nullable=False)
    fund_number             = db.Column(db.String(50), unique=True)
    restriction             = db.Column(db.Enum(FundRestriction), nullable=False)
    restriction_purpose     = db.Column(db.Text)  # For temporarily restricted funds
    spend_rate              = db.Column(db.Numeric(5, 4), default=0.05)   # e.g. 0.05 = 5%
    allow_underwater_spend  = db.Column(db.Boolean, default=False)
    is_active               = db.Column(db.Boolean, default=True)
    inception_date          = db.Column(db.Date, nullable=False)
    notes                   = db.Column(db.Text)
    created_at              = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id           = db.Column(db.Integer, db.ForeignKey("users.id"))

    # ── Onboarding / beginning balance fields ──
    # Used when migrating an existing foundation into the system.
    # beginning_corpus = the total original gift principal as of the onboarding date
    # beginning_earnings = accumulated earnings (or losses) as of the onboarding date
    beginning_corpus        = db.Column(db.Numeric(18, 4), default=0)
    beginning_earnings      = db.Column(db.Numeric(18, 4), default=0)

    contributions   = db.relationship("FundContribution", backref="fund", lazy="dynamic", cascade="all, delete-orphan")
    snapshots       = db.relationship("FundMonthlySnapshot", backref="fund", lazy="dynamic", cascade="all, delete-orphan")
    distributions   = db.relationship("Distribution", backref="fund", lazy="dynamic")

    created_by      = db.relationship("User", foreign_keys=[created_by_id])

    @property
    def total_corpus(self):
        """Sum of beginning corpus + all contributions (original principal)."""
        result = db.session.query(db.func.sum(FundContribution.amount)).filter_by(fund_id=self.id, is_voided=False).scalar()
        return float(self.beginning_corpus or 0) + float(result or 0)

    @property
    def latest_snapshot(self):
        return (FundMonthlySnapshot.query
                .filter_by(fund_id=self.id)
                .order_by(FundMonthlySnapshot.year.desc(), FundMonthlySnapshot.month.desc())
                .first())

    @property
    def current_value(self):
        snap = self.latest_snapshot
        if snap:
            return float(snap.fund_value)
        # No snapshots yet — value = corpus + beginning earnings
        return self.total_corpus + float(self.beginning_earnings or 0)

    @property
    def current_units(self):
        snap = self.latest_snapshot
        return float(snap.units_held) if snap else 0

    @property
    def accumulated_earnings(self):
        return self.current_value - self.total_corpus

    @property
    def is_underwater(self):
        return self.current_value < self.total_corpus

    @property
    def distributable_amount(self):
        """Annual distributable amount at the configured spend rate."""
        if self.is_underwater and not self.allow_underwater_spend:
            return 0.0
        return self.current_value * float(self.spend_rate or 0)

    def __repr__(self):
        return f"<Fund {self.name}>"


class FundContribution(db.Model):
    """A donation or contribution that adds to a fund's corpus."""
    __tablename__ = "fund_contributions"
    id              = db.Column(db.Integer, primary_key=True)
    fund_id         = db.Column(db.Integer, db.ForeignKey("funds.id"), nullable=False)
    donor_id        = db.Column(db.Integer, db.ForeignKey("donors.id"))
    donor_name      = db.Column(db.String(200), nullable=False)  # Kept for display + backward compat
    gift_type       = db.Column(db.Enum(GiftType), default=GiftType.CHECK)
    amount          = db.Column(db.Numeric(18, 4), nullable=False)
    contribution_date = db.Column(db.Date, nullable=False)
    notes           = db.Column(db.Text)
    is_voided       = db.Column(db.Boolean, default=False)
    voided_reason   = db.Column(db.Text)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id   = db.Column(db.Integer, db.ForeignKey("users.id"))

    # Buy-in tracking: contributions buy units at end-of-month price
    buy_in_year     = db.Column(db.Integer)   # Month when units are purchased
    buy_in_month    = db.Column(db.Integer)
    units_purchased = db.Column(db.Numeric(18, 6))
    unit_price_paid = db.Column(db.Numeric(18, 6))

    created_by      = db.relationship("User", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<Contribution {self.donor_name} ${self.amount} on {self.contribution_date}>"


class FundMonthlySnapshot(db.Model):
    """Per-fund participation snapshot at end of each month."""
    __tablename__ = "fund_monthly_snapshots"
    __table_args__ = (db.UniqueConstraint("fund_id", "year", "month", name="uq_fund_snapshot"),)

    id                  = db.Column(db.Integer, primary_key=True)
    fund_id             = db.Column(db.Integer, db.ForeignKey("funds.id"), nullable=False)
    pool_snapshot_id    = db.Column(db.Integer, db.ForeignKey("pool_monthly_snapshots.id"))
    year                = db.Column(db.Integer, nullable=False)
    month               = db.Column(db.Integer, nullable=False)
    units_held          = db.Column(db.Numeric(18, 6), default=0)
    unit_price          = db.Column(db.Numeric(18, 6), default=0)
    fund_value          = db.Column(db.Numeric(18, 4), default=0)
    corpus_balance      = db.Column(db.Numeric(18, 4), default=0)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<FundSnapshot {self.fund_id} {self.year}-{self.month:02d}>"

# ─────────────────────────────────────────────
# Distributions
# ─────────────────────────────────────────────

class Distribution(db.Model):
    __tablename__ = "distributions"
    id              = db.Column(db.Integer, primary_key=True)
    fund_id         = db.Column(db.Integer, db.ForeignKey("funds.id"), nullable=False)
    amount          = db.Column(db.Numeric(18, 4), nullable=False)
    distribution_date = db.Column(db.Date, nullable=False)
    purpose         = db.Column(db.Text)
    recipient       = db.Column(db.String(200))
    is_voided       = db.Column(db.Boolean, default=False)
    voided_reason   = db.Column(db.Text)
    voided_at       = db.Column(db.DateTime)
    voided_by_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id   = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes           = db.Column(db.Text)

    created_by      = db.relationship("User", foreign_keys=[created_by_id])
    voided_by       = db.relationship("User", foreign_keys=[voided_by_id])

    def __repr__(self):
        return f"<Distribution fund={self.fund_id} ${self.amount} on {self.distribution_date}>"

# ─────────────────────────────────────────────
# Documents
# ─────────────────────────────────────────────

class Document(db.Model):
    """A file attachment linked to a fund or investment pool."""
    __tablename__ = "documents"
    id              = db.Column(db.Integer, primary_key=True)
    entity_type     = db.Column(db.String(20), nullable=False)   # "fund" or "pool"
    entity_id       = db.Column(db.Integer, nullable=False)
    filename        = db.Column(db.String(255), nullable=False)
    description     = db.Column(db.String(255))
    mime_type       = db.Column(db.String(100))
    file_size       = db.Column(db.Integer)
    file_data       = db.Column(db.LargeBinary, nullable=False)
    uploaded_at     = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by_id  = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_deleted      = db.Column(db.Boolean, default=False)

    uploaded_by     = db.relationship("User", foreign_keys=[uploaded_by_id])

    @property
    def size_display(self):
        if not self.file_size:
            return "—"
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024*1024):.1f} MB"

    @property
    def icon(self):
        mt = self.mime_type or ""
        if "pdf" in mt:
            return "bi-file-earmark-pdf text-danger"
        elif "word" in mt or "docx" in mt or "doc" in mt:
            return "bi-file-earmark-word text-primary"
        elif "excel" in mt or "spreadsheet" in mt or "xlsx" in mt:
            return "bi-file-earmark-excel text-success"
        elif "image" in mt:
            return "bi-file-earmark-image text-info"
        else:
            return "bi-file-earmark text-secondary"

    def __repr__(self):
        return f"<Document {self.filename} ({self.entity_type}:{self.entity_id})>"


# ─────────────────────────────────────────────
# Audit Log
# ─────────────────────────────────────────────

class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"))
    action      = db.Column(db.Enum(AuditAction), nullable=False)
    entity_type = db.Column(db.String(100))   # e.g. "Fund", "Distribution"
    entity_id   = db.Column(db.Integer)
    description = db.Column(db.Text)
    ip_address  = db.Column(db.String(50))
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow)

    user        = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return f"<AuditLog {self.action} {self.entity_type}:{self.entity_id}>"
