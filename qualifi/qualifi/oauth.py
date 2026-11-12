"""Sign in with Google, Apple or GitHub (OAuth 2.0 / OpenID Connect).

A provider shows up on the login and register pages only when its keys are set (see .env.example).
New people finish sign-up on /auth/finish (candidate or company, name, company name); candidates
then upload their CV exactly like after a normal registration.

Safety:
- `state` is signed, expires after 10 minutes and is tied to this browser by a nonce cookie.
- ID tokens come straight from the provider's token endpoint over TLS, and issuer, audience,
  expiry and nonce are all checked.
- An existing account is linked by email only when the provider says the email is verified.
"""
import base64
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import (Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, request,
                   session, url_for)
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .auth import EMAIL_RE, external_url, has_password, new_unusable_password, start_session
from .db import get_db, query

bp = Blueprint("oauth", __name__)

STATE_MAX_AGE = 10 * 60
SIGNUP_MAX_AGE = 15 * 60
NONCE_COOKIE = "qualifi_oauth"
LABELS = {"google": "Google", "apple": "Apple", "github": "GitHub"}


class OAuthError(Exception):
    """Shown to the user as-is."""


# ---------------------------------------------------------------- HTTP + JWT helpers
def _http_json(url, data=None, headers=None):
    """GET (or POST form `data`) and return parsed JSON. Tests replace this function."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    hdrs = {"Accept": "application/json", "User-Agent": "Qualifi"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"{url} answered {e.code}: {detail}") from e


def _jwt_claims(token):
    """Payload of a JWT. Only used on tokens received directly from the provider's token
    endpoint over TLS (OpenID Connect Core 3.1.3.7 allows TLS instead of the signature check)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception as e:
        raise RuntimeError("Malformed ID token") from e


def _check_id_token(claims, issuers, audience, nonce):
    if claims.get("iss") not in issuers:
        raise RuntimeError(f"Unexpected issuer {claims.get('iss')}")
    aud = claims.get("aud")
    if audience not in (aud if isinstance(aud, list) else [aud]):
        raise RuntimeError("ID token is for another app")
    if float(claims.get("exp", 0)) < time.time() - 60:
        raise RuntimeError("ID token expired")
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise RuntimeError("Nonce missing or wrong")
    if not claims.get("sub"):
        raise RuntimeError("ID token has no subject")


def _truthy(value):
    return value is True or str(value).lower() == "true"


