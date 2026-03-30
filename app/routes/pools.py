from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, IntegerField, SelectField, BooleanField
from wtforms.validators import DataRequired, Optional, NumberRange
from decimal import Decimal
from datetime import datetime

from models import (
    db, InvestmentPool, InvestmentVehicle, VehicleMonthlyActivity,
    PoolMonthlySnapshot, PoolAdjustment, FundMonthlySnapshot, Fund, FundContribution,
    Distribution, AuditLog, AuditAction, Document
)

pools_bp = Blueprint("pools", __name__)


# ── Forms ──────────────────────────────────────

class PoolForm(FlaskForm):
    name        = StringField("Pool Name", validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])


class VehicleForm(FlaskForm):
    name        = StringField("Vehicle Name", validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])


class ActivityForm(FlaskForm):
    beginning_balance   = DecimalField("Beginning Balance", places=2, validators=[Optional()], default=0)
    additions           = DecimalField("Additions (Cash In)", places=2, validators=[Optional()], default=0)
    withdrawals         = DecimalField("Withdrawals (Cash Out)", places=2, validators=[Optional()], default=0)
    management_expenses = DecimalField("Management / Admin Expenses", places=2, validators=[Optional()], default=0)
    interest_dividends  = DecimalField("Interest & Dividend Income", places=2, validators=[Optional()], default=0)
    unrealized_gains    = DecimalField("Unrealized Gains (Losses)", places=2, validators=[Optional()], default=0)
    realized_gains      = DecimalField("Realized Gains (Losses)", places=2, validators=[Optional()], default=0)
    notes               = TextAreaField("Notes", validators=[Optional()])


# ── Pool CRUD ──────────────────────────────────

@pools_bp.route("/")
@login_required
def index():
    pools = InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()
    return render_template("pools/index.html", pools=pools)


@pools_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_pool():
    if not current_user.can_edit:
        abort(403)
    form = PoolForm()
    if form.validate_on_submit():
        pool = InvestmentPool(name=form.name.data, description=form.description.data)
        db.session.add(pool)
        db.session.flush()
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="InvestmentPool", entity_id=pool.id,
            description=f"Created pool '{pool.name}'", ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Pool '{pool.name}' created.", "success")
        return redirect(url_for("pools.detail", pool_id=pool.id))
    return render_template("pools/form.html", form=form, title="New Investment Pool")


@pools_bp.route("/<int:pool_id>")
@login_required
def detail(pool_id):
    pool = InvestmentPool.query.get_or_404(pool_id)
    snapshots = (PoolMonthlySnapshot.query
                 .filter_by(pool_id=pool_id)
                 .order_by(PoolMonthlySnapshot.year.desc(), PoolMonthlySnapshot.month.desc())
                 .limit(24).all())
    funds = Fund.query.filter_by(pool_id=pool_id, is_active=True).all()
    pool_documents = Document.query.filter_by(entity_type="pool", entity_id=pool_id, is_deleted=False)\
        .order_by(Document.uploaded_at.desc()).all()
    return render_template("pools/detail.html", pool=pool, snapshots=snapshots, funds=funds,
                           pool_documents=pool_documents)


@pools_bp.route("/<int:pool_id>/edit", methods=["GET", "POST"])
@login_required
def edit_pool(pool_id):
    if not current_user.can_edit:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)
    form = PoolForm(obj=pool)
    if form.validate_on_submit():
        pool.name = form.name.data
        pool.description = form.description.data
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.UPDATE,
            entity_type="InvestmentPool", entity_id=pool.id,
            description=f"Updated pool '{pool.name}'", ip_address=request.remote_addr))
        db.session.commit()
        flash("Pool updated.", "success")
        return redirect(url_for("pools.detail", pool_id=pool.id))
    return render_template("pools/form.html", form=form, title="Edit Pool", pool=pool)


# ── Vehicle CRUD ───────────────────────────────

