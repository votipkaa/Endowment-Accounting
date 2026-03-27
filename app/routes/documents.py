from flask import Blueprint, request, redirect, url_for, flash, send_file, abort, current_app
from flask_login import login_required, current_user
from io import BytesIO
from datetime import datetime

from models import db, Document, Fund, InvestmentPool, AuditLog, AuditAction

documents_bp = Blueprint("documents", __name__)

ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "csv",
    "txt", "rtf", "png", "jpg", "jpeg", "gif", "msg", "eml"
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _next_url(entity_type, entity_id):
    if entity_type == "fund":
        return url_for("funds.detail", fund_id=entity_id)
    return url_for("pools.detail", pool_id=entity_id)


@documents_bp.route("/upload/<entity_type>/<int:entity_id>", methods=["POST"])
@login_required
def upload(entity_type, entity_id):
    if not current_user.can_edit:
        abort(403)
    if entity_type not in ("fund", "pool"):
        abort(400)

    # Validate the entity exists
    if entity_type == "fund":
        Fund.query.get_or_404(entity_id)
    else:
        InvestmentPool.query.get_or_404(entity_id)

    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected.", "warning")
        return redirect(_next_url(entity_type, entity_id))

    if not _allowed(file.filename):
        flash(f"File type not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}", "danger")
        return redirect(_next_url(entity_type, entity_id))

    file_data = file.read()
    if len(file_data) > MAX_FILE_SIZE:
        flash("File is too large. Maximum size is 10 MB.", "danger")
        return redirect(_next_url(entity_type, entity_id))

    # Sanitise filename
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(file.filename)

    doc = Document(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=safe_name,
        description=request.form.get("description", "").strip() or None,
        mime_type=file.mimetype,
        file_size=len(file_data),
        file_data=file_data,
        uploaded_by_id=current_user.id,
    )
    db.session.add(doc)
    db.session.flush()
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=AuditAction.CREATE,
        entity_type="Document",
        entity_id=doc.id,
        description=f"Uploaded document '{safe_name}' to {entity_type} #{entity_id}",
        ip_address=request.remote_addr,
    ))
    db.session.commit()
    flash(f"'{safe_name}' uploaded successfully.", "success")
    return redirect(_next_url(entity_type, entity_id))


@documents_bp.route("/download/<int:doc_id>")
@login_required
def download(doc_id):
    doc = Document.query.get_or_404(doc_id)
    if doc.is_deleted:
        abort(404)
    return send_file(
        BytesIO(doc.file_data),
        download_name=doc.filename,
        as_attachment=True,
        mimetype=doc.mime_type or "application/octet-stream",
    )


@documents_bp.route("/view/<int:doc_id>")
@login_required
def view(doc_id):
    """Serve inline (for PDFs and images viewable in the browser)."""
    doc = Document.query.get_or_404(doc_id)
    if doc.is_deleted:
        abort(404)
    return send_file(
        BytesIO(doc.file_data),
        download_name=doc.filename,
        as_attachment=False,
        mimetype=doc.mime_type or "application/octet-stream",
    )


@documents_bp.route("/delete/<int:doc_id>", methods=["POST"])
@login_required
def delete(doc_id):
    if not current_user.can_approve:
        abort(403)
    doc = Document.query.get_or_404(doc_id)
    entity_type = doc.entity_type
    entity_id   = doc.entity_id
    doc.is_deleted = True
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=AuditAction.DELETE,
        entity_type="Document",
        entity_id=doc.id,
        description=f"Deleted document '{doc.filename}' from {entity_type} #{entity_id}",
        ip_address=request.remote_addr,
    ))
    db.session.commit()
    flash(f"'{doc.filename}' removed.", "warning")
    return redirect(_next_url(entity_type, entity_id))
