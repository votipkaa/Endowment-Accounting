from flask import Blueprint, render_template, request
from flask_login import login_required
from decimal import Decimal

from models import (
    db, Fund, FundRestriction, FundContribution, FundMonthlySnapshot,
    InvestmentPool, InvestmentVehicle, VehicleMonthlyActivity,
    PoolMonthlySnapshot, Distribution, AuditLog
)

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/spendability")
@login_required
def spendability():
    """On-demand spendability report across all active funds."""
    pool_filter = request.args.get("pool_id", type=int)
    restriction_filter = request.args.get("restriction")

    query = Fund.query.filter_by(is_active=True)
    if pool_filter:
        query = query.filter_by(pool_id=pool_filter)
    if restriction_filter:
        query = query.filter_by(restriction=restriction_filter)

    funds = query.order_by(Fund.name).all()
    pools = InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()

    rows = []
    total_fund_value       = Decimal("0")
    total_corpus           = Decimal("0")
    total_distributable    = Decimal("0")
    underwater_count       = 0
    eligible_count         = 0

    for fund in funds:
        current_val = Decimal(str(fund.current_value))
        corpus      = Decimal(str(fund.total_corpus))
        distributable = Decimal(str(fund.distributable_amount))
        is_uw       = fund.is_underwater
        eligible    = not is_uw or fund.allow_underwater_spend

        total_fund_value    += current_val
        total_corpus        += corpus
        total_distributable += distributable
        if is_uw:
            underwater_count += 1
        if eligible and distributable > 0:
            eligible_count += 1

        rows.append({
            "fund":            fund,
            "current_value":   current_val,
            "corpus":          corpus,
            "earnings":        current_val - corpus,
            "spend_rate_pct":  float(fund.spend_rate or 0) * 100,
            "distributable":   distributable,
            "is_underwater":   is_uw,
            "eligible":        eligible,
            "restriction":     fund.restriction,
        })

    return render_template("reports/spendability.html",
        rows=rows,
        pools=pools,
        pool_filter=pool_filter,
        restriction_filter=restriction_filter,
        total_fund_value=total_fund_value,
        total_corpus=total_corpus,
        total_distributable=total_distributable,
        underwater_count=underwater_count,
        eligible_count=eligible_count,
        FundRestriction=FundRestriction,
    )


@reports_bp.route("/audit")
@login_required
def audit():
    page = request.args.get("page", 1, type=int)
    entity_filter = request.args.get("entity")
    query = AuditLog.query.order_by(AuditLog.timestamp.desc())
    if entity_filter:
        query = query.filter_by(entity_type=entity_filter)
    logs = query.paginate(page=page, per_page=50)
    entity_types = db.session.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all()
    entity_types = [e[0] for e in entity_types if e[0]]
    return render_template("reports/audit.html", logs=logs, entity_types=entity_types, entity_filter=entity_filter)


@reports_bp.route("/distributions-history")
@login_required
def distributions_history():
    year  = request.args.get("year",  type=int)
    month = request.args.get("month", type=int)
    pool_filter = request.args.get("pool_id", type=int)
    pools = InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()

    query = Distribution.query.filter_by(is_voided=False)
    if year:
        query = query.filter(db.extract("year", Distribution.distribution_date) == year)
    if month:
        query = query.filter(db.extract("month", Distribution.distribution_date) == month)
    if pool_filter:
        fund_ids = [f.id for f in Fund.query.filter_by(pool_id=pool_filter).all()]
        query = query.filter(Distribution.fund_id.in_(fund_ids))

    distributions = query.order_by(Distribution.distribution_date.desc()).all()
    total = sum(Decimal(str(d.amount)) for d in distributions)

    return render_template("reports/distributions_history.html",
        distributions=distributions, total=total,
        pools=pools, pool_filter=pool_filter,
        year=year, month=month)