@pools_bp.route("/<int:pool_id>/vehicles/new", methods=["GET", "POST"])
@login_required
def new_vehicle(pool_id):
    if not current_user.can_edit:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)
    form = VehicleForm()
    if form.validate_on_submit():
        v = InvestmentVehicle(pool_id=pool_id, name=form.name.data, description=form.description.data)
        db.session.add(v)
        db.session.flush()
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="InvestmentVehicle", entity_id=v.id,
            description=f"Added vehicle '{v.name}' to pool '{pool.name}'",
            ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Vehicle '{v.name}' added.", "success")
        return redirect(url_for("pools.detail", pool_id=pool_id))
    return render_template("pools/vehicle_form.html", form=form, pool=pool, title="Add Investment Vehicle")


# ── Monthly Activity ───────────────────────────

@pools_bp.route("/<int:pool_id>/activity")
@login_required
def activity_list(pool_id):
    pool = InvestmentPool.query.get_or_404(pool_id)
    year  = request.args.get("year",  datetime.utcnow().year,  type=int)
    month = request.args.get("month", datetime.utcnow().month, type=int)
    vehicles = pool.vehicles.filter_by(is_active=True).all()
    activity = {}
    for v in vehicles:
        act = VehicleMonthlyActivity.query.filter_by(vehicle_id=v.id, year=year, month=month).first()
        activity[v.id] = act
    snapshot = PoolMonthlySnapshot.query.filter_by(pool_id=pool_id, year=year, month=month).first()
    return render_template("pools/activity.html",
        pool=pool, vehicles=vehicles, activity=activity,
        snapshot=snapshot, year=year, month=month)


@pools_bp.route("/<int:pool_id>/activity/<int:vehicle_id>/<int:year>/<int:month>", methods=["GET", "POST"])
@login_required
def enter_activity(pool_id, vehicle_id, year, month):
    if not current_user.can_edit:
        abort(403)
    pool    = InvestmentPool.query.get_or_404(pool_id)
    vehicle = InvestmentVehicle.query.get_or_404(vehicle_id)
    existing = VehicleMonthlyActivity.query.filter_by(vehicle_id=vehicle_id, year=year, month=month).first()

    # Auto-carry beginning balance from prior month's ending balance
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    prior_activity = VehicleMonthlyActivity.query.filter_by(
        vehicle_id=vehicle_id, year=prev_year, month=prev_month, is_voided=False).first()
    prior_ending = prior_activity.ending_balance if prior_activity else None

    form = ActivityForm(obj=existing)

    # On GET with no existing record, pre-fill beginning balance from prior month
    if request.method == "GET" and not existing and prior_ending is not None:
        form.beginning_balance.data = prior_ending

    if form.validate_on_submit():
        if existing and existing.is_approved and not current_user.can_approve:
            flash("This period is already approved. Only admins can modify approved entries.", "danger")
            return redirect(url_for("pools.activity_list", pool_id=pool_id, year=year, month=month))

        if not existing:
            existing = VehicleMonthlyActivity(
                vehicle_id=vehicle_id, year=year, month=month,
                created_by_id=current_user.id)
            db.session.add(existing)

        existing.beginning_balance   = form.beginning_balance.data or 0
        existing.additions           = form.additions.data or 0
        existing.withdrawals         = form.withdrawals.data or 0
        existing.management_expenses = form.management_expenses.data or 0
        existing.interest_dividends  = form.interest_dividends.data or 0
        existing.unrealized_gains    = form.unrealized_gains.data or 0
        existing.realized_gains      = form.realized_gains.data or 0
        existing.notes               = form.notes.data
        # Auto-calc ending balance
        existing.ending_balance = (
            (existing.beginning_balance or 0)
            + (existing.additions or 0)
            - (existing.withdrawals or 0)
            + (existing.interest_dividends or 0)
            + (existing.unrealized_gains or 0)
            + (existing.realized_gains or 0)
            - (existing.management_expenses or 0)
        )
        existing.is_approved = False  # Reset approval on edit

        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.UPDATE,
            entity_type="VehicleMonthlyActivity", entity_id=existing.id,
            description=f"Entered activity for {vehicle.name} {year}-{month:02d}",
            ip_address=request.remote_addr))
        db.session.commit()
        flash("Activity saved.", "success")
        return redirect(url_for("pools.activity_list", pool_id=pool_id, year=year, month=month))

    return render_template("pools/activity_form.html",
        form=form, pool=pool, vehicle=vehicle, year=year, month=month,
        existing=existing, prior_ending=prior_ending,
        prev_year=prev_year, prev_month=prev_month)


