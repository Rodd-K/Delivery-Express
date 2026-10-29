import time

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .access import home_for
from .extensions import db
from .models import User
from .utils import normalize_phone, safe_next, valid_email

bp = Blueprint("auth", __name__)

# Small in-memory brake on password guessing: 5 failures per 10 minutes per IP + email.
# Fine for one server process; use Flask-Limiter + Redis when you scale.
_failed = {}
_WINDOW = 600
_MAX_FAILS = 5
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _key(email):
    return f"{request.remote_addr}|{email}"


def _too_many(key):
    now = time.time()
    recent = [t for t in _failed.get(key, []) if now - t < _WINDOW]
    _failed[key] = recent
    return len(recent) >= _MAX_FAILS


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    next_url = safe_next(request.values.get("next"), "")
    error = None
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        key = _key(email)
        if _too_many(key):
            error = "Too many attempts. Try again in 10 minutes."
        else:
            user = User.query.filter_by(email=email).first()
            if user:
                ok = user.check_password(password)
            else:
                check_password_hash(_DUMMY_HASH, password)  # keep timing similar
                ok = False
            if not ok:
                _failed.setdefault(key, []).append(time.time())
                error = "Email or password is not correct."
            elif not user.active:
                error = "This account has been deactivated. Contact support."
            elif user.role == "rider" and not user.approved:
                error = "Your rider account is waiting for admin approval."
            else:
                _failed.pop(key, None)
                login_user(user)
                return redirect(next_url or home_for(user))
    return render_template("login.html", error=error, email=email, next_url=next_url)


def _signup(role, template):
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    values = {k: (request.form.get(k) or "").strip() for k in ("name", "email", "phone")}
    values["email"] = values["email"].lower()
    errors = []
    if request.method == "POST":
        password = request.form.get("password") or ""
        if not 2 <= len(values["name"]) <= 80:
            errors.append("Enter your full name.")
        if not valid_email(values["email"]):
            errors.append("Enter a valid email address.")
        phone = normalize_phone(values["phone"])
        if not phone:
            errors.append("Enter a valid Kenyan phone number, like 0712 345 678.")
        if not 8 <= len(password) <= 128:
            errors.append("Choose a password of at least 8 characters.")
        elif password != (request.form.get("password2") or ""):
            errors.append("The two passwords do not match.")
        if not errors and User.query.filter_by(email=values["email"]).first():
            errors.append("An account with this email already exists. Try signing in.")
        if not errors:
            user = User(name=values["name"], email=values["email"], phone=phone, role=role,
                        approved=(role != "rider"))
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            if role == "rider":
                flash("Thanks! Your rider account was created. An admin must approve it before you can sign in.", "info")
                return redirect(url_for("auth.login"))
            login_user(user)
            flash("Welcome to Express Mtaani!", "success")
            return redirect(safe_next(request.values.get("next"), url_for("shop.home")))
        return render_template(template, values=values, errors=errors), 400
    return render_template(template, values=values, errors=errors)


@bp.route("/register", methods=["GET", "POST"])
def register():
    return _signup("customer", "register.html")


@bp.route("/rider/register", methods=["GET", "POST"])
def rider_register():
    return _signup("rider", "rider_register.html")


@bp.post("/logout")
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("shop.home"))