# ---------------------------------------------------------------- providers
class Google:
    name = "google"

    @staticmethod
    def configured():
        return bool(os.environ.get("QUALIFI_GOOGLE_CLIENT_ID") and os.environ.get("QUALIFI_GOOGLE_CLIENT_SECRET"))

    @staticmethod
    def authorize_url(state, nonce, redirect_uri):
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": os.environ["QUALIFI_GOOGLE_CLIENT_ID"], "redirect_uri": redirect_uri,
            "response_type": "code", "scope": "openid email profile", "state": state, "nonce": nonce,
            "prompt": "select_account"})

    @staticmethod
    def identity(code, redirect_uri, nonce, extra):
        client_id = os.environ["QUALIFI_GOOGLE_CLIENT_ID"]
        tok = _http_json("https://oauth2.googleapis.com/token", {
            "code": code, "client_id": client_id, "client_secret": os.environ["QUALIFI_GOOGLE_CLIENT_SECRET"],
            "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        if "id_token" not in tok:
            raise RuntimeError(f"Google token error: {tok.get('error')}")
        c = _jwt_claims(tok["id_token"])
        _check_id_token(c, ("https://accounts.google.com", "accounts.google.com"), client_id, nonce)
        return {"subject": c["sub"], "email": c.get("email", ""), "email_verified": _truthy(c.get("email_verified")),
                "name": c.get("name") or " ".join(p for p in (c.get("given_name"), c.get("family_name")) if p)}


class GitHub:
    name = "github"

    @staticmethod
    def configured():
        return bool(os.environ.get("QUALIFI_GITHUB_CLIENT_ID") and os.environ.get("QUALIFI_GITHUB_CLIENT_SECRET"))

    @staticmethod
    def authorize_url(state, nonce, redirect_uri):
        return "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode({
            "client_id": os.environ["QUALIFI_GITHUB_CLIENT_ID"], "redirect_uri": redirect_uri,
            "scope": "read:user user:email", "state": state, "allow_signup": "true"})

    @staticmethod
    def identity(code, redirect_uri, nonce, extra):
        tok = _http_json("https://github.com/login/oauth/access_token", {
            "client_id": os.environ["QUALIFI_GITHUB_CLIENT_ID"],
            "client_secret": os.environ["QUALIFI_GITHUB_CLIENT_SECRET"], "code": code, "redirect_uri": redirect_uri})
        if not tok.get("access_token"):
            raise RuntimeError(f"GitHub token error: {tok.get('error')}")
        auth = {"Authorization": "Bearer " + tok["access_token"], "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}
        user = _http_json("https://api.github.com/user", headers=auth)
        emails = _http_json("https://api.github.com/user/emails", headers=auth)
        verified = [e for e in emails if isinstance(e, dict) and e.get("verified")]
        best = next((e for e in verified if e.get("primary")), verified[0] if verified else None)
        return {"subject": str(user["id"]), "email": best["email"] if best else "", "email_verified": bool(best),
                "name": user.get("name") or user.get("login") or ""}


class Apple:
    name = "apple"

    @staticmethod
    def _key():
        key = os.environ.get("QUALIFI_APPLE_PRIVATE_KEY", "").replace("\\n", "\n").strip()
        path = os.environ.get("QUALIFI_APPLE_PRIVATE_KEY_FILE", "")
        if not key and path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                key = f.read().strip()
        return key

    @classmethod
    def configured(cls):
        return all(os.environ.get(k) for k in ("QUALIFI_APPLE_CLIENT_ID", "QUALIFI_APPLE_TEAM_ID",
                                               "QUALIFI_APPLE_KEY_ID")) and bool(cls._key())

    @staticmethod
    def authorize_url(state, nonce, redirect_uri):
        # Apple POSTs the result back (form_post) when name/email are requested.
        return "https://appleid.apple.com/auth/authorize?" + urllib.parse.urlencode({
            "client_id": os.environ["QUALIFI_APPLE_CLIENT_ID"], "redirect_uri": redirect_uri,
            "response_type": "code", "response_mode": "form_post", "scope": "name email",
            "state": state, "nonce": nonce}, quote_via=urllib.parse.quote)

    @classmethod
    def client_secret(cls):
        import jwt  # PyJWT + cryptography, only needed for Apple
        now = int(time.time())
        return jwt.encode({"iss": os.environ["QUALIFI_APPLE_TEAM_ID"], "iat": now, "exp": now + 600,
                           "aud": "https://appleid.apple.com", "sub": os.environ["QUALIFI_APPLE_CLIENT_ID"]},
                          cls._key(), algorithm="ES256", headers={"kid": os.environ["QUALIFI_APPLE_KEY_ID"]})

    @classmethod
    def identity(cls, code, redirect_uri, nonce, extra):
        client_id = os.environ["QUALIFI_APPLE_CLIENT_ID"]
        tok = _http_json("https://appleid.apple.com/auth/token", {
            "client_id": client_id, "client_secret": cls.client_secret(), "code": code,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri})
        if "id_token" not in tok:
            raise RuntimeError(f"Apple token error: {tok.get('error')}")
        c = _jwt_claims(tok["id_token"])
        _check_id_token(c, ("https://appleid.apple.com",), client_id, nonce)
        name = ""
        try:   # Apple sends the name only the very first time, as a JSON form field
            n = json.loads(extra.get("user") or "{}").get("name") or {}
            name = " ".join(p for p in (n.get("firstName"), n.get("lastName")) if p)
        except (ValueError, AttributeError):
            pass
        return {"subject": c["sub"], "email": c.get("email", ""), "email_verified": _truthy(c.get("email_verified")),
                "name": name}


PROVIDERS = {p.name: p for p in (Google, Apple, GitHub)}


def enabled_providers():
    return [(name, LABELS[name]) for name, p in PROVIDERS.items() if p.configured()]


@bp.app_context_processor
def inject_providers():
    # All three buttons are always shown; one whose keys aren't set yet explains that when clicked.
    return {"oauth_providers": list(LABELS.items())}


def _provider_or_404(provider):
    p = PROVIDERS.get(provider)
    if p is None or not p.configured():
        abort(404)
    return p


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="qualifi-oauth-state")