@pools_bp.route("/<int:pool_id>/activity/<int:vehicle_id>/<int:year>/<int:month>/approve", methods=["POST"])
@login_required
def approve_activity(pool_id, vehicle_id, year, month):
    if not current_user.can_approve:
        abort(403)
    act = VehicleMonthlyActivity.query.filter_by(vehicle_id=vehicle_id, year=year, month=month).first_or_404()
    act.is_approved   = True
    act.approved_by_id = current_user.id
    act.approved_at   = datetime.utcnow()
    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.APPROVE,
        entity_type="VehicleMonthlyActivity", entity_id=act.id,
        description=f"Approved activity for vehicle {vehicle_id} {year}-{month:02d}",
        ip_address=request.remote_addr))
    db.session.commit()
    flash("Activity approved.", "success")
    return redirect(url_for("pools.activity_list", pool_id=pool_id, year=year, month=month))


@pools_bp.route("/<int:pool_id>/close-month/<int:year>/<int:month>", methods=["POST"])
@login_required
def close_month(pool_id, year, month):
    """Calculate unit price for the month and update all fund snapshots."""
    if not current_user.can_approve:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)

    # Sum all approved vehicle ending balances for this pool/month
    vehicles = pool.vehicles.filter_by(is_active=True).all()
    total_value = Decimal("0")
    for v in vehicles:
        act = VehicleMonthlyActivity.query.filter_by(vehicle_id=v.id, year=year, month=month, is_voided=False).first()
        if act:
            total_value += (act.ending_balance or Decimal("0"))

    # Get or create snapshot
    snap = PoolMonthlySnapshot.query.filter_by(pool_id=pool_id, year=year, month=month).first()
    if not snap:
        snap = PoolMonthlySnapshot(pool_id=pool_id, year=year, month=month)
        db.session.add(snap)

    snap.total_value = total_value
    db.session.flush()  # Ensure snap has an ID for adjustment lookup

    # Include any manual adjustments (timing variances, corrections)
    adjustment_total = Decimal("0")
    adjustments = PoolAdjustment.query.filter_by(pool_snapshot_id=snap.id).all()
    if adjustments:
        adjustment_total = sum(Decimal(str(a.amount)) for a in adjustments)
        snap.total_value = total_value + adjustment_total

    # Calculate total units: existing units from last month + new buy-ins this month
    # Get previous month snapshot for existing units
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    prev_snap = PoolMonthlySnapshot.query.filter_by(pool_id=pool_id, year=prev_year, month=prev_month).first()
    existing_units = Decimal(str(prev_snap.total_units)) if prev_snap else Decimal("0")

    # New units from contributions that buy in this month
    new_contributions = (FundContribution.query
        .join(Fund)
        .filter(Fund.pool_id == pool_id,
                FundContribution.buy_in_year == year,
                FundContribution.buy_in_month == month,
                FundContribution.is_voided == False)
        .all())

    # Calculate unit price BEFORE new buy-ins (new money buys at closing price)
    if existing_units > 0 and total_value > 0:
        unit_price = total_value / existing_units
    elif total_value > 0:
        unit_price = Decimal("1.000000")  # Initial price
        existing_units = Decimal("0")
    else:
        unit_price = Decimal("1.000000")

    # Process new contributions at this unit price
    new_units = Decimal("0")
    for contrib in new_contributions:
        if unit_price > 0:
            units = Decimal(str(contrib.amount)) / unit_price
            contrib.units_purchased = units
            contrib.unit_price_paid = unit_price
            new_units += units

    snap.total_units = existing_units + new_units
    snap.unit_price  = unit_price
    snap.is_closed   = True

    db.session.flush()

    # Update fund snapshots for all active funds in this pool
    funds = Fund.query.filter_by(pool_id=pool_id, is_active=True).all()
    for fund in funds:
        _update_fund_snapshot(fund, year, month, snap)

    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.APPROVE,
        entity_type="PoolMonthlySnapshot", entity_id=snap.id,
        description=f"Closed month {year}-{month:02d} for pool '{pool.name}'. Unit price: ${unit_price:.4f}",
        ip_address=request.remote_addr))
    db.session.commit()
    adj_msg = f" (includes ${float(adjustment_total):,.2f} in adjustments)" if adjustment_total else ""
    flash(f"Month closed. Unit price: ${float(unit_price):.4f}. Total pool value: ${float(snap.total_value):,.2f}{adj_msg}", "success")
    return redirect(url_for("pools.activity_list", pool_id=pool_id, year=year, month=month))


