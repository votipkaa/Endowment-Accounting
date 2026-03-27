from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired
from datetime import datetime

from models import db, User, AuditLog, AuditAction

auth_bp = Blueprint("auth", __name__)


class LoginForm(FlaskForm):
    username  = StringField("Username", validators=[DataRequired()])
    password  = PasswordField("Password", validators=[DataRequired()])
    remember  = BooleanField("Remember me")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and user.is_active:
            login_user(user, remember=form.remember.data)
            user.last_login = datetime.utcnow()
            log = AuditLog(user_id=user.id, action=AuditAction.LOGIN,
                           entity_type="User", entity_id=user.id,
                           description=f"User '{user.username}' logged in",
                           ip_address=request.remote_addr)
            db.session.add(log)
            db.session.commit()
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    log = AuditLog(user_id=current_user.id, action=AuditAction.LOGOUT,
                   entity_type="User", entity_id=current_user.id,
                   description=f"User '{current_user.username}' logged out",
                   ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
