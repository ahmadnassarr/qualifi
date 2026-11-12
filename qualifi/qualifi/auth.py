"""Register, log in, log out, and role-based access decorators."""
import functools
import hashlib
import os
import re
import secrets
import threading
import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, query

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---- brute-force protection: 5 wrong passwords for one email from one address = 15-minute lock ----
MAX_FAILED_LOGINS = 5
LOCK_SECONDS = 15 * 60
_failed = {}                 # (ip, email) -> list of failure timestamps
_failed_lock = threading.Lock()


def _recent_failures(key):
    cutoff = time.time() - LOCK_SECONDS
    with _failed_lock:
        stamps = [t for t in _failed.get(key, []) if t > cutoff]
        if stamps:
            _failed[key] = stamps
        else:
            _failed.pop(key, None)
        return stamps


def _record_failure(key):
    with _failed_lock:
        _failed.setdefault(key, []).append(time.time())
        if len(_failed) > 10000:  # keep memory bounded
            _failed.clear()


def clear_failed_logins(email):
    """After a password reset the owner can log in straight away."""
    with _failed_lock:
        for key in [k for k in _failed if k[1] == email]:
            del _failed[key]


def password_fingerprint(password_hash):
    """Short digest of the stored hash. Kept in the session: when the password changes,
    sessions on other devices no longer match and are logged out."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:20]


def new_unusable_password():
    """Accounts made with Google/Apple/GitHub have no password until the person sets one.
    The random value keeps the session fingerprint unique; '!' marks it as unusable."""
    return "!" + secrets.token_hex(24)


def has_password(user):
    return bool(user["password_hash"]) and not user["password_hash"].startswith("!")


def verify_password(user, password):
    return has_password(user) and check_password_hash(user["password_hash"], password or "")


def external_url(endpoint, **values):
    """Absolute link for emails and sign-in redirects. Uses QUALIFI_BASE_URL when set, so a forged
    Host header can never put someone else's address into a link."""
    base = os.environ.get("QUALIFI_BASE_URL", "").rstrip("/")
    if base:
        return base + url_for(endpoint, **values)
    return url_for(endpoint, _external=True, **values)


def start_session(user_id, password_hash):
    session.clear()
    session["user_id"] = user_id
    session["pwv"] = password_fingerprint(password_hash)
    session["csrf_token"] = secrets.token_urlsafe(32)


def login_required(role=None):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if role and g.user["role"] != role:
                flash("That page is for " + ("companies." if role == "company" else "candidates."), "error")
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("home"))
    role = request.values.get("role", "candidate")
    form = {"name": "", "email": "", "company_name": ""}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "email", "company_name")}
        password = request.form.get("password", "")
        email = form["email"].lower()
        error = None
        if role not in ("candidate", "company"):
            error = "Choose candidate or company."
        elif not form["name"]:
            error = "Please enter your name."
        elif role == "company" and not form["company_name"]:
            error = "Please enter your company name."
        elif not EMAIL_RE.match(email):
            error = "Please enter a valid email."
        elif len(form["name"]) > 120 or len(form["company_name"]) > 160 or len(email) > 254:
            error = "That name or email is too long."
        elif len(password) < 8:
            error = "Your password needs at least 8 characters."
        elif query("SELECT id FROM users WHERE email = ?", (email,), one=True):
            error = "An account with this email already exists."
        if error:
            flash(error, "error")
        else:
            password_hash = generate_password_hash(password)
            uid = execute("INSERT INTO users (email, password_hash, role, name) VALUES (?, ?, ?, ?)",
                          (email, password_hash, role, form["name"]))
            if role == "company":
                execute("INSERT INTO companies (user_id, company_name) VALUES (?, ?)", (uid, form["company_name"]))
            else:
                execute("INSERT INTO candidate_profiles (user_id) VALUES (?)", (uid,))
            start_session(uid, password_hash)
            if role == "company":
                return redirect(url_for("company.dashboard"))
            return redirect(url_for("candidate.upload_cv"))
    return render_template("auth/register.html", role=role, form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("home"))
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        key = (request.remote_addr, email)
        failures = _recent_failures(key)
        if len(failures) >= MAX_FAILED_LOGINS:
            minutes = max(1, int((failures[0] + LOCK_SECONDS - time.time()) // 60) + 1)
            flash(f"Too many wrong passwords. Please try again in {minutes} minute{'s' if minutes != 1 else ''}.", "error")
            return render_template("auth/login.html", email=email), 429
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user is not None and not has_password(user):
            providers = [r["provider"] for r in query("SELECT provider FROM user_identities WHERE user_id = ?",
                                                      (user["id"],))]
            names = " or ".join({"google": "Google", "apple": "Apple", "github": "GitHub"}[p] for p in providers)
            _record_failure(key)
            flash(f"This account signs in with {names or 'a linked account'}. Use the button below, "
                  f"or choose “Forgot password?” to set a password.", "error")
        elif user is None or not verify_password(user, request.form.get("password", "")):
            _record_failure(key)
            flash("Wrong email or password.", "error")
        else:
            with _failed_lock:
                _failed.pop(key, None)
            start_session(user["id"], user["password_hash"])
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("home"))
    return render_template("auth/login.html", email=email)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