def _update_fund_snapshot(fund, year, month, pool_snap):
    """Recalculate a fund's snapshot for the given month."""
    # Prior month units
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    prev_fund_snap = FundMonthlySnapshot.query.filter_by(fund_id=fund.id, year=prev_year, month=prev_month).first()
    units = Decimal(str(prev_fund_snap.units_held)) if prev_fund_snap else Decimal("0")

    # Add new units purchased this month by this fund's contributions
    new_contribs = FundContribution.query.filter_by(
        fund_id=fund.id, buy_in_year=year, buy_in_month=month, is_voided=False).all()
    for c in new_contribs:
        if c.units_purchased:
            units += Decimal(str(c.units_purchased))

    # Subtract units redeemed by distributions this month
    monthly_distributions = Distribution.query.filter_by(fund_id=fund.id, is_voided=False)\
        .filter(db.extract('year', Distribution.distribution_date) == year,
                db.extract('month', Distribution.distribution_date) == month).all()
    dist_total = sum(Decimal(str(d.amount)) for d in monthly_distributions)
    if pool_snap.unit_price and pool_snap.unit_price > 0 and dist_total > 0:
        units_redeemed = dist_total / Decimal(str(pool_snap.unit_price))
        units = max(Decimal("0"), units - units_redeemed)

    fund_value = units * Decimal(str(pool_snap.unit_price))
    corpus = Decimal(str(fund.total_corpus))

    snap = FundMonthlySnapshot.query.filter_by(fund_id=fund.id, year=year, month=month).first()
    if not snap:
        snap = FundMonthlySnapshot(fund_id=fund.id, year=year, month=month)
        db.session.add(snap)
    snap.pool_snapshot_id = pool_snap.id
    snap.units_held       = units
    snap.unit_price       = pool_snap.unit_price
    snap.fund_value       = fund_value
    snap.corpus_balance   = corpus


# ── Vehicle Detail / Drill-Down ────────────