@reports_bp.route("/reconciliation")
@login_required
def reconciliation():
    """Reconcile fund values vs. vehicle values, additions vs. gifts, distributions vs. fund distributions.

    Key changes from original:
    - Fund values now come from FundMonthlySnapshot (historical), not f.current_value
    - Vehicle additions are compared to fund contributions (external cash only)
    - Vehicle distributions are compared to fund distributions
    - Transfers (internal vehicle-to-vehicle movements) are shown separately and should net to zero
    """
    from datetime import datetime
    pool_filter = request.args.get("pool_id", type=int)
    year  = request.args.get("year",  datetime.utcnow().year, type=int)
    month = request.args.get("month", datetime.utcnow().month, type=int)

    pools = InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()
    pool_rows = []

    for pool in pools:
        if pool_filter and pool.id != pool_filter:
            continue

        # ── Vehicle side (what the brokerage says) ──
        vehicles = pool.vehicles.filter_by(is_active=True).all()
        vehicle_total_ending       = Decimal("0")
        vehicle_total_additions    = Decimal("0")
        vehicle_total_distributions = Decimal("0")
        vehicle_total_transfers_in  = Decimal("0")
        vehicle_total_transfers_out = Decimal("0")
        vehicle_details = []

        for v in vehicles:
            act = VehicleMonthlyActivity.query.filter_by(
                vehicle_id=v.id, year=year, month=month, is_voided=False).first()
            ending  = Decimal(str(act.ending_balance or 0)) if act else Decimal("0")
            adds    = Decimal(str(act.additions or 0)) if act else Decimal("0")
            dists   = Decimal(str(act.withdrawals or 0)) if act else Decimal("0")
            t_in    = Decimal(str(act.transfers_in or 0)) if act else Decimal("0")
            t_out   = Decimal(str(act.transfers_out or 0)) if act else Decimal("0")
            vehicle_total_ending       += ending
            vehicle_total_additions    += adds
            vehicle_total_distributions += dists
            vehicle_total_transfers_in  += t_in
            vehicle_total_transfers_out += t_out
            vehicle_details.append({
                "name": v.name,
                "ending": ending,
                "additions": adds,
                "distributions": dists,
                "transfers_in": t_in,
                "transfers_out": t_out,
                "has_data": act is not None,
                "is_clearing": v.is_cash_clearing,
            })

        # ── Fund side (accounting records) — use HISTORICAL snapshot values ──
        funds = Fund.query.filter_by(pool_id=pool.id, is_active=True).all()
        fund_total_value = Decimal("0")
        fund_total_contributions = Decimal("0")
        fund_total_distributions = Decimal("0")
        fund_details = []

        for f in funds:
            # Use the fund's monthly snapshot for the selected period (not current_value!)
            fund_snap = FundMonthlySnapshot.query.filter_by(
                fund_id=f.id, year=year, month=month).first()
            if fund_snap:
                fval = Decimal(str(fund_snap.fund_value))
            else:
                # No snapshot for this month — fall back to pre-initialization value
                fval = Decimal(str(f.total_corpus)) + Decimal(str(f.beginning_earnings or 0))
            fund_total_value += fval

            # Contributions for this period
            contribs = FundContribution.query.filter_by(
                fund_id=f.id, buy_in_year=year, buy_in_month=month, is_voided=False).all()
            contrib_sum = sum(Decimal(str(c.amount)) for c in contribs)
            fund_total_contributions += contrib_sum

            # Distributions for this period
            dists_q = Distribution.query.filter_by(fund_id=f.id, is_voided=False)\
                .filter(db.extract('year', Distribution.distribution_date) == year,
                        db.extract('month', Distribution.distribution_date) == month).all()
            dist_sum = sum(Decimal(str(d.amount)) for d in dists_q)
            fund_total_distributions += dist_sum

            fund_details.append({
                "name": f.name,
                "value": fval,
                "contributions": contrib_sum,
                "distributions": dist_sum,
            })

        # ── Pool snapshot (if closed) ──
        snap = PoolMonthlySnapshot.query.filter_by(
            pool_id=pool.id, year=year, month=month).first()

        # ── Variance calculations ──
        # Value: vehicle ending balances vs fund values (from snapshots)
        value_variance = vehicle_total_ending - fund_total_value

        # Additions: vehicle additions (external new money) vs fund contributions
        additions_variance = vehicle_total_additions - fund_total_contributions

        # Distributions: vehicle distributions vs fund distributions
        distributions_variance = vehicle_total_distributions - fund_total_distributions

        # Transfers: should net to zero across all vehicles in the pool
        net_transfers = vehicle_total_transfers_in - vehicle_total_transfers_out

        pool_rows.append({
            "pool": pool,
            "snap": snap,
            "vehicle_total_ending":        vehicle_total_ending,
            "vehicle_total_additions":     vehicle_total_additions,
            "vehicle_total_distributions": vehicle_total_distributions,
            "vehicle_total_transfers_in":  vehicle_total_transfers_in,
            "vehicle_total_transfers_out": vehicle_total_transfers_out,
            "net_transfers":               net_transfers,
            "vehicle_details":             vehicle_details,
            "fund_total_value":            fund_total_value,
            "fund_total_contributions":    fund_total_contributions,
            "fund_total_distributions":    fund_total_distributions,
            "fund_details":                fund_details,
            "value_variance":              value_variance,
            "additions_variance":          additions_variance,
            "distributions_variance":      distributions_variance,
        })

    return render_template("reports/reconciliation.html",
        pool_rows=pool_rows,
        pools=pools,
        pool_filter=pool_filter,
        year=year, month=month,
        current_year=datetime.utcnow().year,
    )


