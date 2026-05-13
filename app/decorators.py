from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user


def role_required(*roles):
    """Restrict a route to users whose role is in `roles`. Redirects with a flash on failure."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if current_user.role not in roles:
                flash("You don't have permission to perform this action.", "danger")
                return redirect(url_for("dashboard.index"))
            return f(*args, **kwargs)
        return decorated
    return decorator
