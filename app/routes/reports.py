from flask import Blueprint, render_template, request
from flask_login import login_required
from decimal import Decimal

from models import db, Fund, FundRestriction, InvestmentPool, Distribution, AuditLog

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
