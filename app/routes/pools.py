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
    additions           = DecimalField("Additions (New Money In)", places=2, validators=[Optional()], default=0)
    withdrawals         = DecimalField("Distributions (Cash Out of Pool)", places=2, validators=[Optional()], default=0)
    transfers_in        = DecimalField("Transfers In (from other vehicles)", places=2, validators=[Optional()], default=0)
    transfers_out       = DecimalField("Transfers Out (to other vehicles)", places=2, validators=[Optional()], default=0)
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

        # Auto-create a Due To/From (cash clearing) vehicle for this pool
        dtf = InvestmentVehicle(
            pool_id=pool.id,
            name="Due To/From",
            description="Cash clearing account — holds gift cash before it is invested in a vehicle.",
            is_cash_clearing=True,
        )
        db.session.add(dtf)

        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="InvestmentPool", entity_id=pool.id,
            description=f"Created pool '{pool.name}' with Due To/From vehicle", ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Pool '{pool.name}' created with a Due To/From clearing vehicle.", "success")
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


# ── Add Due To/From to existing pool ───────────

@pools_bp.route("/<int:pool_id>/add-due-to-from", methods=["POST"])
@login_required
def add_due_to_from(pool_id):
    """Add a Due To/From clearing vehicle to a pool that doesn't have one."""
    if not current_user.can_edit:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)
    existing = pool.vehicles.filter_by(is_cash_clearing=True).first()
    if existing:
        flash("This pool already has a Due To/From vehicle.", "info")
        return redirect(url_for("pools.activity_list", pool_id=pool_id))

    dtf = InvestmentVehicle(
        pool_id=pool_id,
        name="Due To/From",
        description="Cash clearing account — holds gift cash before it is invested.",
        is_cash_clearing=True,
    )
    db.session.add(dtf)
    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
        entity_type="InvestmentVehicle", entity_id=pool_id,
        description=f"Added Due To/From vehicle to pool '{pool.name}'",
        ip_address=request.remote_addr))
    db.session.commit()
    flash("Due To/From clearing vehicle added.", "success")
    return redirect(url_for("pools.activity_list", pool_id=pool_id))


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

    # ── Cash flow reconciliation data ──
    # Total contributions buying in this month
    contribs_this_month = (FundContribution.query
        .join(Fund)
        .filter(Fund.pool_id == pool_id,
                FundContribution.buy_in_year == year,
                FundContribution.buy_in_month == month,
                FundContribution.is_voided == False)
        .all())
    total_gifts = sum(Decimal(str(c.amount)) for c in contribs_this_month)

    # Due To/From vehicle activity
    dtf_vehicle = pool.vehicles.filter_by(is_cash_clearing=True, is_active=True).first()
    dtf_activity = None
    dtf_additions = Decimal("0")
    dtf_transfers_out = Decimal("0")
    if dtf_vehicle:
        dtf_activity = VehicleMonthlyActivity.query.filter_by(
            vehicle_id=dtf_vehicle.id, year=year, month=month, is_voided=False).first()
        if dtf_activity:
            dtf_additions = Decimal(str(dtf_activity.additions or 0))
            # Cash moved from DTF to investment vehicles = transfers_out
            dtf_transfers_out = Decimal(str(dtf_activity.transfers_out or 0))

    # Non-clearing vehicle transfers in (money received from DTF)
    invested_transfers_in = Decimal("0")
    for v in vehicles:
        if v.is_cash_clearing:
            continue
        act = activity.get(v.id)
        if act:
            invested_transfers_in += Decimal(str(act.transfers_in or 0))

    # Reconciliation flags
    recon = {
        "total_gifts": total_gifts,
        "dtf_additions": dtf_additions,
        "dtf_transfers_out": dtf_transfers_out,
        "invested_transfers_in": invested_transfers_in,
        "gift_vs_dtf_diff": total_gifts - dtf_additions,
        "dtf_vs_invested_diff": dtf_transfers_out - invested_transfers_in,
        "has_dtf": dtf_vehicle is not None,
    }

    return render_template("pools/activity.html",
        pool=pool, vehicles=vehicles, activity=activity,
        snapshot=snapshot, year=year, month=month, recon=recon)


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
        existing.transfers_in        = form.transfers_in.data or 0
        existing.transfers_out       = form.transfers_out.data or 0
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
            + (existing.transfers_in or 0)
            - (existing.transfers_out or 0)
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
    """Calculate unit price for the month and update all fund snapshots.

    IMPORTANT — Unit price calculation:
    The unit price must reflect only EARNINGS, not new money flowing in or out.
    Formula:  unit_price = (total_pool_value − new_contribution_cash + distribution_cash) / existing_units

    Internal transfers between vehicles net to zero across the pool and do NOT
    affect unit price — they merely move cash between vehicles.
    """
    if not current_user.can_approve:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)

    # Sum all vehicle ending balances for this pool/month
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

    # ── Get existing units from prior month ──
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    prev_snap = PoolMonthlySnapshot.query.filter_by(pool_id=pool_id, year=prev_year, month=prev_month).first()
    existing_units = Decimal(str(prev_snap.total_units)) if prev_snap else Decimal("0")

    # ── Find new contributions buying in this month ──
    new_contributions = (FundContribution.query
        .join(Fund)
        .filter(Fund.pool_id == pool_id,
                FundContribution.buy_in_year == year,
                FundContribution.buy_in_month == month,
                FundContribution.is_voided == False)
        .all())

    # Total NEW cash from contributions — this is NOT earnings
    new_cash = sum(Decimal(str(c.amount)) for c in new_contributions)

    # Also account for distributions (cash leaving the pool)
    month_distributions = (Distribution.query
        .join(Fund)
        .filter(Fund.pool_id == pool_id,
                Distribution.is_voided == False,
                db.extract('year', Distribution.distribution_date) == year,
                db.extract('month', Distribution.distribution_date) == month)
        .all())
    dist_cash = sum(Decimal(str(d.amount)) for d in month_distributions)

    # ── Calculate unit price ──
    # Subtract new contribution cash (and add back distribution cash) so
    # the price only reflects investment performance, not cash flows.
    #
    #   adjusted_value = total_pool_value − new_contributions + distributions
    #   unit_price     = adjusted_value / existing_units
    #
    # New money then buys units AT this price. Distributions redeem units
    # at this price in _update_fund_snapshot.
    if existing_units > 0:
        adjusted_value = snap.total_value - new_cash + dist_cash
        unit_price = adjusted_value / existing_units
    elif snap.total_value > 0:
        # Very first month (no existing units) — set initial price
        unit_price = Decimal("1.000000")
    else:
        unit_price = Decimal("1.000000")

    # ── Process new contributions at this unit price ──
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

    # ── Update fund snapshots ──
    funds = Fund.query.filter_by(pool_id=pool_id, is_active=True).all()
    for fund in funds:
        _update_fund_snapshot(fund, year, month, snap)

    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.APPROVE,
        entity_type="PoolMonthlySnapshot", entity_id=snap.id,
        description=(f"Closed month {year}-{month:02d} for pool '{pool.name}'. "
                     f"Unit price: ${unit_price:.6f}, New cash: ${float(new_cash):,.2f}"),
        ip_address=request.remote_addr))
    db.session.commit()
    adj_msg = f" (includes ${float(adjustment_total):,.2f} in adjustments)" if adjustment_total else ""
    new_cash_msg = f" New contributions: ${float(new_cash):,.2f} ({float(new_units):,.4f} units)." if new_cash else ""
    flash(
        f"Month closed. Unit price: ${float(unit_price):.6f}. "
        f"Total pool value: ${float(snap.total_value):,.2f}{adj_msg}.{new_cash_msg}",
        "success"
    )
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


