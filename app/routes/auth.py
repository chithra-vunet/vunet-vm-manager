from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.find_by_username(username)
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@auth_bp.route("/auth/google")
def google_login():
    import app as _app_module
    redirect_uri = url_for("auth.google_callback", _external=True)
    return _app_module.oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
def google_callback():
    import app as _app_module
    try:
        token    = _app_module.oauth.google.authorize_access_token()
        userinfo = token.get("userinfo", {})
        email    = (userinfo.get("email") or "").strip().lower()
        google_id = userinfo.get("sub", "")
        name      = userinfo.get("name", "")
    except Exception as exc:
        flash(f"Google sign-in failed: {exc}", "danger")
        return redirect(url_for("auth.login"))

    if not email:
        flash("Could not retrieve your email from Google. Try again.", "danger")
        return redirect(url_for("auth.login"))

    if not email.endswith("@vunetsystems.com"):
        flash(
            "Only @vunetsystems.com accounts are allowed to access VM Manager.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    user = User.find_by_email(email)
    if not user:
        flash(
            "Your Google account is not authorised to access VM Manager. "
            "Ask your IT administrator to invite you.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    User.activate_google(email, google_id, name)
    user = User.find_by_email(email)
    login_user(user, remember=True)
    flash(f"Welcome, {user.display_name}!", "success")
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
