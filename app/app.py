"""
Endowment Accounting Software — Main Application
"""

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, DecimalField, DateField, TextAreaField, BooleanField, IntegerField
from wtforms.validators import DataRequired, Email, Optional, NumberRange
from sqlalchemy import func
from decimal import Decimal
from datetime import datetime, date
import os
import traceback

from models import (
    db, User, UserRole, FundRestriction, AuditAction,
    InvestmentPool, InvestmentVehicle, VehicleMonthlyActivity, PoolMonthlySnapshot,
    Fund, FundContribution, FundMonthlySnapshot,
    Distribution, AuditLog
)

# ─────────────────────────────────────────────
# App Factory
# ─────────────────────────────────────────────

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    # Render provides DATABASE_URL as postgres:// but SQLAlchemy needs postgresql://
    db_url = os.environ.get("DATABASE_URL",
        f"sqlite:///{os.path.join(os.path.dirname(__file__), 'endowment.db')}")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit

    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from routes.auth import auth_bp
    from routes.pools import pools_bp
    from routes.funds import funds_bp
    from routes.distributions import distributions_bp
    from routes.reports import reports_bp
    from routes.admin import admin_bp
    from routes.documents import documents_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(pools_bp, url_prefix="/pools")
    app.register_blueprint(funds_bp, url_prefix="/funds")
    app.register_blueprint(distributions_bp, url_prefix="/distributions")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(documents_bp, url_prefix="/documents")

    # Dashboard route
    @app.route("/")
    @login_required
    def dashboard():
        pools = InvestmentPool.query.filter_by(is_active=True).all()
        funds = Fund.query.filter_by(is_active=True).all()

        # Summary stats
        total_pool_value = sum(f.current_value for f in funds)
        total_corpus = sum(f.total_corpus for f in funds)
        total_distributable = sum(f.distributable_amount for f in funds)
        underwater_count = sum(1 for f in funds if f.is_underwater)

        # Recent activity
        recent_distributions = Distribution.query.filter_by(is_voided=False)\
            .order_by(Distribution.distribution_date.desc()).limit(5).all()
        recent_audit = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()

        return render_template("dashboard.html",
            pools=pools,
            funds=funds,
            total_pool_value=total_pool_value,
            total_corpus=total_corpus,
            total_distributable=total_distributable,
            underwater_count=underwater_count,
            recent_distributions=recent_distributions,
            recent_audit=recent_audit,
        )

    # Audit helper — accessible from all routes
    @app.context_processor
    def inject_helpers():
        sidebar_pools = []
        try:
            from flask_login import current_user as cu
            if cu.is_authenticated:
                sidebar_pools = (InvestmentPool.query
                                 .filter_by(is_active=True)
                                 .order_by(InvestmentPool.name)
                                 .all())
        except Exception:
            pass
        return dict(
            UserRole=UserRole,
            FundRestriction=FundRestriction,
            now=datetime.utcnow(),
            sidebar_pools=sidebar_pools,
        )

    # Temporary debug error handler — shows the full traceback in the browser
    # Remove this once the 500 error is diagnosed
    @app.errorhandler(500)
    def handle_500(e):
        tb = traceback.format_exc()
        return (
            f"<h2>500 Internal Server Error</h2>"
            f"<p>Please copy this and send to your developer:</p>"
            f"<pre style='background:#f8f8f8;padding:1rem;font-size:.85rem;overflow:auto'>{tb}</pre>",
            500,
        )

    # Create tables and seed admin on first run
    with app.app_context():
        try:
            db.create_all()
            _seed_admin()
        except Exception as exc:
            print(f"[STARTUP ERROR] db.create_all() failed: {exc}")
            traceback.print_exc()

    return app


def _seed_admin():
    """Create a default admin user if none exists."""
    if not User.query.filter_by(role=UserRole.ADMIN).first():
        admin = User(
            username="admin",
            email="admin@foundation.org",
            role=UserRole.ADMIN,
            is_active=True,
        )
        admin.set_password("Admin1234!")
        db.session.add(admin)
        db.session.commit()
        print("✓ Default admin created: username=admin  password=Admin1234!")


def log_action(action, entity_type=None, entity_id=None, description=None):
    """Write an audit log entry."""
    entry = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        ip_address=request.remote_addr,
    )
    db.session.add(entry)


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
