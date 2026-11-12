"""Account settings: forgot / reset password, change password, delete account."""
import os
import threading
import time

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from .auth import (EMAIL_RE, clear_failed_logins, external_url, has_password, login_required,
                   password_fingerprint, start_session, verify_password)
from .db import get_db, query, upload_path
from .mailer import send_email

bp = Blueprint("account", __name__)

RESET_MAX_AGE = 60 * 60          # reset links work for 1 hour
MIN_PASSWORD = 8

# ---- limit reset emails: 1 per 2 minutes per address, 20 per hour per visitor ----
_sent = {}
_sent_lock = threading.Lock()


def _allowed_to_send(email, ip):
    now = time.time()
    with _sent_lock:
        for key in list(_sent):
            _sent[key] = [t for t in _sent[key] if t > now - 3600]
            if not _sent[key]:
                del _sent[key]
        if any(t > now - 120 for t in _sent.get(("email", email), [])):
            return False
        if len(_sent.get(("ip", ip), [])) >= 20:
            return False
        _sent.setdefault(("email", email), []).append(now)
        _sent.setdefault(("ip", ip), []).append(now)
        return True


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="qualifi-password-reset")


def _make_token(user):
    # The token includes a fingerprint of the current password, so it stops working
    # as soon as the password changes: each link can be used only once.
    return _serializer().dumps({"u": user["id"], "p": password_fingerprint(user["password_hash"])})


def _user_from_token(token):
    try:
        data = _serializer().loads(token, max_age=RESET_MAX_AGE)
    except SignatureExpired:
        return None, "This link has expired. Ask for a new one below."
    except BadSignature:
        return None, "This link isn’t valid. Ask for a new one below."
    user = query("SELECT * FROM users WHERE id = ?", (data.get("u"),), one=True)
    if user is None or password_fingerprint(user["password_hash"]) != data.get("p"):
        return None, "This link was already used. Ask for a new one below."
    return user, None


def _password_problem(password, confirm):
    if len(password) < MIN_PASSWORD:
        return f"Your password needs at least {MIN_PASSWORD} characters."
    if len(password) > 200:
        return "That password is too long."
    if password != confirm:
        return "The two passwords don’t match."
    return None


# ---------------------------------------------------------------- forgot / reset password
@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if g.user:
        return redirect(url_for("account.settings"))
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not EMAIL_RE.match(email):
            flash("Please enter a valid email.", "error")
            return render_template("auth/forgot.html", email=email, sent=False)
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user is not None and _allowed_to_send(email, request.remote_addr):
            link = external_url("account.reset_password", token=_make_token(user))
            send_email(user["email"], "Reset your Qualifi password",
                       f"Hi {user['name']},\n\n"
                       f"Someone (hopefully you) asked to reset the password for your Qualifi account.\n\n"
                       f"Choose a new password here (the link works once, for 1 hour):\n{link}\n\n"
                       f"If you didn’t ask for this, you can ignore this email. Your password stays the same.\n\n"
                       f"Qualifi")
        # Same answer whether or not the account exists, so emails can't be probed.
        return render_template("auth/forgot.html", email=email, sent=True)
    return render_template("auth/forgot.html", email=email, sent=False)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user, problem = _user_from_token(token)
    if problem:
        flash(problem, "error")
        return redirect(url_for("account.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        error = _password_problem(password, request.form.get("confirm", ""))
        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), user["id"]))
            db.commit()
            clear_failed_logins(user["email"])
            session.clear()          # every other device is logged out (password fingerprint changed)
            flash("Your password was changed. Log in with your new password.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", token=token, email=user["email"])


# ---------------------------------------------------------------- account settings
@bp.route("/account")
@login_required()
def settings():
    from .oauth import LABELS, PROVIDERS
    linked = {r["provider"]: r for r in query("SELECT * FROM user_identities WHERE user_id = ?", (g.user["id"],))}
    # show every provider that is switched on, plus any already linked one
    methods = [{"key": k, "label": LABELS[k], "linked": linked.get(k), "enabled": PROVIDERS[k].configured()}
               for k in LABELS if PROVIDERS[k].configured() or k in linked]
    return render_template("account/settings.html", methods=methods, has_password=has_password(g.user),
                           can_disconnect=has_password(g.user) or len(linked) > 1)


@bp.route("/account/password", methods=["POST"])
@login_required()
def change_password():
    if has_password(g.user) and not verify_password(g.user, request.form.get("current", "")):
        flash("Your current password isn’t right.", "error")
        return redirect(url_for("account.settings"))
    password = request.form.get("password", "")
    error = _password_problem(password, request.form.get("confirm", ""))
    if error:
        flash(error, "error")
        return redirect(url_for("account.settings"))
    new_hash = generate_password_hash(password)
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, g.user["id"]))
    db.commit()
    had_password = has_password(g.user)
    start_session(g.user["id"], new_hash)   # stay logged in here; other devices are logged out
    flash("Your password was changed. Other devices were logged out." if had_password
          else "Your password is set. You can now also log in with your email and password.", "success")
    return redirect(url_for("account.settings"))


@bp.route("/account/delete", methods=["POST"])
@login_required()
def delete_account():
    if has_password(g.user):
        confirmed = verify_password(g.user, request.form.get("password", ""))
        problem = "That password isn’t right, so your account was not deleted."
    else:   # signed up with Google/Apple/GitHub and never set a password
        confirmed = request.form.get("confirm_text", "").strip().upper() == "DELETE"
        problem = "Type DELETE to confirm. Your account was not deleted."
    if not confirmed:
        flash(problem, "error")
        return redirect(url_for("account.settings"))
    delete_user(g.user["id"])
    session.clear()
    flash("Your account and all its data were deleted.", "success")
    return redirect(url_for("auth.login"))


def delete_user(uid):
    """Remove a user, everything linked to them, and their uploaded files, in one transaction."""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        return
    files = []
    if user["role"] == "candidate":
        prof = db.execute("SELECT cv_path FROM candidate_profiles WHERE user_id = ?", (uid,)).fetchone()
        if prof and prof["cv_path"]:
            files.append(prof["cv_path"])
        db.execute("DELETE FROM applications WHERE candidate_id = ?", (uid,))
    else:
        company = db.execute("SELECT company_name FROM companies WHERE user_id = ?", (uid,)).fetchone()
        company_name = company["company_name"] if company else user["name"]
        files += [r["path"] for r in db.execute(
            "SELECT d.path FROM job_documents d JOIN jobs j ON j.id = d.job_id WHERE j.company_id = ?", (uid,))]
        # tell candidates their applications are gone
        for r in db.execute("SELECT a.candidate_id, j.title FROM applications a JOIN jobs j ON j.id = a.job_id "
                            "WHERE j.company_id = ?", (uid,)).fetchall():
            db.execute("INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
                       (r["candidate_id"], f"{company_name} closed its Qualifi account, so your application for "
                                           f"{r['title']} was removed.", ""))
        db.execute("DELETE FROM applications WHERE job_id IN (SELECT id FROM jobs WHERE company_id = ?)", (uid,))
    db.execute("DELETE FROM users WHERE id = ?", (uid,))   # profile, jobs, tests, notifications cascade
    db.commit()
    for stored in files:
        path = upload_path(stored)
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            current_app.logger.warning("Could not remove file %s", path)
