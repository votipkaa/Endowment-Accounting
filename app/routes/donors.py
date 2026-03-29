from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Optional, Email
from datetime import datetime

from models import db, Donor, DonorType, FundContribution, Fund, AuditLog, AuditAction

donors_bp = Blueprint("donors", __name__)


# ── Forms ──────────────────────────────────────

class DonorForm(FlaskForm):
    donor_type          = SelectField("Donor Type", validators=[DataRequired()],
                            choices=[
                                ("individual", "Individual"),
                                ("organization", "Organization"),
                                ("foundation", "Foundation"),
                                ("trust", "Trust"),
                                ("estate", "Estate"),
                                ("other", "Other"),
                            ])
    first_name          = StringField("First Name", validators=[Optional()])
    last_name           = StringField("Last Name", validators=[Optional()])
    organization        = StringField("Organization", validators=[Optional()])
    display_name        = StringField("Display Name", validators=[DataRequired()])
    email               = StringField("Email", validators=[Optional(), Email()])
    email_secondary     = StringField("Secondary Email", validators=[Optional(), Email()])
    phone               = StringField("Phone", validators=[Optional()])
    phone_secondary     = StringField("Secondary Phone", validators=[Optional()])
    address_line1       = StringField("Address Line 1", validators=[Optional()])
    address_line2       = StringField("Address Line 2", validators=[Optional()])
    city                = StringField("City", validators=[Optional()])
    state               = StringField("State", validators=[Optional()])
    zip_code            = StringField("Zip Code", validators=[Optional()])
    country             = StringField("Country", validators=[Optional()], default="United States")
    notes               = TextAreaField("Notes", validators=[Optional()])


# ── Donor Index ────────────────────────────────

@donors_bp.route("/")
@login_required
def index():
    """List all active donors with search and sort."""
    search_query = request.args.get("search", "").strip()
    sort_by = request.args.get("sort", "display_name")  # display_name, total_given, gift_count

    query = Donor.query.filter_by(is_active=True)

    # Apply search filter
    if search_query:
        query = query.filter(Donor.display_name.ilike(f"%{search_query}%"))

    # Apply sorting
    if sort_by == "total_given":
        # Note: This sorts in Python after fetching, as it's a property
        donors = query.all()
        donors.sort(key=lambda d: d.total_given, reverse=True)
    elif sort_by == "gift_count":
        donors = query.all()
        donors.sort(key=lambda d: d.gift_count, reverse=True)
    else:  # display_name (default)
        donors = query.order_by(Donor.display_name).all()

    return render_template("donors/index.html",
        donors=donors,
        search_query=search_query,
        sort_by=sort_by,
    )


# ── Create Donor ───────────────────────────────

@donors_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_donor():
    """Create a new donor."""
    if not current_user.can_edit:
        abort(403)

    form = DonorForm()

    if form.validate_on_submit():
        donor = Donor(
            donor_type=DonorType(form.donor_type.data),
            first_name=form.first_name.data or None,
            last_name=form.last_name.data or None,
            organization=form.organization.data or None,
            display_name=form.display_name.data,
            email=form.email.data or None,
            email_secondary=form.email_secondary.data or None,
            phone=form.phone.data or None,
            phone_secondary=form.phone_secondary.data or None,
            address_line1=form.address_line1.data or None,
            address_line2=form.address_line2.data or None,
            city=form.city.data or None,
            state=form.state.data or None,
            zip_code=form.zip_code.data or None,
            country=form.country.data or "United States",
            notes=form.notes.data or None,
            created_by_id=current_user.id,
        )
        db.session.add(donor)
        db.session.flush()
        db.session.add(AuditLog(
            user_id=current_user.id,
            action=AuditAction.CREATE,
            entity_type="Donor",
            entity_id=donor.id,
            description=f"Created donor '{donor.display_name}'",
            ip_address=request.remote_addr,
        ))
        db.session.commit()
        flash(f"Donor '{donor.display_name}' created successfully.", "success")
        return redirect(url_for("donors.detail", donor_id=donor.id))

    return render_template("donors/form.html", form=form, title="New Donor")


# ── Donor Detail ───────────────────────────────

@donors_bp.route("/<int:donor_id>")
@login_required
def detail(donor_id):
    """Show donor info and all their contributions."""
    donor = Donor.query.get_or_404(donor_id)

    # Get all contributions for this donor, sorted newest first
    contributions = FundContribution.query.filter_by(
        donor_id=donor_id,
        is_voided=False
    ).order_by(FundContribution.contribution_date.desc()).all()

    # Build a summary of total given per fund
    fund_summary = {}
    for contrib in contributions:
        fund = Fund.query.get(contrib.fund_id)
        if fund:
            if fund.id not in fund_summary:
                fund_summary[fund.id] = {
                    "name": fund.name,
                    "total": 0,
                }
            fund_summary[fund.id]["total"] += float(contrib.amount or 0)

    return render_template("donors/detail.html",
        donor=donor,
        contributions=contributions,
        fund_summary=fund_summary,
    )


# ── Edit Donor ─────────────────────────────────

@donors_bp.route("/<int:donor_id>/edit", methods=["GET", "POST"])
@login_required
def edit_donor(donor_id):
    """Edit an existing donor."""
    if not current_user.can_edit:
        abort(403)

    donor = Donor.query.get_or_404(donor_id)
    form = DonorForm(obj=donor)

    if form.validate_on_submit():
        # Update donor fields
        donor.donor_type = DonorType(form.donor_type.data)
        donor.first_name = form.first_name.data or None
        donor.last_name = form.last_name.data or None
        donor.organization = form.organization.data or None
        donor.display_name = form.display_name.data
        donor.email = form.email.data or None
        donor.email_secondary = form.email_secondary.data or None
        donor.phone = form.phone.data or None
        donor.phone_secondary = form.phone_secondary.data or None
        donor.address_line1 = form.address_line1.data or None
        donor.address_line2 = form.address_line2.data or None
        donor.city = form.city.data or None
        donor.state = form.state.data or None
        donor.zip_code = form.zip_code.data or None
        donor.country = form.country.data or "United States"
        donor.notes = form.notes.data or None

        db.session.add(AuditLog(
            user_id=current_user.id,
            action=AuditAction.UPDATE,
            entity_type="Donor",
            entity_id=donor.id,
            description=f"Updated donor '{donor.display_name}'",
            ip_address=request.remote_addr,
        ))
        db.session.commit()
        flash(f"Donor '{donor.display_name}' updated successfully.", "success")
        return redirect(url_for("donors.detail", donor_id=donor.id))

    # Pre-populate form on GET
    if request.method == "GET":
        form.donor_type.data = donor.donor_type.value

    return render_template("donors/form.html", form=form, title="Edit Donor", donor=donor)