def _begin(provider, mode, role=None):
    p = _provider_or_404(provider)
    nonce = secrets.token_urlsafe(24)
    state = _serializer().dumps({"p": provider, "m": mode, "r": role, "n": nonce,
                                 "u": g.user["id"] if mode == "link" else None})
    resp = redirect(p.authorize_url(state, nonce, external_url("oauth.callback", provider=provider)))
    resp.set_cookie(NONCE_COOKIE, nonce, max_age=STATE_MAX_AGE, httponly=True, samesite="Lax",
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", False), path="/auth")
    return resp


# ---------------------------------------------------------------- routes
@bp.route("/auth/<provider>/start")
def start(provider):
    if g.user:
        return redirect(url_for("home"))
    if provider not in LABELS:
        abort(404)
    role = request.args.get("role")
    role = role if role in ("candidate", "company") else None
    if not PROVIDERS[provider].configured():
        current_app.logger.warning("%s sign-in clicked but its keys are not set in .env", LABELS[provider])
        flash(f"Signing in with {LABELS[provider]} isn’t available yet. Please use your email and password for now.",
              "info")
        return redirect(url_for("auth.register", role=role) if role else url_for("auth.login"))
    return _begin(provider, "login", role)


@bp.route("/auth/<provider>/connect", methods=["POST"])
def connect(provider):
    if g.user is None:
        return redirect(url_for("auth.login"))
    return _begin(provider, "link")


@bp.route("/auth/<provider>/callback", methods=["GET", "POST"])
def callback(provider):
    p = _provider_or_404(provider)
    if request.method == "POST":
        # Apple posts here from appleid.apple.com. That cross-site POST carries no cookies, so
        # bounce it to a same-site GET of this URL, where the session and nonce cookies are sent.
        params = {k: v for k, v in request.form.items() if k in ("code", "state", "user", "error")}
        target = url_for("oauth.callback", provider=provider, **params)
        resp = make_response(render_template("auth/oauth_continue.html", target=target))
        resp.headers["Refresh"] = f"0;url={target}"
        return resp

    label = LABELS[provider]
    try:
        data = _serializer().loads(request.args.get("state", ""), max_age=STATE_MAX_AGE)
    except BadSignature:
        data = None
    cookie_nonce = request.cookies.get(NONCE_COOKIE)
    back = url_for("account.settings") if (data and data.get("m") == "link") else url_for("auth.login")

    def fail(message):
        resp = redirect(back)
        resp.delete_cookie(NONCE_COOKIE, path="/auth")
        flash(message, "error")
        return resp

    if not data or data.get("p") != provider or not cookie_nonce or not secrets.compare_digest(cookie_nonce, data["n"]):
        return fail(f"That {label} sign-in expired or didn’t come from this browser. Please try again.")
    if request.args.get("error"):
        return fail(f"{label} sign-in was cancelled.")
    if not request.args.get("code"):
        return fail(f"{label} didn’t send a sign-in code. Please try again.")
    try:
        ident = p.identity(request.args["code"], external_url("oauth.callback", provider=provider), data["n"],
                           request.args)
        ident["email"] = (ident.get("email") or "").strip().lower()
        if ident["email"] and not EMAIL_RE.match(ident["email"]):
            ident["email"], ident["email_verified"] = "", False
    except Exception:
        current_app.logger.exception("%s sign-in failed", label)
        return fail(f"We couldn’t sign you in with {label}. Please try again.")

    try:
        if data["m"] == "link":
            resp = _link(provider, ident, data.get("u"))
        else:
            resp = _login_or_signup(provider, ident, data.get("r"))
    except OAuthError as e:
        return fail(str(e))
    resp.delete_cookie(NONCE_COOKIE, path="/auth")
    return resp


def _identity_owner(provider, subject):
    return query("SELECT u.* FROM user_identities i JOIN users u ON u.id = i.user_id "
                 "WHERE i.provider = ? AND i.subject = ?", (provider, subject), one=True)


def _add_identity(user_id, provider, ident):
    db = get_db()
    db.execute("INSERT INTO user_identities (user_id, provider, subject, email) VALUES (?, ?, ?, ?)",
               (user_id, provider, ident["subject"], ident["email"]))
    db.commit()


def _home_for(user):
    return url_for("company.dashboard") if user["role"] == "company" else url_for("home")


def _login_or_signup(provider, ident, role):
    label = LABELS[provider]
    user = _identity_owner(provider, ident["subject"])
    if user is not None:
        start_session(user["id"], user["password_hash"])
        return redirect(_home_for(user))
    if not ident["email"] or not ident["email_verified"]:
        raise OAuthError(f"{label} didn’t share a verified email address, which Qualifi needs for your account. "
                         f"Verify your email with {label}, or register with email and password.")
    existing = query("SELECT * FROM users WHERE email = ?", (ident["email"],), one=True)
    if existing is not None:
        if query("SELECT 1 FROM user_identities WHERE user_id = ? AND provider = ?",
                 (existing["id"], provider), one=True):
            raise OAuthError(f"Your Qualifi account is connected to a different {label} account. "
                             f"Log in with that one, or with your password.")
        # The provider verified this email, so it is the same person: connect and log in.
        _add_identity(existing["id"], provider, ident)
        start_session(existing["id"], existing["password_hash"])
        flash(f"{label} is now connected to your Qualifi account. Next time just click “Continue with {label}”.",
              "success")
        return redirect(_home_for(existing))
    session["oauth_signup"] = {"provider": provider, "subject": ident["subject"], "email": ident["email"],
                               "name": (ident.get("name") or "").strip()[:120], "role": role,
                               "expires": time.time() + SIGNUP_MAX_AGE}
    return redirect(url_for("oauth.finish", role=role) if role else url_for("oauth.finish"))


def _link(provider, ident, user_id):
    label = LABELS[provider]
    if g.user is None or g.user["id"] != user_id:
        raise OAuthError("Please log in again, then connect your account from the Account page.")
    owner = _identity_owner(provider, ident["subject"])
    if owner is not None and owner["id"] != user_id:
        raise OAuthError(f"That {label} account is already used by another Qualifi account.")
    if owner is None:
        if query("SELECT 1 FROM user_identities WHERE user_id = ? AND provider = ?", (user_id, provider), one=True):
            raise OAuthError(f"A different {label} account is already connected. Disconnect it first.")
        _add_identity(user_id, provider, ident)
    flash(f"{label} is connected. You can now log in with it.", "success")
    return redirect(url_for("account.settings"))


@bp.route("/auth/finish", methods=["GET", "POST"])
def finish():
    pending = session.get("oauth_signup")
    if not pending or pending.get("expires", 0) < time.time():
        session.pop("oauth_signup", None)
        flash("Your sign-up took too long. Please start again.", "error")
        return redirect(url_for("auth.register"))
    label = LABELS[pending["provider"]]
    role = request.values.get("role") or pending.get("role") or "candidate"
    if role not in ("candidate", "company"):
        role = "candidate"
    form = {"name": pending.get("name", ""), "company_name": ""}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "company_name")}
        error = None
        if not form["name"]:
            error = "Please enter your name."
        elif role == "company" and not form["company_name"]:
            error = "Please enter your company name."
        elif len(form["name"]) > 120 or len(form["company_name"]) > 160:
            error = "That name is too long."
        elif query("SELECT 1 FROM users WHERE email = ?", (pending["email"],), one=True):
            error = "An account with this email was just created. Please log in."
        elif _identity_owner(pending["provider"], pending["subject"]):
            error = f"This {label} account is already registered. Please log in."
        if error:
            flash(error, "error")
        else:
            password_hash = new_unusable_password()
            db = get_db()
            cur = db.execute("INSERT INTO users (email, password_hash, role, name) VALUES (?, ?, ?, ?)",
                             (pending["email"], password_hash, role, form["name"]))
            uid = cur.lastrowid
            if role == "company":
                db.execute("INSERT INTO companies (user_id, company_name) VALUES (?, ?)", (uid, form["company_name"]))
            else:
                db.execute("INSERT INTO candidate_profiles (user_id) VALUES (?)", (uid,))
            db.execute("INSERT INTO user_identities (user_id, provider, subject, email) VALUES (?, ?, ?, ?)",
                       (uid, pending["provider"], pending["subject"], pending["email"]))
            db.commit()
            start_session(uid, password_hash)       # also removes the pending sign-up
            if role == "company":
                flash("Welcome to Qualifi! Post your first job to start receiving qualified applicants.", "success")
                return redirect(url_for("company.dashboard"))
            flash("Welcome to Qualifi! Upload your CV to build your profile.", "success")
            return redirect(url_for("candidate.upload_cv"))
    return render_template("auth/oauth_finish.html", pending=pending, label=label, role=role, form=form)


@bp.route("/auth/<provider>/disconnect", methods=["POST"])
def disconnect(provider):
    if g.user is None:
        return redirect(url_for("auth.login"))
    if provider not in LABELS:
        abort(404)
    others = query("SELECT COUNT(*) AS n FROM user_identities WHERE user_id = ? AND provider != ?",
                   (g.user["id"], provider), one=True)["n"]
    if not has_password(g.user) and others == 0:
        flash(f"Set a password first, so you can still log in without {LABELS[provider]}.", "error")
        return redirect(url_for("account.settings"))
    db = get_db()
    db.execute("DELETE FROM user_identities WHERE user_id = ? AND provider = ?", (g.user["id"], provider))
    db.commit()
    flash(f"{LABELS[provider]} was disconnected.", "success")
    return redirect(url_for("account.settings"))
