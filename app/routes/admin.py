from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, BooleanField, PasswordField
from wtforms.validators import DataRequired, Email, Optional, EqualTo, Length

from models import db, User, UserRole, AuditLog, AuditAction

admin_bp = Blueprint("admin", __name__)


class UserForm(FlaskForm):
    username    = StringField("Username", validators=[DataRequired(), Length(3, 80)])
    email       = StringField("Email", validators=[DataRequired(), Email()])
    role        = SelectField("Role", validators=[DataRequired()],
                    choices=[
                        (UserRole.ADMIN.value,      "Administrator"),
                        (UserRole.DATA_ENTRY.value,  "Data Entry"),
                        (UserRole.REPORTING.value,   "Reporting"),
                        (UserRole.READ_ONLY.value,   "Read Only"),
                    ])
    is_active   = BooleanField("Active", default=True)
    password    = PasswordField("Password (leave blank to keep current)", validators=[Optional(), Length(min=8)])
    password2   = PasswordField("Confirm Password", validators=[Optional(), EqualTo("password")])


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != UserRole.ADMIN:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    users = User.query.order_by(User.username).all()
    return render_template("admin/users.html", users=users, UserRole=UserRole)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_user():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Username already taken.", "danger")
            return render_template("admin/user_form.html", form=form, title="New User")
        if User.query.filter_by(email=form.email.data).first():
            flash("Email already in use.", "danger")
            return render_template("admin/user_form.html", form=form, title="New User")
        if not form.password.data:
            flash("Password is required for new users.", "danger")
            return render_template("admin/user_form.html", form=form, title="New User")
        user = User(
            username=form.username.data,
            email=form.email.data,
            role=UserRole(form.role.data),
            is_active=form.is_active.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.CREATE,
            entity_type="User", entity_id=user.id,
            description=f"Created user '{user.username}' with role {user.role.value}",
            ip_address=request.remote_addr))
        db.session.commit()
        flash(f"User '{user.username}' created.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, title="New User")


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = UserForm(obj=user)
    if request.method == "GET":
        form.role.data = user.role.value
    if form.validate_on_submit():
        user.username  = form.username.data
        user.email     = form.email.data
        user.role      = UserRole(form.role.data)
        user.is_active = form.is_active.data
        if form.password.data:
            user.set_password(form.password.data)
        db.session.add(AuditLog(user_id=current_user.id, action=AuditAction.UPDATE,
            entity_type="User", entity_id=user.id,
            description=f"Updated user '{user.username}'",
            ip_address=request.remote_addr))
        db.session.commit()
        flash("User updated.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, title=f"Edit User: {user.username}", user=user)