# ── Pool Initialization (Onboarding) ─────────

class InitializePoolForm(FlaskForm):
    year  = SelectField("Cutoff Year", coerce=int, validators=[DataRequired()])
    month = SelectField("Cutoff Month", coerce=int, validators=[DataRequired()],
                choices=[(i, datetime(2000, i, 1).strftime("%B")) for i in range(1, 13)])
    total_pool_value = DecimalField("Total Pool Value ($)", places=2,
                         validators=[DataRequired(), NumberRange(min=0)],
                         description="Total market value from investment statements as of this month-end")


@pools_bp.route("/<int:pool_id>/initialize", methods=["GET", "POST"])
@login_required
def initialize_pool(pool_id):
    """Create an opening snapshot that establishes Day 1 unit ownership for all funds.

    This is the critical onboarding step: it tells the system what each fund was
    worth as of a cutoff date and creates the unit structure that allows future
    month-close processes to allocate earnings correctly.
    """
    if not current_user.can_approve:
        abort(403)
    pool = InvestmentPool.query.get_or_404(pool_id)
    funds = Fund.query.filter_by(pool_id=pool_id, is_active=True).order_by(Fund.name).all()

    # Check if pool already has a closed snapshot (i.e., already initialized)
    existing_closed = PoolMonthlySnapshot.query.filter_by(
        pool_id=pool_id, is_closed=True).first()

    current_year = datetime.utcnow().year
    form = InitializePoolForm()
    form.year.choices = [(y, str(y)) for y in range(current_year - 10, current_year + 1)]
    if request.method == "GET":
        # Default to last month
        now = datetime.utcnow()
        if now.month == 1:
            form.year.data = now.year - 1
            form.month.data = 12
        else:
            form.year.data = now.year
            form.month.data = now.month - 1

    # Build a preview of fund values
    fund_preview = []
    for fund in funds:
        corpus = float(fund.beginning_corpus or 0)
        # Also add any contributions already in the system
        from sqlalchemy import func as sqlfunc
        contribs_total = db.session.query(sqlfunc.sum(FundContribution.amount))\
            .filter_by(fund_id=fund.id, is_voided=False).scalar()
        corpus += float(contribs_total or 0)
        earnings = float(fund.beginning_earnings or 0)
        total = corpus + earnings
        fund_preview.append({
            "fund": fund,
            "corpus": corpus,
            "earnings": earnings,
            "total": total,
        })
    total_fund_value = sum(fp["total"] for fp in fund_preview)

    if form.validate_on_submit():
        init_year = form.year.data
        init_month = form.month.data
        pool_value = Decimal(str(form.total_pool_value.data))

        if pool_value <= 0:
            flash("Pool value must be greater than zero.", "danger")
            return render_template("pools/initialize.html", form=form, pool=pool,
                                   funds=funds, fund_preview=fund_preview,
                                   total_fund_value=total_fund_value,
                                   existing_closed=existing_closed)

        # Check no snapshot already exists for this period
        existing_snap = PoolMonthlySnapshot.query.filter_by(
            pool_id=pool_id, year=init_year, month=init_month).first()
        if existing_snap and existing_snap.is_closed:
            flash(f"A closed snapshot already exists for {init_year}-{init_month:02d}. "
                  "Reopen it first or choose a different period.", "danger")
            return render_template("pools/initialize.html", form=form, pool=pool,
                                   funds=funds, fund_preview=fund_preview,
                                   total_fund_value=total_fund_value,
                                   existing_closed=existing_closed)

        # ── Create the opening snapshot ──
        if not existing_snap:
            snap = PoolMonthlySnapshot(pool_id=pool_id, year=init_year, month=init_month)
            db.session.add(snap)
        else:
            snap = existing_snap

        snap.total_value = pool_value
        # Unit price = $1.00 at inception; total units = total pool value
        unit_price = Decimal("1.000000")
        snap.unit_price = unit_price
        snap.total_units = pool_value  # $1 per unit means units = dollars
        snap.is_closed = True
        db.session.flush()

        # ── Create fund snapshots & assign units ──
        # Each fund gets units proportional to its value
        total_fund_val = Decimal("0")
        fund_values = []
        for fund in funds:
            corpus = Decimal(str(fund.beginning_corpus or 0))
            from sqlalchemy import func as sqlfunc
            contribs = db.session.query(sqlfunc.sum(FundContribution.amount))\
                .filter_by(fund_id=fund.id, is_voided=False).scalar()
            corpus += Decimal(str(contribs or 0))
            earnings = Decimal(str(fund.beginning_earnings or 0))
            fund_val = corpus + earnings
            fund_values.append((fund, fund_val, corpus))
            total_fund_val += fund_val

        for fund, fund_val, corpus in fund_values:
            if total_fund_val > 0 and pool_value > 0:
                # Proportional allocation: fund_units = (fund_val / total_fund_val) * total_pool_units
                fund_units = (fund_val / total_fund_val) * pool_value
            else:
                fund_units = Decimal("0")

            fund_value_at_close = fund_units * unit_price  # = fund_units since price is $1

            fsnap = FundMonthlySnapshot.query.filter_by(
                fund_id=fund.id, year=init_year, month=init_month).first()
            if not fsnap:
                fsnap = FundMonthlySnapshot(fund_id=fund.id, year=init_year, month=init_month)
                db.session.add(fsnap)
            fsnap.pool_snapshot_id = snap.id
            fsnap.units_held = fund_units
            fsnap.unit_price = unit_price
            fsnap.fund_value = fund_value_at_close
            fsnap.corpus_balance = corpus

        # ── Stamp all existing contributions as bought-in ──
        all_contribs = FundContribution.query.join(Fund)\
            .filter(Fund.pool_id == pool_id, FundContribution.is_voided == False).all()
        for c in all_contribs:
            if c.units_purchased is None:
                c.units_purchased = Decimal(str(c.amount)) / unit_price
                c.unit_price_paid = unit_price
                c.buy_in_year = init_year
                c.buy_in_month = init_month

        db.session.add(AuditLog(
            user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="PoolMonthlySnapshot", entity_id=snap.id,
            description=(
                f"Initialized pool '{pool.name}' as of {init_year}-{init_month:02d}. "
                f"Pool value: ${float(pool_value):,.2f}, Unit price: $1.000000, "
                f"Total units: {float(pool_value):,.4f}, Funds: {len(funds)}"
            ),
            ip_address=request.remote_addr,
        ))
        db.session.commit()

        month_name = datetime(2000, init_month, 1).strftime("%B")
        flash(
            f"Pool initialized as of {month_name} {init_year}. "
            f"Unit price: $1.00, total units: {float(pool_value):,.4f}. "
            f"{len(funds)} fund(s) now own units. "
            f"You can now enter activity for {('January ' + str(init_year + 1)) if init_month == 12 else (datetime(2000, init_month + 1, 1).strftime('%B') + ' ' + str(init_year))} and close months going forward.",
            "success"
        )
        return redirect(url_for("pools.detail", pool_id=pool_id))

    return render_template("pools/initialize.html", form=form, pool=pool,
                           funds=funds, fund_preview=fund_preview,
                           total_fund_value=total_fund_value,
                           existing_closed=existing_closed)


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
