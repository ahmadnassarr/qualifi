"""Sign in with Google / Apple / GitHub, against simulated provider servers.
Run:  python -m unittest discover tests"""
import base64
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

import test_flow  # noqa: E402
from qualifi import create_app, oauth  # noqa: E402
from qualifi.db import query  # noqa: E402
from test_flow import Client  # noqa: E402

APPLE_KEY = ec.generate_private_key(ec.SECP256R1())
APPLE_PEM = APPLE_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
ENV = {
    "QUALIFI_GOOGLE_CLIENT_ID": "google-client.apps.googleusercontent.com", "QUALIFI_GOOGLE_CLIENT_SECRET": "gsecret",
    "QUALIFI_GITHUB_CLIENT_ID": "gh-client", "QUALIFI_GITHUB_CLIENT_SECRET": "ghsecret",
    "QUALIFI_APPLE_CLIENT_ID": "com.qualifi.web", "QUALIFI_APPLE_TEAM_ID": "TEAM123456",
    "QUALIFI_APPLE_KEY_ID": "KEY1234567", "QUALIFI_APPLE_PRIVATE_KEY": APPLE_PEM.replace("\n", "\\n"),
    "QUALIFI_BASE_URL": "http://localhost:5000",
}


def fake_jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return enc({"alg": "RS256", "kid": "x"}) + "." + enc(claims) + ".c2lnbmF0dXJl"


class FakeProviders:
    """Pretends to be Google's, Apple's and GitHub's servers."""

    def __init__(self):
        self.person = {}          # what the provider says about the person signing in
        self.nonce = None
        self.redirect_uri = None
        self.tamper = {}          # override id-token claims to test rejection
        self.calls = []

    def __call__(self, url, data=None, headers=None):
        self.calls.append(url)
        p = self.person
        if data is not None:
            assert data["code"] == "good-code", data
            assert data["redirect_uri"] == self.redirect_uri, (data["redirect_uri"], self.redirect_uri)
        if url == "https://oauth2.googleapis.com/token":
            assert data["client_secret"] == "gsecret" and data["grant_type"] == "authorization_code"
            claims = {"iss": "https://accounts.google.com", "aud": ENV["QUALIFI_GOOGLE_CLIENT_ID"],
                      "exp": time.time() + 3600, "nonce": self.nonce, "sub": p["sub"], "email": p["email"],
                      "email_verified": p.get("verified", True), "name": p.get("name", "")}
            claims.update(self.tamper)
            return {"access_token": "ya29", "id_token": fake_jwt(claims)}
        if url == "https://appleid.apple.com/auth/token":
            secret = jwt.decode(data["client_secret"], APPLE_KEY.public_key(), algorithms=["ES256"],
                                audience="https://appleid.apple.com")
            assert secret["iss"] == ENV["QUALIFI_APPLE_TEAM_ID"] and secret["sub"] == ENV["QUALIFI_APPLE_CLIENT_ID"]
            assert jwt.get_unverified_header(data["client_secret"])["kid"] == ENV["QUALIFI_APPLE_KEY_ID"]
            claims = {"iss": "https://appleid.apple.com", "aud": ENV["QUALIFI_APPLE_CLIENT_ID"],
                      "exp": time.time() + 600, "nonce": self.nonce, "sub": p["sub"], "email": p["email"],
                      "email_verified": "true"}
            claims.update(self.tamper)
            return {"access_token": "a", "id_token": fake_jwt(claims)}
        if url == "https://github.com/login/oauth/access_token":
            assert data["client_secret"] == "ghsecret"
            return {"access_token": "gho_token", "token_type": "bearer"}
        if url == "https://api.github.com/user":
            assert headers["Authorization"] == "Bearer gho_token"
            return {"id": int(p["sub"]), "login": p.get("login", "octocat"), "name": p.get("name")}
        if url == "https://api.github.com/user/emails":
            return p.get("emails", [{"email": p["email"], "primary": True, "verified": True}])
        raise AssertionError("unexpected call " + url)


