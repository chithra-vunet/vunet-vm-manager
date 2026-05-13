from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models.user import User
from app.decorators import role_required

users_bp = Blueprint("users", __name__)

ROLES = ["admin", "editor", "viewer"]


@users_bp.route("/users")
@login_required
@role_required("admin")
def index():
    return render_template("users.html", users=User.all_users(), roles=ROLES)


@users_bp.route("/users/invite", methods=["POST"])
@login_required
@role_required("admin")
def invite():
    email = request.form.get("email", "").strip().lower()
    role  = request.form.get("role", "viewer")

    if not email or role not in ROLES:
        flash("Valid email and role are required.", "danger")
        return redirect(url_for("users.index"))

    existing = User.find_by_email(email)
    if existing:
        flash(f"{email} already has access ({existing.role}).", "warning")
        return redirect(url_for("users.index"))

    User.invite(email, role, invited_by=current_user.display_name or current_user.username)

    # Send welcome email
    try:
        from app.notifications import send_welcome_email
        signin_url = url_for("auth.google_login", _external=True)
        send_welcome_email(email, role, signin_url)
        flash(f"Invitation sent to {email}.", "success")
    except Exception as exc:
        flash(f"User added but welcome email failed: {exc}", "warning")

    return redirect(url_for("users.index"))


@users_bp.route("/users/<user_id>/role", methods=["POST"])
@login_required
@role_required("admin")
def update_role(user_id):
    role = request.form.get("role", "")
    if role not in ROLES:
        flash("Invalid role.", "danger")
        return redirect(url_for("users.index"))
    if user_id == current_user.id:
        flash("You cannot change your own role.", "warning")
        return redirect(url_for("users.index"))
    User.update_role(user_id, role)
    flash("Role updated.", "success")
    return redirect(url_for("users.index"))


@users_bp.route("/users/<user_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(user_id):
    if user_id == current_user.id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("users.index"))
    User.delete(user_id)
    flash("User removed.", "success")
    return redirect(url_for("users.index"))
