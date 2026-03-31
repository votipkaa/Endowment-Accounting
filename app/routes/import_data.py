"""
CSV batch import routes for onboarding existing foundations.
Supports importing donors and historical gifts/contributions.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, Response
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import SelectField
from wtforms.validators import DataRequired
from decimal import Decimal, InvalidOperation
from datetime import datetime
import csv
import io

from models import (
    db, Donor, DonorType, Fund, FundContribution, GiftType,
    InvestmentPool, AuditLog, AuditAction
)

import_bp = Blueprint("import_data", __name__)


# ── Forms ──────────────────────────────────────

class DonorImportForm(FlaskForm):
    csv_file = FileField("CSV File", validators=[
        FileRequired(),
        FileAllowed(["csv"], "Only CSV files are allowed.")
    ])


class GiftImportForm(FlaskForm):
    csv_file = FileField("CSV File", validators=[
        FileRequired(),
        FileAllowed(["csv"], "Only CSV files are allowed.")
    ])
    default_fund_id = SelectField("Default Fund (if not specified in CSV)", coerce=int,
                                   validators=[DataRequired()])


# ── Import Hub ─────────────────────────────────

@import_bp.route("/")
@login_required
def index():
    if not current_user.can_edit:
        abort(403)
    return render_template("import/index.html")


# ── Donor CSV Import ──────────────────────────

@import_bp.route("/donors", methods=["GET", "POST"])
@login_required
def import_donors():
    """Import donors from a CSV file."""
    if not current_user.can_edit:
        abort(403)

    form = DonorImportForm()

    if form.validate_on_submit():
        csv_file = form.csv_file.data
        try:
            content = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            csv_file.seek(0)
            content = csv_file.read().decode("latin-1")

        reader = csv.DictReader(io.StringIO(content))

        # Normalise header names: strip whitespace, lowercase
        if reader.fieldnames:
            reader.fieldnames = [f.strip().lower().replace(" ", "_") for f in reader.fieldnames]

        created = 0
        skipped = 0
        errors = []

        for row_num, row in enumerate(reader, start=2):
            # Clean up row values
            row = {k: (v.strip() if v else "") for k, v in row.items()}

            # Required: display_name (or first_name + last_name)
            display_name = row.get("display_name", "")
            first_name = row.get("first_name", "")
            last_name = row.get("last_name", "")

            if not display_name:
                if first_name or last_name:
                    display_name = f"{first_name} {last_name}".strip()
                else:
                    errors.append(f"Row {row_num}: Missing display_name — skipped.")
                    skipped += 1
                    continue

            # Check for duplicate by display_name
            existing = Donor.query.filter(
                db.func.lower(Donor.display_name) == display_name.lower()
            ).first()
            if existing:
                skipped += 1
                continue

            # Parse donor type
            dtype_str = row.get("donor_type", "individual").lower()
            try:
                dtype = DonorType(dtype_str)
            except ValueError:
                dtype = DonorType.INDIVIDUAL

            donor = Donor(
                donor_type=dtype,
                first_name=first_name or None,
                last_name=last_name or None,
                organization=row.get("organization") or None,
                display_name=display_name,
                email=row.get("email") or None,
                email_secondary=row.get("email_secondary") or None,
                phone=row.get("phone") or None,
                phone_secondary=row.get("phone_secondary") or None,
                address_line1=row.get("address_line1") or row.get("address") or None,
                address_line2=row.get("address_line2") or None,
                city=row.get("city") or None,
                state=row.get("state") or None,
                zip_code=row.get("zip_code") or row.get("zip") or None,
                country=row.get("country") or "United States",
                notes=row.get("notes") or None,
                created_by_id=current_user.id,
            )
            db.session.add(donor)
            created += 1

        if created > 0:
            db.session.add(AuditLog(
                user_id=current_user.id,
                action=AuditAction.CREATE,
                entity_type="Donor",
                description=f"CSV import: created {created} donor(s), skipped {skipped}",
                ip_address=request.remote_addr,
            ))
            db.session.commit()

        if errors:
            for e in errors[:10]:
                flash(e, "warning")
            if len(errors) > 10:
                flash(f"… and {len(errors) - 10} more errors.", "warning")

        flash(f"Import complete: {created} donor(s) created, {skipped} skipped (duplicate or missing name).", "success")
        return redirect(url_for("import_data.index"))

    return render_template("import/donors.html", form=form)


# ── Gift / Contribution CSV Import ────────────

@import_bp.route("/gifts", methods=["GET", "POST"])
@login_required
def import_gifts():
    """Import historical gifts/contributions from a CSV file."""
    if not current_user.can_edit:
        abort(403)

    form = GiftImportForm()
    funds = Fund.query.filter_by(is_active=True).order_by(Fund.name).all()
    form.default_fund_id.choices = [(0, "— Use fund_name column in CSV —")] + \
        [(f.id, f"{f.name} ({f.pool.name})") for f in funds]

    if form.validate_on_submit():
        csv_file = form.csv_file.data
        try:
            content = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            csv_file.seek(0)
            content = csv_file.read().decode("latin-1")

        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames:
            reader.fieldnames = [f.strip().lower().replace(" ", "_") for f in reader.fieldnames]

        default_fund_id = form.default_fund_id.data

        # Build lookup caches
        fund_cache = {f.name.lower(): f for f in funds}
        fund_id_cache = {f.id: f for f in funds}
        donor_cache = {d.display_name.lower(): d for d in
                       Donor.query.filter_by(is_active=True).all()}

        created = 0
        skipped = 0
        errors = []
        auto_donors = 0

        for row_num, row in enumerate(reader, start=2):
            row = {k: (v.strip() if v else "") for k, v in row.items()}

            # Determine fund
            fund = None
            fund_name = row.get("fund_name", "") or row.get("fund", "")
            if fund_name:
                fund = fund_cache.get(fund_name.lower())
                if not fund:
                    errors.append(f"Row {row_num}: Fund '{fund_name}' not found — skipped.")
                    skipped += 1
                    continue
            elif default_fund_id and default_fund_id > 0:
                fund = fund_id_cache.get(default_fund_id)
            if not fund:
                errors.append(f"Row {row_num}: No fund specified and no default selected — skipped.")
                skipped += 1
                continue

            # Amount
            amt_str = row.get("amount", "").replace(",", "").replace("$", "")
            try:
                amt = Decimal(amt_str)
                if amt <= 0:
                    errors.append(f"Row {row_num}: Amount must be positive — skipped.")
                    skipped += 1
                    continue
            except (InvalidOperation, ValueError):
                errors.append(f"Row {row_num}: Invalid amount '{row.get('amount', '')}' — skipped.")
                skipped += 1
                continue

            # Date
            date_str = row.get("contribution_date", "") or row.get("date", "") or row.get("gift_date", "")
            contrib_date = None
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d/%m/%Y"):
                try:
                    contrib_date = datetime.strptime(date_str, fmt).date()
                    break
                except (ValueError, TypeError):
                    continue
            if not contrib_date:
                errors.append(f"Row {row_num}: Invalid date '{date_str}' — skipped.")
                skipped += 1
                continue

            # Donor (match by name, auto-create if needed)
            donor_name = row.get("donor_name", "") or row.get("donor", "") or row.get("display_name", "")
            donor = None
            if donor_name:
                donor = donor_cache.get(donor_name.lower())
                if not donor:
                    # Auto-create donor
                    donor = Donor(
                        donor_type=DonorType.INDIVIDUAL,
                        display_name=donor_name,
                        created_by_id=current_user.id,
                    )
                    db.session.add(donor)
                    db.session.flush()
                    donor_cache[donor_name.lower()] = donor
                    auto_donors += 1

            # Gift type
            gtype_str = row.get("gift_type", "check").lower()
            try:
                gift_type = GiftType(gtype_str)
            except ValueError:
                gift_type = GiftType.CHECK

            # Buy-in month (default to contribution month)
            buy_in_year = contrib_date.year
            buy_in_month = contrib_date.month
            if row.get("buy_in_year"):
                try:
                    buy_in_year = int(row["buy_in_year"])
                except ValueError:
                    pass
            if row.get("buy_in_month"):
                try:
                    buy_in_month = int(row["buy_in_month"])
                except ValueError:
                    pass

            contrib = FundContribution(
                fund_id=fund.id,
                donor_id=donor.id if donor else None,
                donor_name=donor.display_name if donor else (donor_name or "Unknown"),
                gift_type=gift_type,
                amount=amt,
                contribution_date=contrib_date,
                buy_in_year=buy_in_year,
                buy_in_month=buy_in_month,
                notes=row.get("notes", "") or f"CSV import",
                created_by_id=current_user.id,
            )
            db.session.add(contrib)
            created += 1

        if created > 0 or auto_donors > 0:
            db.session.add(AuditLog(
                user_id=current_user.id,
                action=AuditAction.CREATE,
                entity_type="FundContribution",
                description=f"CSV import: created {created} gift(s), auto-created {auto_donors} donor(s), skipped {skipped}",
                ip_address=request.remote_addr,
            ))
            db.session.commit()

        if errors:
            for e in errors[:10]:
                flash(e, "warning")
            if len(errors) > 10:
                flash(f"… and {len(errors) - 10} more errors.", "warning")

        msg = f"Import complete: {created} gift(s) created"
        if auto_donors > 0:
            msg += f", {auto_donors} new donor(s) auto-created"
        if skipped > 0:
            msg += f", {skipped} skipped"
        flash(msg + ".", "success")
        return redirect(url_for("import_data.index"))

    return render_template("import/gifts.html", form=form, funds=funds)


# ── CSV Templates ─────────────────────────────

@import_bp.route("/template/donors")
@login_required
def donor_template():
    """Download a sample CSV template for donor imports."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "display_name", "first_name", "last_name", "organization",
        "donor_type", "email", "phone", "address_line1", "address_line2",
        "city", "state", "zip_code", "country", "notes"
    ])
    writer.writerow([
        "John & Jane Smith", "John", "Smith", "",
        "individual", "john@example.com", "555-0100", "123 Main St", "",
        "Anytown", "CA", "90210", "United States", "Annual donor"
    ])
    writer.writerow([
        "Acme Foundation", "", "", "Acme Foundation",
        "foundation", "grants@acme.org", "555-0200", "456 Oak Ave", "Suite 100",
        "Bigcity", "NY", "10001", "United States", "Corporate foundation"
    ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=donor_import_template.csv"}
    )


@import_bp.route("/template/gifts")
@login_required
def gift_template():
    """Download a sample CSV template for gift imports."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "donor_name", "fund_name", "amount", "contribution_date",
        "gift_type", "notes"
    ])
    writer.writerow([
        "John & Jane Smith", "Smith Family Endowment", "50000.00", "2020-01-15",
        "check", "Initial gift"
    ])
    writer.writerow([
        "Acme Foundation", "General Scholarship Fund", "25000.00", "2021-06-01",
        "wire", "Annual grant"
    ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=gift_import_template.csv"}
    )
