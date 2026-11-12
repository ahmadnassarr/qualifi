"""Qualifi: a recruitment platform with skill-based application screening."""
import logging
import os
import secrets
from datetime import datetime
from logging.handlers import RotatingFileHandler

from flask import Flask, abort, g, redirect, request, session, url_for

from . import db as dbmod
from .auth import password_fingerprint

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; object-src 'none'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

FIELDS = [
    "Tech", "Nursing & Healthcare", "Accounting & Finance", "Design", "Marketing & Sales",
    "Engineering", "Education", "Customer Service", "Human Resources", "Hospitality", "Legal", "Other",
]
LEVELS = {"fresh": "Fresh graduate", "junior": "Junior", "senior": "Senior"}
EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Internship", "Contract", "Remote"]


def _load_dotenv(path):
    """Tiny .env reader so the app needs no extra package."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def create_app(test_config=None):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _load_dotenv(os.path.join(base_dir, ".env"))

    app = Flask(__name__, instance_path=os.environ.get("QUALIFI_DATA_DIR") or os.path.join(base_dir, "instance"))
    os.makedirs(app.instance_path, exist_ok=True)
    https = os.environ.get("QUALIFI_HTTPS") == "1"
    app.config.update(
        SECRET_KEY=os.environ.get("QUALIFI_SECRET_KEY") or _persistent_secret(app.instance_path),
        DATABASE=os.path.join(app.instance_path, "qualifi.sqlite"),
        UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
        MAX_CONTENT_LENGTH=15 * 1024 * 1024,           # 15 MB per request
        RETAKE_DAYS=int(os.environ.get("QUALIFI_RETAKE_DAYS", 14)),
        QUESTIONS_TO_GENERATE=int(os.environ.get("QUALIFI_QUESTIONS_TO_GENERATE", 40)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=https,                  # cookies only over HTTPS once the site is online
        PREFERRED_URL_SCHEME="https" if https else "http",
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Behind a hosting proxy (Render, Railway, Nginx...), trust its X-Forwarded-* headers
    # so the real visitor address and https are seen. Set QUALIFI_BEHIND_PROXY=1 there.
    if os.environ.get("QUALIFI_BEHIND_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _setup_logging(app)
    app.teardown_appcontext(dbmod.close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """Create the database tables."""
        dbmod.init_db()
        print("Database ready at", app.config["DATABASE"])

    # ---- auth state + CSRF for every request ----
    @app.before_request
    def load_user_and_check_csrf():
        uid = session.get("user_id")
        g.user = dbmod.query("SELECT * FROM users WHERE id = ?", (uid,), one=True) if uid else None
        if uid and g.user is None:          # account no longer exists
            session.clear()
        elif g.user is not None and session.get("pwv") != password_fingerprint(g.user["password_hash"]):
            g.user = None                    # password changed on another device: log this one out
            session.clear()
        # Apple's sign-in posts back from appleid.apple.com, so it can't carry our token. That view only
        # bounces to a GET of itself, where the signed state + browser nonce are checked instead.
        if request.method == "POST" and request.endpoint != "oauth.callback" and not app.config.get("TESTING_SKIP_CSRF"):
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not token or token != session.get("csrf_token"):
                abort(400, "Your session expired. Please go back and try again.")

    @app.after_request
    def ensure_csrf_token(response):
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        # security headers
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if response.mimetype == "text/html":
            response.headers.setdefault("Content-Security-Policy", CSP)
            if g.get("user") is not None:   # pages with personal data: don't keep them in shared caches
                response.headers.setdefault("Cache-Control", "no-store")
        if https:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.context_processor
    def inject_globals():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        unread = 0
        if g.get("user") is not None:
            row = dbmod.query("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0",
                              (g.user["id"],), one=True)
            unread = row["n"]
        return {
            "csrf_token": session["csrf_token"],
            "LEVELS": LEVELS,
            "FIELDS": FIELDS,
            "EMPLOYMENT_TYPES": EMPLOYMENT_TYPES,
            "unread_count": unread,
        }

    @app.template_filter("date")
    def format_date(value):
        if not value:
            return ""
        try:
            return datetime.fromisoformat(str(value)).strftime("%d %b %Y")
        except ValueError:
            return str(value)

    @app.template_filter("initials")
    def initials(name):
        parts = [p for p in (name or "").split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    from . import account, auth, candidate, company, oauth
    app.register_blueprint(auth.bp)
    app.register_blueprint(account.bp)
    app.register_blueprint(oauth.bp)
    app.register_blueprint(candidate.bp)
    app.register_blueprint(company.bp)

    @app.route("/")
    def home():
        if g.user is None:
            return redirect(url_for("auth.login"))
        if g.user["role"] == "company":
            return redirect(url_for("company.dashboard"))
        return redirect(url_for("candidate.jobs"))

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(err):
        from flask import render_template
        code = getattr(err, "code", 500)
        messages = {
            400: getattr(err, "description", "Bad request."),
            403: "You don’t have access to this page.",
            404: "This page doesn’t exist.",
            413: "That file is too big. The limit is 15 MB.",
        }
        return render_template("error.html", code=code, message=messages.get(code, "Something went wrong.")), code

    @app.errorhandler(500)
    def server_error(err):
        from flask import render_template
        app.logger.exception("Server error on %s %s", request.method, request.path)
        return render_template("error.html", code=500,
                               message="Something went wrong on our side. Please try again in a moment."), 500

    with app.app_context():
        dbmod.init_db()   # safe to run every start: CREATE TABLE IF NOT EXISTS

    return app


def _setup_logging(app):
    """Errors go to instance/logs/qualifi.log (rotated) as well as the console."""
    if app.testing or app.config.get("TESTING"):
        return
    log_dir = os.path.join(app.instance_path, "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(os.path.join(log_dir, "qualifi.log"), maxBytes=1_000_000, backupCount=5,
                                  encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    app.logger.addHandler(handler)


def _persistent_secret(instance_path):
    path = os.path.join(instance_path, "secret_key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key