@reports_bp.route("/earnings-allocation")
@login_required
def earnings_allocation():
    """Show month-by-month earnings allocation detail for each fund.

    For each closed month, shows:
    - Prior month units, new units from contributions, units redeemed from distributions
    - Total units held, pool unit price, fund value
    - Earnings = fund_value - corpus
    - Earnings this month = change in fund value - new contributions + distributions
    """
    from datetime import datetime
    pool_filter = request.args.get("pool_id", type=int)
    fund_filter = request.args.get("fund_id", type=int)

    pools = InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()
    funds_query = Fund.query.filter_by(is_active=True)
    if pool_filter:
        funds_query = funds_query.filter_by(pool_id=pool_filter)

    all_funds = funds_query.order_by(Fund.name).all()

    # If a specific fund is selected, show only that fund
    if fund_filter:
        target_funds = [f for f in all_funds if f.id == fund_filter]
    else:
        target_funds = all_funds

    fund_rows = []
    for fund in target_funds:
        # Get all monthly snapshots for this fund, ordered chronologically
        snapshots = (FundMonthlySnapshot.query
            .filter_by(fund_id=fund.id)
            .order_by(FundMonthlySnapshot.year.asc(), FundMonthlySnapshot.month.asc())
            .all())

        if not snapshots:
            continue

        months_data = []
        prev_value = Decimal("0")
        prev_units = Decimal("0")

        for snap in snapshots:
            # Contributions buying in this month
            contribs = FundContribution.query.filter_by(
                fund_id=fund.id, buy_in_year=snap.year, buy_in_month=snap.month,
                is_voided=False).all()
            new_contrib_amount = sum(Decimal(str(c.amount)) for c in contribs)
            new_units = sum(Decimal(str(c.units_purchased or 0)) for c in contribs)

            # Distributions this month
            dists = Distribution.query.filter_by(fund_id=fund.id, is_voided=False)\
                .filter(db.extract('year', Distribution.distribution_date) == snap.year,
                        db.extract('month', Distribution.distribution_date) == snap.month).all()
            dist_amount = sum(Decimal(str(d.amount)) for d in dists)
            units_redeemed = Decimal("0")
            if snap.unit_price and Decimal(str(snap.unit_price)) > 0 and dist_amount > 0:
                units_redeemed = dist_amount / Decimal(str(snap.unit_price))

            fund_value = Decimal(str(snap.fund_value))
            corpus = Decimal(str(snap.corpus_balance))
            earnings_cumulative = fund_value - corpus

            # Earnings THIS month = change in value - new money + distributions
            earnings_this_month = fund_value - prev_value - new_contrib_amount + dist_amount

            months_data.append({
                "year": snap.year,
                "month": snap.month,
                "prior_units": prev_units,
                "new_units": new_units,
                "units_redeemed": units_redeemed,
                "total_units": Decimal(str(snap.units_held)),
                "unit_price": Decimal(str(snap.unit_price)),
                "new_contributions": new_contrib_amount,
                "distributions": dist_amount,
                "fund_value": fund_value,
                "corpus": corpus,
                "earnings_cumulative": earnings_cumulative,
                "earnings_this_month": earnings_this_month,
            })

            prev_value = fund_value
            prev_units = Decimal(str(snap.units_held))

        fund_rows.append({
            "fund": fund,
            "months": months_data,
        })

    return render_template("reports/earnings_allocation.html",
        fund_rows=fund_rows,
        all_funds=all_funds,
        pools=pools,
        pool_filter=pool_filter,
        fund_filter=fund_filter,
        current_year=datetime.utcnow().year,
    )


@reports_bp.route("/fund-summary")
@login_required
def fund_summary():
    """All funds with current corpus, accumulated earnings, and available drawdown."""
    from datetime import datetime
    pool_filter = request.args.get("pool_id", type=int)
    restriction_filter = request.args.get("restriction")

    query = Fund.query.filter_by(is_active=True)
    if pool_filter:
        query = query.filter_by(pool_id=pool_filter)
    if restriction_filter:
        query = query.filter_by(restriction=restriction_filter)

    funds = query.order_by(Fund.name).all()
    pools = InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()

    rows = []
    total_corpus      = Decimal("0")
    total_value       = Decimal("0")
    total_earnings    = Decimal("0")
    total_drawdown    = Decimal("0")
    underwater_count  = 0

    for fund in funds:
        corpus = Decimal(str(fund.total_corpus))
        current_val = Decimal(str(fund.current_value))
        earnings = current_val - corpus
        spend_rate = float(fund.spend_rate or 0)
        drawdown = Decimal(str(fund.distributable_amount))
        is_uw = fund.is_underwater

        total_corpus   += corpus
        total_value    += current_val
        total_earnings += earnings
        total_drawdown += drawdown
        if is_uw:
            underwater_count += 1

        # Get total distributions ever paid
        total_distributed = db.session.query(db.func.sum(Distribution.amount))\
            .filter_by(fund_id=fund.id, is_voided=False).scalar()
        total_distributed = Decimal(str(total_distributed or 0))

        rows.append({
            "fund": fund,
            "pool_name": fund.pool.name if fund.pool else "—",
            "corpus": corpus,
            "current_value": current_val,
            "earnings": earnings,
            "spend_rate_pct": spend_rate * 100,
            "drawdown": drawdown,
            "total_distributed": total_distributed,
            "is_underwater": is_uw,
            "units_held": Decimal(str(fund.current_units)),
        })

    return render_template("reports/fund_summary.html",
        rows=rows,
        pools=pools,
        pool_filter=pool_filter,
        restriction_filter=restriction_filter,
        total_corpus=total_corpus,
        total_value=total_value,
        total_earnings=total_earnings,
        total_drawdown=total_drawdown,
        underwater_count=underwater_count,
        FundRestriction=FundRestriction,
    )
