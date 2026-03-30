from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, send_file
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, DecimalField, DateField, SelectField, BooleanField
from wtforms.validators import DataRequired, Optional, NumberRange
from decimal import Decimal
from datetime import datetime, date
import io

from models import (
    db, Fund, FundRestriction, FundContribution, FundMonthlySnapshot,
    Distribution, InvestmentPool, PoolMonthlySnapshot, AuditLog, AuditAction,
    Document, Donor, GiftType
)


def _month_is_closed(pool_id, year, month):
    """Return True if the given pool/year/month snapshot is already closed."""
    snap = PoolMonthlySnapshot.query.filter_by(
        pool_id=pool_id, year=year, month=month, is_closed=True).first()
    return snap is not None

funds_bp = Blueprint("funds", __name__)


# ── Forms ──────────────────────────────────────

class FundForm(FlaskForm):
    name                    = StringField("Fund Name", validators=[DataRequired()])
    fund_number             = StringField("Fund Number / Code", validators=[Optional()])
    pool_id                 = SelectField("Investment Pool", coerce=int, validators=[DataRequired()])
    restriction             = SelectField("Restriction Type", validators=[DataRequired()],
                                choices=[
                                    ("permanently_restricted",  "Permanently Restricted"),
                                    ("temporarily_restricted",  "Temporarily Restricted"),
                                    ("unrestricted",            "Unrestricted"),
                                ])
    restriction_purpose     = TextAreaField("Restriction Purpose / Notes", validators=[Optional()])
    spend_rate              = DecimalField("Annual Spend Rate (%)", places=2,
                                validators=[DataRequired(), NumberRange(0, 100)], default=5.0)
    allow_underwater_spend  = BooleanField("Allow distributions when fund is underwater")
    inception_date          = DateField("Inception Date", validators=[DataRequired()], default=date.today)
    notes                   = TextAreaField("Additional Notes", validators=[Optional()])