@pools_bp.route("/<int:pool_id>/vehicles/<int:vehicle_id>")
@login_required
def vehicle_detail(pool_id, vehicle_id):
    """Cumulative activity drill-down for a single investment vehicle."""
    pool    = InvestmentPool.query.get_or_404(pool_id)
    vehicle = InvestmentVehicle.query.get_or_404(vehicle_id)

    # All activity records, oldest first so we can compute running totals
    all_activity = (VehicleMonthlyActivity.query
                    .filter_by(vehicle_id=vehicle_id, is_voided=False)
                    .order_by(VehicleMonthlyActivity.year, VehicleMonthlyActivity.month)
                    .all())

    # Build rows with running cumulative totals
    rows = []
    cum_expenses     = Decimal("0")
    cum_interest     = Decimal("0")
    cum_unrealized   = Decimal("0")
    cum_realized     = Decimal("0")
    cum_net_activity = Decimal("0")
    cum_additions    = Decimal("0")
    cum_withdrawals  = Decimal("0")

    for act in all_activity:
        cum_expenses     += Decimal(str(act.management_expenses or 0))
        cum_interest     += Decimal(str(act.interest_dividends or 0))
        cum_unrealized   += Decimal(str(act.unrealized_gains or 0))
        cum_realized     += Decimal(str(act.realized_gains or 0))
        cum_net_activity += Decimal(str(act.net_activity or 0))
        cum_additions    += Decimal(str(act.additions or 0))
        cum_withdrawals  += Decimal(str(act.withdrawals or 0))

        # Is this month's pool snapshot closed?
        pool_snap = PoolMonthlySnapshot.query.filter_by(
            pool_id=pool_id, year=act.year, month=act.month).first()
        is_closed = pool_snap.is_closed if pool_snap else False

        rows.append({
            "act":              act,
            "is_closed":        is_closed,
            "cum_expenses":     cum_expenses,
            "cum_interest":     cum_interest,
            "cum_unrealized":   cum_unrealized,
            "cum_realized":     cum_realized,
            "cum_net_activity": cum_net_activity,
            "cum_additions":    cum_additions,
            "cum_withdrawals":  cum_withdrawals,
        })

    # Reverse for display (newest first), but keep cumulative values
    rows_display = list(reversed(rows))

    # Find the last CLOSED month for reconciliation helper
    last_closed_row = None
    for row in rows:  # oldest-first so last match = most recent closed
        if row["is_closed"]:
            last_closed_row = row

    # Chart data (oldest-first subset)
    chart_labels  = [f"{r['act'].year}-{r['act'].month:02d}" for r in rows]
    chart_ending  = [float(r["act"].ending_balance or 0) for r in rows]
    chart_unrealized_cum = [float(r["cum_unrealized"]) for r in rows]

    return render_template("pools/vehicle_detail.html",
        pool=pool,
        vehicle=vehicle,
        rows=rows_display,
        last_closed_row=last_closed_row,
        chart_labels=chart_labels,
        chart_ending=chart_ending,
        chart_unrealized_cum=chart_unrealized_cum,
    )


# ── Reopen Month ──────────────────────────────

@pools_bp.route("/<int:pool_id>/reopen-month/<int:year>/<int:month>", methods=["POST"])
@login_required
def reopen_month(pool_id, year, month):
    """Reopen a previously closed month so activity can be corrected and re-closed."""
    if not current_user.can_approve:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)
    snap = PoolMonthlySnapshot.query.filter_by(pool_id=pool_id, year=year, month=month).first()
    if not snap or not snap.is_closed:
        flash("This month is not closed.", "warning")
        return redirect(url_for("pools.activity_list", pool_id=pool_id, year=year, month=month))

    # Check if a LATER month is closed — can only reopen the most recent closed month
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    later_snap = PoolMonthlySnapshot.query.filter_by(pool_id=pool_id, year=next_year, month=next_month).first()
    if later_snap and later_snap.is_closed:
        flash("Cannot reopen this month because a later month is already closed. "
              "Reopen the most recent month first, then work backwards.", "danger")
        return redirect(url_for("pools.activity_list", pool_id=pool_id, year=year, month=month))

    # Reopen: set is_closed = False, clear fund snapshots so they get recalculated
    snap.is_closed = False

    # Reset contribution unit purchases for this period (they'll be recalculated on re-close)
    contributions = (FundContribution.query
        .join(Fund)
        .filter(Fund.pool_id == pool_id,
                FundContribution.buy_in_year == year,
                FundContribution.buy_in_month == month,
                FundContribution.is_voided == False)
        .all())
    for c in contributions:
        c.units_purchased = None
        c.unit_price_paid = None

    # Delete fund snapshots for this month (they'll be recreated on re-close)
    FundMonthlySnapshot.query.filter_by(pool_snapshot_id=snap.id).delete()

    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.UPDATE,
        entity_type="PoolMonthlySnapshot", entity_id=snap.id,
        description=f"Reopened month {year}-{month:02d} for pool '{pool.name}'",
        ip_address=request.remote_addr))
    db.session.commit()
    flash(f"Month {year}-{month:02d} reopened. Edit activity or add adjustments, then close again.", "success")
    return redirect(url_for("pools.activity_list", pool_id=pool_id, year=year, month=month))


