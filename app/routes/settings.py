from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.decorators import role_required
from app.models.settings import get_settings, save_settings

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings", methods=["GET"])
@login_required
@role_required("admin")
def index():
    return render_template("settings.html", s=get_settings())


@settings_bp.route("/settings/save", methods=["POST"])
@login_required
@role_required("admin")
def save():
    f = request.form
    current  = get_settings()
    password = f.get("mail_password", "").strip()
    if not password:
        password = current.get("mail_password", "")

    save_settings({
        "mail_username":  f.get("mail_username", "").strip().lower(),
        "mail_password":  password,
        "admin_email":    f.get("admin_email", "").strip().lower(),
        "alert_days":     max(1, int(f.get("alert_days") or 2)),
        "alerts_enabled": f.get("alerts_enabled") == "1",
    })
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/settings/test-email", methods=["POST"])
@login_required
@role_required("admin")
def test_email():
    from flask import current_app
    from app.notifications import send_expiry_alerts
    try:
        send_expiry_alerts(current_app._get_current_object())
        flash(
            "Test run complete. If VMs are expiring within the alert window and "
            "email is configured, alerts have been sent.",
            "success",
        )
    except Exception as exc:
        flash(f"Alert failed: {exc}", "danger")
    return redirect(url_for("settings.index"))