class ContributionForm(FlaskForm):
    donor_id            = SelectField("Donor", coerce=int, validators=[DataRequired()])
    gift_type           = SelectField("Gift Type", validators=[DataRequired()],
                            choices=[
                                ("cash", "Cash"),
                                ("check", "Check"),
                                ("wire", "Wire Transfer"),
                                ("stock", "Stock / Securities"),
                                ("real_estate", "Real Estate"),
                                ("in_kind", "In-Kind"),
                                ("pledge", "Pledge"),
                                ("bequest", "Bequest"),
                                ("other", "Other"),
                            ])
    amount              = DecimalField("Amount ($)", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    contribution_date   = DateField("Contribution Date", validators=[DataRequired()], default=date.today)
    buy_in_year         = SelectField("Buy-In Year", coerce=int, validators=[DataRequired()])
    buy_in_month        = SelectField("Buy-In Month", coerce=int, validators=[DataRequired()],
                            choices=[(i, datetime(2000, i, 1).strftime("%B")) for i in range(1, 13)])
    notes               = TextAreaField("Notes", validators=[Optional()])
    document            = FileField("Attach Document", validators=[
                            FileAllowed(["pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "gif", "tif", "tiff"],
                                        "Allowed: PDF, Word, Excel, Images")])


# ── Fund CRUD ──────────────────────────────────

@funds_bp.route("/")
@login_required
def index():
    pools = InvestmentPool.query.filter_by(is_active=True).all()
    pool_filter = request.args.get("pool_id", type=int)
    restriction_filter = request.args.get("restriction")
    query = Fund.query.filter_by(is_active=True)
    if pool_filter:
        query = query.filter_by(pool_id=pool_filter)
    if restriction_filter:
        query = query.filter_by(restriction=restriction_filter)
    funds = query.order_by(Fund.name).all()
    return render_template("funds/index.html",
        funds=funds, pools=pools,
        pool_filter=pool_filter, restriction_filter=restriction_filter,
        FundRestriction=FundRestriction)


@funds_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_fund():
    if not current_user.can_edit:
        abort(403)
    form = FundForm()
    form.pool_id.choices = [(p.id, p.name) for p in InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()]
    current_year = datetime.utcnow().year
    if form.validate_on_submit():
        fund = Fund(
            pool_id=form.pool_id.data,
            name=form.name.data,
            fund_number=form.fund_number.data or None,
            restriction=FundRestriction(form.restriction.data),
            restriction_purpose=form.restriction_purpose.data,
            spend_rate=form.spend_rate.data / 100,  # Store as decimal
            allow_underwater_spend=form.allow_underwater_spend.data,
            inception_date=form.inception_date.data,
            notes=form.notes.data,
            created_by_id=current_user.id,
        )
        db.session.add(fund)
        db.session.flush()
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="Fund", entity_id=fund.id,
            description=f"Created fund '{fund.name}'", ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Fund '{fund.name}' created. Add an initial contribution to get started.", "success")
        return redirect(url_for("funds.detail", fund_id=fund.id))
    return render_template("funds/form.html", form=form, title="New Fund", current_year=current_year)


@funds_bp.route("/<int:fund_id>")
@login_required
def detail(fund_id):
    fund = Fund.query.get_or_404(fund_id)
    contributions = FundContribution.query.filter_by(fund_id=fund_id, is_voided=False)\
        .order_by(FundContribution.contribution_date.desc()).all()
    void_contributions = FundContribution.query.filter_by(fund_id=fund_id, is_voided=True)\
        .order_by(FundContribution.contribution_date.desc()).all()
    snapshots = FundMonthlySnapshot.query.filter_by(fund_id=fund_id)\
        .order_by(FundMonthlySnapshot.year.desc(), FundMonthlySnapshot.month.desc()).all()
    distributions = Distribution.query.filter_by(fund_id=fund_id, is_voided=False)\
        .order_by(Distribution.distribution_date.desc()).all()
    void_distributions = Distribution.query.filter_by(fund_id=fund_id, is_voided=True)\
        .order_by(Distribution.distribution_date.desc()).all()
    fund_documents = Document.query.filter_by(entity_type="fund", entity_id=fund_id, is_deleted=False)\
        .order_by(Document.uploaded_at.desc()).all()

    # Chart data: fund value over time
    chart_labels = []
    chart_values = []
    chart_corpus = []
    for s in reversed(snapshots[-24:]):
        chart_labels.append(f"{s.year}-{s.month:02d}")
        chart_values.append(float(s.fund_value or 0))
        chart_corpus.append(float(s.corpus_balance or 0))

    return render_template("funds/detail.html",
        fund=fund,
        contributions=contributions,
        void_contributions=void_contributions,
        snapshots=snapshots,
        distributions=distributions,
        void_distributions=void_distributions,
        fund_documents=fund_documents,
        chart_labels=chart_labels,
        chart_values=chart_values,
        chart_corpus=chart_corpus,
        FundRestriction=FundRestriction,
    )


@funds_bp.route("/<int:fund_id>/edit", methods=["GET", "POST"])
@login_required
def edit_fund(fund_id):
    if not current_user.can_edit:
        abort(403)
    fund = Fund.query.get_or_404(fund_id)
    form = FundForm(obj=fund)
    form.pool_id.choices = [(p.id, p.name) for p in InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()]
    current_year = datetime.utcnow().year
    # Pre-populate spend rate as percentage
    if request.method == "GET":
        form.spend_rate.data = float(fund.spend_rate or 0) * 100
        form.restriction.data = fund.restriction.value

    if form.validate_on_submit():
        fund.name = form.name.data
        fund.fund_number = form.fund_number.data or None
        fund.pool_id = form.pool_id.data
        fund.restriction = FundRestriction(form.restriction.data)
        fund.restriction_purpose = form.restriction_purpose.data
        fund.spend_rate = form.spend_rate.data / 100
        fund.allow_underwater_spend = form.allow_underwater_spend.data
        fund.inception_date = form.inception_date.data
        fund.notes = form.notes.data
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.UPDATE,
            entity_type="Fund", entity_id=fund.id,
            description=f"Updated fund '{fund.name}'", ip_address=request.remote_addr))
        db.session.commit()
        flash("Fund updated.", "success")
        return redirect(url_for("funds.detail", fund_id=fund.id))
    return render_template("funds/form.html", form=form, title="Edit Fund", fund=fund, current_year=current_year)