# ── Pool Adjustments ──────────────────────────

class AdjustmentForm(FlaskForm):
    amount          = DecimalField("Adjustment Amount ($)", places=2, validators=[DataRequired()])
    adjustment_type = SelectField("Type", validators=[DataRequired()],
                        choices=[
                            ("timing", "Timing Variance"),
                            ("rounding", "Rounding Difference"),
                            ("correction", "Prior Period Correction"),
                            ("other", "Other"),
                        ])
    description     = StringField("Description", validators=[DataRequired()])


@pools_bp.route("/<int:pool_id>/adjustments/<int:year>/<int:month>", methods=["GET", "POST"])
@login_required
def manage_adjustments(pool_id, year, month):
    """View and add adjustment entries for a pool month."""
    if not current_user.can_approve:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)

    # Get or create snapshot (adjustments attach to the snapshot)
    snap = PoolMonthlySnapshot.query.filter_by(pool_id=pool_id, year=year, month=month).first()
    if not snap:
        snap = PoolMonthlySnapshot(pool_id=pool_id, year=year, month=month)
        db.session.add(snap)
        db.session.flush()

    form = AdjustmentForm()
    if form.validate_on_submit():
        if snap.is_closed:
            flash("Month is closed. Reopen it first before adding adjustments.", "danger")
            return redirect(url_for("pools.manage_adjustments", pool_id=pool_id, year=year, month=month))

        adj = PoolAdjustment(
            pool_snapshot_id=snap.id,
            amount=form.amount.data,
            adjustment_type=form.adjustment_type.data,
            description=form.description.data,
            created_by_id=current_user.id,
        )
        db.session.add(adj)
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="PoolAdjustment", entity_id=snap.id,
            description=f"Added {form.adjustment_type.data} adjustment of ${float(form.amount.data):,.2f} for {pool.name} {year}-{month:02d}: {form.description.data}",
            ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Adjustment of ${float(form.amount.data):,.2f} added.", "success")
        return redirect(url_for("pools.manage_adjustments", pool_id=pool_id, year=year, month=month))

    adjustments = PoolAdjustment.query.filter_by(pool_snapshot_id=snap.id).order_by(PoolAdjustment.created_at.desc()).all()
    adj_total = sum(Decimal(str(a.amount)) for a in adjustments)

    return render_template("pools/adjustments.html",
        pool=pool, snap=snap, form=form,
        adjustments=adjustments, adj_total=adj_total,
        year=year, month=month)


@pools_bp.route("/<int:pool_id>/adjustments/<int:year>/<int:month>/<int:adj_id>/delete", methods=["POST"])
@login_required
def delete_adjustment(pool_id, year, month, adj_id):
    """Remove an adjustment entry."""
    if not current_user.can_approve:
        abort(403)
    adj = PoolAdjustment.query.get_or_404(adj_id)
    snap = adj.pool_snapshot
    if snap.is_closed:
        flash("Month is closed. Reopen it first.", "danger")
        return redirect(url_for("pools.manage_adjustments", pool_id=pool_id, year=year, month=month))

    desc = adj.description
    db.session.delete(adj)
    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.VOID,
        entity_type="PoolAdjustment", entity_id=adj_id,
        description=f"Deleted adjustment '{desc}' for pool {pool_id} {year}-{month:02d}",
        ip_address=request.remote_addr))
    db.session.commit()
    flash("Adjustment removed.", "success")
    return redirect(url_for("pools.manage_adjustments", pool_id=pool_id, year=year, month=month))
