from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import DecimalField, DateField, TextAreaField, SelectField, StringField
from wtforms.validators import DataRequired, Optional, NumberRange
from decimal import Decimal
from datetime import datetime, date

from models import (
    db, Fund, Distribution, AuditLog, AuditAction, FundRestriction, InvestmentPool
)

distributions_bp = Blueprint("distributions", __name__)


class DistributionForm(FlaskForm):
    fund_id             = SelectField("Fund", coerce=int, validators=[DataRequired()])
    amount              = DecimalField("Amount ($)", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    distribution_date   = DateField("Distribution Date", validators=[DataRequired()], default=date.today)
    recipient           = StringField("Recipient / Payee", validators=[Optional()])
    purpose             = TextAreaField("Purpose / Description", validators=[Optional()])
    notes               = TextAreaField("Internal Notes", validators=[Optional()])


@distributions_bp.route("/")
@login_required
def index():
    pool_filter = request.args.get("pool_id", type=int)
    query = Distribution.query.filter_by(is_voided=False)
    pools = InvestmentPool.query.filter_by(is_active=True).all()
    funds_for_select = Fund.query.filter_by(is_active=True).order_by(Fund.name).all()

    if pool_filter:
        fund_ids = [f.id for f in Fund.query.filter_by(pool_id=pool_filter).all()]
        query = query.filter(Distribution.fund_id.in_(fund_ids))

    distributions = query.order_by(Distribution.distribution_date.desc()).all()
    return render_template("distributions/index.html",
        distributions=distributions, pools=pools,
        pool_filter=pool_filter, funds_for_select=funds_for_select)


@distributions_bp.route("/new", methods=["GET", "POST"])
@distributions_bp.route("/new/<int:fund_id>", methods=["GET", "POST"])
@login_required
def new_distribution(fund_id=None):
    if not current_user.can_edit:
        abort(403)
    form = DistributionForm()
    funds = Fund.query.filter_by(is_active=True).order_by(Fund.name).all()
    form.fund_id.choices = [(f.id, f"{f.name} (${f.current_value:,.2f} available)") for f in funds]

    if fund_id:
        form.fund_id.data = fund_id

    selected_fund = None
    if form.fund_id.data:
        selected_fund = Fund.query.get(form.fund_id.data)

    if form.validate_on_submit():
        target_fund = Fund.query.get(form.fund_id.data)
        if not target_fund:
            flash("Invalid fund selected.", "danger")
            return render_template("distributions/form.html", form=form, funds=funds, selected_fund=None)

        # Validation checks
        amt = Decimal(str(form.amount.data))
        current_val = Decimal(str(target_fund.current_value))

        if amt > current_val:
            flash(f"Distribution amount ${float(amt):,.2f} exceeds fund value ${float(current_val):,.2f}.", "danger")
            return render_template("distributions/form.html", form=form, funds=funds, selected_fund=target_fund)

        if target_fund.is_underwater and not target_fund.allow_underwater_spend:
            flash(f"Fund '{target_fund.name}' is underwater and not permitted to distribute. Adjust the fund settings to allow underwater spending.", "danger")
            return render_template("distributions/form.html", form=form, funds=funds, selected_fund=target_fund)

        dist = Distribution(
            fund_id=form.fund_id.data,
            amount=form.amount.data,
            distribution_date=form.distribution_date.data,
            recipient=form.recipient.data,
            purpose=form.purpose.data,
            notes=form.notes.data,
            created_by_id=current_user.id,
        )
        db.session.add(dist)
        db.session.flush()
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="Distribution", entity_id=dist.id,
            description=f"Recorded distribution of ${float(form.amount.data):,.2f} from fund '{target_fund.name}'",
            ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Distribution of ${float(form.amount.data):,.2f} recorded from '{target_fund.name}'.", "success")
        return redirect(url_for("funds.detail", fund_id=target_fund.id))

    return render_template("distributions/form.html", form=form, funds=funds, selected_fund=selected_fund)


@distributions_bp.route("/<int:dist_id>/void", methods=["POST"])
@login_required
def void_distribution(dist_id):
    if not current_user.can_approve:
        abort(403)
    dist = Distribution.query.get_or_404(dist_id)
    reason = request.form.get("reason", "")
    dist.is_voided    = True
    dist.voided_reason = reason
    dist.voided_at    = datetime.utcnow()
    dist.voided_by_id = current_user.id
    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.VOID,
        entity_type="Distribution", entity_id=dist.id,
        description=f"Voided distribution #{dist.id} of ${float(dist.amount):,.2f}: {reason}",
        ip_address=request.remote_addr))
    db.session.commit()
    flash("Distribution voided.", "warning")
    next_url = request.form.get("next") or url_for("distributions.index")
    return redirect(next_url)


@distributions_bp.route("/batch", methods=["GET", "POST"])
@login_required
def batch_distribution():
    """Record distributions for multiple funds at once."""
    if not current_user.can_edit:
        abort(403)
    funds = Fund.query.filter_by(is_active=True).order_by(Fund.name).all()

    if request.method == "POST":
        dist_date_str = request.form.get("distribution_date")
        purpose = request.form.get("purpose", "")
        try:
            dist_date = datetime.strptime(dist_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            flash("Invalid distribution date.", "danger")
            return render_template("distributions/batch.html", funds=funds)

        created_count = 0
        errors = []
        for fund in funds:
            amt_str = request.form.get(f"amount_{fund.id}", "").strip()
            if not amt_str:
                continue
            try:
                amt = Decimal(amt_str)
                if amt <= 0:
                    continue
            except Exception:
                errors.append(f"Invalid amount for {fund.name}")
                continue

            if fund.is_underwater and not fund.allow_underwater_spend:
                errors.append(f"{fund.name} is underwater — skipped.")
                continue

            dist = Distribution(
                fund_id=fund.id,
                amount=amt,
                distribution_date=dist_date,
                purpose=purpose,
                created_by_id=current_user.id,
            )
            db.session.add(dist)
            created_count += 1

        if errors:
            for e in errors:
                flash(e, "warning")

        db.session.commit()
        flash(f"{created_count} distribution(s) recorded.", "success")
        return redirect(url_for("distributions.index"))

    # Pre-populate with distributable amounts
    return render_template("distributions/batch.html", funds=funds)