# ── Contributions ──────────────────────────────

@funds_bp.route("/<int:fund_id>/contributions/new", methods=["GET", "POST"])
@login_required
def new_contribution(fund_id):
    if not current_user.can_edit:
        abort(403)
    fund = Fund.query.get_or_404(fund_id)
    form = ContributionForm()
    current_year = datetime.utcnow().year
    donors = Donor.query.filter_by(is_active=True).order_by(Donor.display_name).all()
    form.donor_id.choices = [(0, "— Select a Donor —")] + [(d.id, d.display_name) for d in donors]
    form.buy_in_year.choices = [(y, str(y)) for y in range(current_year - 5, current_year + 2)]
    if request.method == "GET":
        form.buy_in_year.data = current_year

    if form.validate_on_submit():
        if form.donor_id.data == 0:
            flash("Please select a donor. If this is a new donor, create them first.", "warning")
            return render_template("funds/contribution_form.html", form=form, fund=fund,
                                   current_year=current_year, donors=donors)

        # Block contributions to a closed buy-in month
        if _month_is_closed(fund.pool_id, form.buy_in_year.data, form.buy_in_month.data):
            from datetime import datetime as _dt
            mo_name = _dt(2000, form.buy_in_month.data, 1).strftime("%B")
            flash(
                f"Cannot post a contribution with a buy-in of {mo_name} {form.buy_in_year.data} "
                f"— that month is already closed. Choose an open month or reopen it first.",
                "danger"
            )
            return render_template("funds/contribution_form.html", form=form, fund=fund,
                                   current_year=current_year, donors=donors)

        donor = Donor.query.get(form.donor_id.data)
        contrib = FundContribution(
            fund_id=fund_id,
            donor_id=donor.id,
            donor_name=donor.display_name,
            gift_type=GiftType(form.gift_type.data),
            amount=form.amount.data,
            contribution_date=form.contribution_date.data,
            buy_in_year=form.buy_in_year.data,
            buy_in_month=form.buy_in_month.data,
            notes=form.notes.data,
            created_by_id=current_user.id,
        )
        db.session.add(contrib)
        db.session.flush()

        # Handle document upload
        if form.document.data:
            f = form.document.data
            doc = Document(
                entity_type="contribution",
                entity_id=contrib.id,
                filename=f.filename,
                description=f"Gift document for {donor.display_name} — ${float(form.amount.data):,.2f}",
                mime_type=f.content_type,
                file_data=f.read(),
                file_size=f.content_length or 0,
                uploaded_by_id=current_user.id,
            )
            # Get file size from data if content_length is 0
            if not doc.file_size:
                doc.file_size = len(doc.file_data)
            db.session.add(doc)

        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="FundContribution", entity_id=contrib.id,
            description=f"Added {form.gift_type.data} contribution of ${form.amount.data:,.2f} from '{donor.display_name}' to fund '{fund.name}'",
            ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Contribution of ${float(form.amount.data):,.2f} from {donor.display_name} added.", "success")
        return redirect(url_for("funds.detail", fund_id=fund_id))
    return render_template("funds/contribution_form.html", form=form, fund=fund,
                           current_year=current_year, donors=donors)