class OAuthTest(unittest.TestCase):
    # reuse the journey helpers from the main tests
    _file = test_flow.QualifiFlowTest._file
    _company_posts_job = test_flow.QualifiFlowTest._company_posts_job
    _candidate = test_flow.QualifiFlowTest._candidate
    _take_test = test_flow.QualifiFlowTest._take_test

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, dict(ENV, QUALIFI_DATA_DIR=self.tmp))
        self.env.start()
        self.fake = FakeProviders()
        self.http = mock.patch.object(oauth, "_http_json", self.fake)
        self.http.start()
        self.app = create_app({"TESTING": True, "DATABASE": os.path.join(self.tmp, "t.sqlite"),
                               "UPLOAD_FOLDER": os.path.join(self.tmp, "uploads")})
        os.makedirs(self.app.config["UPLOAD_FOLDER"], exist_ok=True)

    def tearDown(self):
        self.http.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -------------------------------------------------------- helpers
    def sign_in(self, client, provider, person, role=None, start=None, apple_user=None):
        """Click 'Continue with X', let the fake provider approve, return the callback response."""
        self.fake.person = person
        r = client.get(start or (f"/auth/{provider}/start" + (f"?role={role}" if role else "")))
        if r.status_code == 302 and "/auth/" not in r.headers["Location"] and "://" not in r.headers["Location"]:
            return r
        loc = urlparse(r.headers["Location"])
        qs = parse_qs(loc.query)
        self.fake.nonce = qs.get("nonce", [None])[0]
        self.fake.redirect_uri = qs["redirect_uri"][0]
        callback = urlparse(qs["redirect_uri"][0]).path
        if provider == "apple":
            # Apple POSTs from its own site: no CSRF token, then the page bounces to a GET
            form = {"code": "good-code", "state": qs["state"][0]}
            if apple_user:
                form["user"] = json.dumps(apple_user)
            bounce = client.c.post(callback, data=form)
            self.assertEqual(bounce.status_code, 200)
            target = bounce.headers["Refresh"].split("url=", 1)[1]
            return client.get(target)
        return client.get(f"{callback}?code=good-code&state={qs['state'][0]}")

    def finish(self, client, name="Sara Khalil", role="candidate", company_name=""):
        client.get(f"/auth/finish?role={role}")
        return client.post(f"/auth/finish?role={role}", {"name": name, "company_name": company_name})

    def user(self, email):
        with self.app.app_context():
            return query("SELECT * FROM users WHERE email = ?", (email,), one=True)

    # -------------------------------------------------------- tests
    def test_buttons_always_show_and_unconfigured_ones_explain(self):
        page = Client(self.app).get("/login").get_data(as_text=True)
        for label in ("Google", "Apple", "GitHub"):
            self.assertIn(f"Continue with {label}", page)
        self.assertIn("<svg", page)                                  # logos are drawn
        self.assertIn("role=company", Client(self.app).get("/register?role=company").get_data(as_text=True))
        with mock.patch.dict(os.environ, {"QUALIFI_APPLE_KEY_ID": ""}):
            c = Client(self.app)
            self.assertIn("Continue with Apple", c.get("/login").get_data(as_text=True))  # still shown
            r = c.get("/auth/apple/start?role=company")
            self.assertIn("/register", r.headers["Location"])
            self.assertIn("Signing in with Apple isn’t available yet", c.get(r.headers["Location"]).get_data(as_text=True))
            self.assertEqual(c.get("/auth/apple/callback?code=x&state=y").status_code, 404)
        self.assertEqual(Client(self.app).get("/auth/facebook/start").status_code, 404)

    def test_google_candidate_signup_then_cv_test_and_apply(self):
        co, job_id = self._company_posts_job()
        ca = Client(self.app)
        r = self.sign_in(ca, "google", {"sub": "g-1", "email": "Sara@Gmail.com", "name": "Sara Khalil"}, role="candidate")
        self.assertIn("/auth/finish", r.headers["Location"])
        page = ca.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("sara@gmail.com", page)
        self.assertIn('value="Sara Khalil"', page)          # name prefilled from Google
        r = self.finish(ca)
        self.assertIn("/candidate/cv", r.headers["Location"])  # asked for the CV, like normal sign-up
        u = self.user("sara@gmail.com")
        self.assertEqual(u["role"], "candidate")
        self.assertTrue(u["password_hash"].startswith("!"))
        # CV is required before any test
        r = ca.post(f"/jobs/{job_id}/test/start")
        self.assertIn("/candidate/cv", r.headers["Location"])
        r = ca.post("/candidate/cv", {"cv": self._file("Lina_Haddad_CV.pdf")}, content_type="multipart/form-data")
        self.assertIn("/candidate/profile", r.headers["Location"])
        self._take_test(ca, job_id, correct=True)
        self.assertIn("/sent", ca.post(f"/jobs/{job_id}/apply").headers["Location"])
        with self.app.app_context():
            app_id = query("SELECT id FROM applications", one=True)["id"]
        self.assertEqual(co.get(f"/company/applications/{app_id}").status_code, 200)
        # log out and back in with Google: straight in, no sign-up page
        ca.post("/logout")
        r = self.sign_in(ca, "google", {"sub": "g-1", "email": "sara@gmail.com"})
        self.assertNotIn("/auth/finish", r.headers["Location"])
        self.assertEqual(ca.get("/applications").status_code, 200)

    def test_github_company_signup_needs_company_name(self):
        c = Client(self.app)
        r = self.sign_in(c, "github", {"sub": "4242", "email": "x@ignored.com", "name": None, "login": "acme-hr",
                                       "emails": [{"email": "old@acme.com", "primary": False, "verified": True},
                                                  {"email": "hr@acme.com", "primary": True, "verified": True}]},
                         role="company")
        self.assertIn("/auth/finish", r.headers["Location"])
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("hr@acme.com", page)                  # primary verified email chosen
        self.assertIn("Company name", page)
        page = self.finish(c, name="Nadine", role="company").get_data(as_text=True)
        self.assertIn("Please enter your company name", page)
        r = self.finish(c, name="Nadine", role="company", company_name="Acme")
        self.assertIn("/company", r.headers["Location"])
        self.assertIn("Welcome, Acme", c.get("/company/").get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(query("SELECT subject FROM user_identities", one=True)["subject"], "4242")

    def test_apple_signup_form_post_and_name(self):
        c = Client(self.app)
        r = self.sign_in(c, "apple", {"sub": "001234.abcd", "email": "abc123@privaterelay.appleid.com"},
                         apple_user={"name": {"firstName": "Maya", "lastName": "Khoury"}})
        self.assertIn("/auth/finish", r.headers["Location"])
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn('value="Maya Khoury"', page)
        self.assertIn("/candidate/cv", self.finish(c, name="Maya Khoury").headers["Location"])
        self.assertIsNotNone(self.user("abc123@privaterelay.appleid.com"))
        # second Apple login (Apple sends no name the second time) logs straight in
        c.post("/logout")
        r = self.sign_in(c, "apple", {"sub": "001234.abcd", "email": "abc123@privaterelay.appleid.com"})
        self.assertNotIn("/auth/finish", r.headers["Location"])
        self.assertEqual(c.get("/applications").status_code, 200)

    def test_existing_password_account_is_linked_by_verified_email(self):
        self._candidate(email="lina@test.test")
        c = Client(self.app)
        r = self.sign_in(c, "google", {"sub": "g-77", "email": "lina@test.test"})
        self.assertNotIn("/auth/finish", r.headers["Location"])
        self.assertIn("is now connected", c.get("/jobs").get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) n FROM users", one=True)["n"], 1)
        # the password still works too
        c2 = Client(self.app)
        self.assertEqual(c2.post("/login", {"email": "lina@test.test", "password": "password123"}).status_code, 302)

    def test_unverified_email_is_refused(self):
        self._candidate(email="victim@test.test")
        c = Client(self.app)
        r = self.sign_in(c, "google", {"sub": "attacker", "email": "victim@test.test", "verified": False})
        self.assertIn("/login", r.headers["Location"])
        self.assertIn("verified email", c.get("/login").get_data(as_text=True))
        r = self.sign_in(Client(self.app), "github", {"sub": "9", "email": "", "emails": [
            {"email": "victim@test.test", "primary": True, "verified": False}]})
        self.assertIn("/login", r.headers["Location"])
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) n FROM user_identities", one=True)["n"], 0)

    def test_forged_or_foreign_callbacks_are_refused(self):
        a, b = Client(self.app), Client(self.app)
        self.fake.person = {"sub": "g-5", "email": "p@test.test"}
        loc = urlparse(a.get("/auth/google/start").headers["Location"])
        state = parse_qs(loc.query)["state"][0]
        # state started in browser A, finished in browser B (login CSRF): refused
        r = b.get(f"/auth/google/callback?code=good-code&state={state}")
        self.assertIn("/login", r.headers["Location"])
        self.assertIn("didn’t come from this browser", b.get("/login").get_data(as_text=True))
        # tampered state: refused
        r = a.get(f"/auth/google/callback?code=good-code&state={state[:-2]}xx")
        self.assertIn("/login", r.headers["Location"])
        # user pressed Cancel at the provider
        a.get("/auth/google/start")
        a2 = parse_qs(urlparse(a.get("/auth/google/start").headers["Location"]).query)["state"][0]
        r = a.get(f"/auth/google/callback?error=access_denied&state={a2}")
        self.assertIn("cancelled", a.get(r.headers["Location"]).get_data(as_text=True))
        self.assertEqual(self.fake.calls, [])               # never even talked to the provider

    def test_bad_id_tokens_are_refused(self):
        for tamper in ({"aud": "someone-elses-app"}, {"iss": "https://evil.example"}, {"nonce": "replayed"},
                       {"nonce": None}, {"exp": time.time() - 3600}):
            self.fake.tamper = tamper
            c = Client(self.app)
            r = self.sign_in(c, "google", {"sub": "g-9", "email": "t@test.test"})
            self.assertIn("/login", r.headers["Location"], tamper)
            self.assertIn("couldn’t sign you in with Google", c.get("/login").get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) n FROM users", one=True)["n"], 0)

    def test_password_login_on_social_account_and_set_password(self):
        c = Client(self.app)
        self.sign_in(c, "google", {"sub": "g-2", "email": "omar@gmail.com", "name": "Omar"})
        self.finish(c, name="Omar Saleh")
        c.post("/logout")
        page = c.post("/login", {"email": "omar@gmail.com", "password": "anything1"}).get_data(as_text=True)
        self.assertIn("signs in with Google", page)
        # set a password from the Account page (no current password needed)
        self.sign_in(c, "google", {"sub": "g-2", "email": "omar@gmail.com"})
        page = c.get("/account").get_data(as_text=True)
        self.assertIn("Set a password", page)
        self.assertIn("Type DELETE to confirm", page)
        r = c.post("/account/password", {"password": "newpass123", "confirm": "newpass123"}, follow_redirects=True)
        self.assertIn("Your password is set", r.get_data(as_text=True))
        c.post("/logout")
        self.assertEqual(c.post("/login", {"email": "omar@gmail.com", "password": "newpass123"}).status_code, 302)

    def test_connect_and_disconnect_from_account_page(self):
        c = Client(self.app)
        self.sign_in(c, "google", {"sub": "g-3", "email": "rami@gmail.com"})
        self.finish(c, name="Rami")
        # can't remove the only way in
        page = c.post("/auth/google/disconnect", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Set a password first", page)
        # connect GitHub (different email is fine when linking from the account page)
        c.get("/account")
        self.fake.person = {"sub": "555", "email": "rami@work.com"}
        loc = urlparse(c.post("/auth/github/connect").headers["Location"])
        qs = parse_qs(loc.query)
        self.fake.redirect_uri = qs["redirect_uri"][0]
        r = c.get(f"/auth/github/callback?code=good-code&state={qs['state'][0]}")
        self.assertIn("/account", r.headers["Location"])
        page = c.get("/account").get_data(as_text=True)
        self.assertIn("GitHub is connected", page)
        self.assertIn("rami@work.com", page)
        # now Google can be disconnected (GitHub still works)
        page = c.post("/auth/google/disconnect", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Google was disconnected", page)
        c.post("/logout")
        r = self.sign_in(c, "github", {"sub": "555", "email": "rami@work.com"})
        self.assertNotIn("/auth/finish", r.headers["Location"])
        self.assertEqual(self.user("rami@gmail.com")["id"], self._session_user(c))

    def _session_user(self, client):
        with client.c.session_transaction() as s:
            return s.get("user_id")

    def test_cannot_link_provider_account_used_by_someone_else(self):
        a = Client(self.app)
        self.sign_in(a, "google", {"sub": "g-shared", "email": "first@gmail.com"})
        self.finish(a, name="First")
        b = self._candidate(email="second@test.test")
        b.get("/account")
        self.fake.person = {"sub": "g-shared", "email": "first@gmail.com"}
        qs = parse_qs(urlparse(b.post("/auth/google/connect").headers["Location"]).query)
        self.fake.nonce, self.fake.redirect_uri = qs["nonce"][0], qs["redirect_uri"][0]
        r = b.get(f"/auth/google/callback?code=good-code&state={qs['state'][0]}")
        self.assertIn("already used by another Qualifi account", b.get(r.headers["Location"]).get_data(as_text=True))

    def test_delete_social_only_account(self):
        c = Client(self.app)
        self.sign_in(c, "github", {"sub": "77", "email": "gone@test.test"})
        self.finish(c, name="Gone")
        page = c.post("/account/delete", {"confirm_text": "nope"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("Type DELETE to confirm", page)
        r = c.post("/account/delete", {"confirm_text": "delete"})
        self.assertIn("/login", r.headers["Location"])
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) n FROM users", one=True)["n"], 0)
            self.assertEqual(query("SELECT COUNT(*) n FROM user_identities", one=True)["n"], 0)
        # signing in again starts a fresh sign-up
        r = self.sign_in(Client(self.app), "github", {"sub": "77", "email": "gone@test.test"})
        self.assertIn("/auth/finish", r.headers["Location"])

    def test_pending_signup_expires(self):
        c = Client(self.app)
        self.sign_in(c, "google", {"sub": "g-8", "email": "late@test.test"})
        with c.c.session_transaction() as s:
            s["oauth_signup"]["expires"] = time.time() - 1
            s.modified = True
        r = c.get("/auth/finish")
        self.assertIn("/register", r.headers["Location"])


if __name__ == "__main__":
    unittest.main()
