from functools import wraps

from flask import abort, jsonify, redirect, request, url_for
from flask_login import current_user


def home_for(user):
    if user.role == "admin":
        return url_for("admin.dashboard")
    if user.role == "rider":
        return url_for("rider.dashboard")
    return url_for("shop.home")


def roles_required(*roles):
    """Page routes: send anonymous users to sign in, show 403 to the wrong role."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.path))
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def api_roles(*roles):
    """JSON routes: answer 401/403 as JSON instead of redirecting."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({"error": "Please sign in."}), 401
            if current_user.role not in roles:
                return jsonify({"error": "You do not have access to this."}), 403
            return view(*args, **kwargs)
        return wrapper
    return decorator