@funds_bp.route("/<int:fund_id>/contributions/<int:contrib_id>/void", methods=["POST"])
@login_required
def void_contribution(fund_id, contrib_id):
    if not current_user.can_approve:
        abort(403)
    contrib = FundContribution.query.get_or_404(contrib_id)
    reason = request.form.get("reason", "")
    contrib.is_voided = True
    contrib.voided_reason = reason
    db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.VOID,
        entity_type="FundContribution", entity_id=contrib.id,
        description=f"Voided contribution #{contrib.id} from '{contrib.donor_name}': {reason}",
        ip_address=request.remote_addr))
    db.session.commit()
    flash("Contribution voided.", "warning")
    return redirect(url_for("funds.detail", fund_id=fund_id))


# ── Standalone New Contribution (from sidebar) ──

class StandaloneContributionForm(FlaskForm):
    fund_id             = SelectField("Fund", coerce=int, validators=[DataRequired()])
    donor_id            = SelectField("Donor", coerce=int, validators=[DataRequired()])
    gift_type           = SelectField("Gift Type", validators=[DataRequired()],
                            choices=[
                                ("cash", "Cash"),
                                ("check", "Check"),
                                ("wire", "Wire Transfer"),
                                ("stock", "Stock / Securities"),
                                ("real_estate", "Real Estate"),
                                ("in_kind", "In-Kind"),
                                ("pledge", "Pledge"),
                                ("bequest", "Bequest"),
                                ("other", "Other"),
                            ])
    amount              = DecimalField("Amount ($)", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    contribution_date   = DateField("Contribution Date", validators=[DataRequired()], default=date.today)
    buy_in_year         = SelectField("Buy-In Year", coerce=int, validators=[DataRequired()])
    buy_in_month        = SelectField("Buy-In Month", coerce=int, validators=[DataRequired()],
                            choices=[(i, datetime(2000, i, 1).strftime("%B")) for i in range(1, 13)])
    notes               = TextAreaField("Notes", validators=[Optional()])
    document            = FileField("Attach Document", validators=[
                            FileAllowed(["pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "gif", "tif", "tiff"],
                                        "Allowed: PDF, Word, Excel, Images")])


@funds_bp.route("/contributions/new", methods=["GET", "POST"])
@login_required
def new_contribution_standalone():
    """Create a new contribution — standalone page accessible from sidebar."""
    if not current_user.can_edit:
        abort(403)
    form = StandaloneContributionForm()
    current_year = datetime.utcnow().year

    funds_list = Fund.query.filter_by(is_active=True).order_by(Fund.name).all()
    donors = Donor.query.filter_by(is_active=True).order_by(Donor.display_name).all()
    form.fund_id.choices = [(0, "— Select a Fund —")] + [(f.id, f"{f.name} ({f.pool.name})") for f in funds_list]
    form.donor_id.choices = [(0, "— Select a Donor —")] + [(d.id, d.display_name) for d in donors]
    form.buy_in_year.choices = [(y, str(y)) for y in range(current_year - 5, current_year + 2)]
    if request.method == "GET":
        form.buy_in_year.data = current_year

    if form.validate_on_submit():
        if form.fund_id.data == 0:
            flash("Please select a fund.", "warning")
            return render_template("funds/new_contribution_standalone.html", form=form,
                                   current_year=current_year, donors=donors, funds=funds_list)
        if form.donor_id.data == 0:
            flash("Please select a donor.", "warning")
            return render_template("funds/new_contribution_standalone.html", form=form,
                                   current_year=current_year, donors=donors, funds=funds_list)

        fund = Fund.query.get(form.fund_id.data)

        # Block contributions to a closed buy-in month
        if _month_is_closed(fund.pool_id, form.buy_in_year.data, form.buy_in_month.data):
            from datetime import datetime as _dt
            mo_name = _dt(2000, form.buy_in_month.data, 1).strftime("%B")
            flash(
                f"Cannot post a contribution with a buy-in of {mo_name} {form.buy_in_year.data} "
                f"— that month is already closed. Choose an open month or reopen it first.",
                "danger"
            )
            return render_template("funds/new_contribution_standalone.html", form=form,
                                   current_year=current_year, donors=donors, funds=funds_list)

        donor = Donor.query.get(form.donor_id.data)
        contrib = FundContribution(
            fund_id=fund.id,
            donor_id=donor.id,
            donor_name=donor.display_name,
            gift_type=GiftType(form.gift_type.data),
            amount=form.amount.data,
            contribution_date=form.contribution_date.data,
            buy_in_year=form.buy_in_year.data,
            buy_in_month=form.buy_in_month.data,
            notes=form.notes.data,
            created_by_id=current_user.id,
        )
        db.session.add(contrib)
        db.session.flush()

        if form.document.data:
            f = form.document.data
            doc = Document(
                entity_type="contribution",
                entity_id=contrib.id,
                filename=f.filename,
                description=f"Gift document for {donor.display_name} — ${float(form.amount.data):,.2f}",
                mime_type=f.content_type,
                file_data=f.read(),
                file_size=f.content_length or 0,
                uploaded_by_id=current_user.id,
            )
            if not doc.file_size:
                doc.file_size = len(doc.file_data)
            db.session.add(doc)

        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="FundContribution", entity_id=contrib.id,
            description=f"Added {form.gift_type.data} contribution of ${form.amount.data:,.2f} from '{donor.display_name}' to fund '{fund.name}'",
            ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Contribution of ${float(form.amount.data):,.2f} from {donor.display_name} to {fund.name} added.", "success")
        return redirect(url_for("funds.all_contributions"))

    return render_template("funds/new_contribution_standalone.html", form=form,
                           current_year=current_year, donors=donors, funds=funds_list)


# ── All Contributions (global view) ──────────

@funds_bp.route("/contributions")
@login_required
def all_contributions():
    """List all contributions across all funds with filters."""
    pool_filter = request.args.get("pool_id", type=int)
    fund_filter = request.args.get("fund_id", type=int)
    donor_filter = request.args.get("donor_id", type=int)
    gift_type_filter = request.args.get("gift_type")
    year_filter = request.args.get("year", type=int)

    query = FundContribution.query.filter_by(is_voided=False)
    if fund_filter:
        query = query.filter_by(fund_id=fund_filter)
    if donor_filter:
        query = query.filter_by(donor_id=donor_filter)
    if gift_type_filter:
        query = query.filter_by(gift_type=gift_type_filter)
    if pool_filter:
        fund_ids = [f.id for f in Fund.query.filter_by(pool_id=pool_filter).all()]
        query = query.filter(FundContribution.fund_id.in_(fund_ids))
    if year_filter:
        query = query.filter(db.extract("year", FundContribution.contribution_date) == year_filter)

    contributions = query.order_by(FundContribution.contribution_date.desc()).all()
    total = sum(Decimal(str(c.amount)) for c in contributions)

    pools = InvestmentPool.query.filter_by(is_active=True).order_by(InvestmentPool.name).all()
    funds = Fund.query.filter_by(is_active=True).order_by(Fund.name).all()
    donors = Donor.query.filter_by(is_active=True).order_by(Donor.display_name).all()

    return render_template("funds/all_contributions.html",
        contributions=contributions,
        total=total,
        pools=pools, funds=funds, donors=donors,
        pool_filter=pool_filter, fund_filter=fund_filter,
        donor_filter=donor_filter, gift_type_filter=gift_type_filter,
        year_filter=year_filter,
        GiftType=GiftType,
    )


# ── Contribution Document Download ───────────

@funds_bp.route("/contributions/<int:contrib_id>/document/<int:doc_id>")
@login_required
def download_contribution_doc(contrib_id, doc_id):
    """Download a document attached to a contribution."""
    doc = Document.query.filter_by(id=doc_id, entity_type="contribution",
                                    entity_id=contrib_id, is_deleted=False).first_or_404()
    return send_file(
        io.BytesIO(doc.file_data),
        mimetype=doc.mime_type,
        as_attachment=True,
        download_name=doc.filename,
    )
