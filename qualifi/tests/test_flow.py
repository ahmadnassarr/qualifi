"""End-to-end tests of both storyboard journeys.   Run:  python -m unittest discover tests"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qualifi import create_app  # noqa: E402
from qualifi.db import loads, query  # noqa: E402

DEMO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class Client:
    def __init__(self, app):
        self.c = app.test_client()

    def token(self):
        html = self.c.get("/login" if not self._logged_in() else "/").get_data(as_text=True)
        with self.c.session_transaction() as s:
            return s.get("csrf_token")

    def _logged_in(self):
        with self.c.session_transaction() as s:
            return "user_id" in s

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token())
        return self.c.post(url, data=data, **kw)


class QualifiFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["QUALIFI_DATA_DIR"] = self.tmp      # never touch the real instance/ folder
        self.app = create_app({
            "TESTING": True,
            "DATABASE": os.path.join(self.tmp, "test.sqlite"),
            "UPLOAD_FOLDER": os.path.join(self.tmp, "uploads"),
        })
        os.makedirs(self.app.config["UPLOAD_FOLDER"], exist_ok=True)
        with self.app.app_context():
            from qualifi.db import init_db
            init_db()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, name):
        with open(os.path.join(DEMO, name), "rb") as f:
            return (io.BytesIO(f.read()), name)

    def _company_posts_job(self):
        co = Client(self.app)
        r = co.post("/register", {"role": "company", "name": "Nadine", "company_name": "TechCo",
                                  "email": "hr@techco.test", "password": "password123"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/company", r.headers["Location"])
        r = co.post("/company/jobs/new", {"title": "Junior Web Developer", "field": "Tech", "level": "junior",
                                          "location": "Beirut", "employment_type": "Full-time",
                                          "description": "React work", "skills": "React, SQL, git, Docker"})
        self.assertEqual(r.status_code, 302)
        job_id = int(re.search(r"/jobs/(\d+)/documents", r.headers["Location"]).group(1))
        # 14. the AI asks for files: upload them
        page = co.get(f"/company/jobs/{job_id}/documents").get_data(as_text=True)
        self.assertIn("Upload your own questions", page)
        r = co.post(f"/company/jobs/{job_id}/documents",
                    {"files": [self._file("TechCo_Onboarding_Guide.pdf"), self._file("TechCo_SQL_Standards.pdf"),
                               self._file("TechCo_Code_Review_Policy.pdf")]},
                    content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) n FROM job_documents WHERE job_id=?", (job_id,), one=True)["n"], 3)
        # generate the test from the files
        r = co.post(f"/company/jobs/{job_id}/generate")
        self.assertEqual(r.status_code, 302)
        page = co.get(f"/company/jobs/{job_id}/review").get_data(as_text=True)
        self.assertIn("Source: TechCo_", page)
        with self.app.app_context():
            n = query("SELECT COUNT(*) n FROM questions WHERE job_id=?", (job_id,), one=True)["n"]
            self.assertGreaterEqual(n, 10)
            qid = query("SELECT id FROM questions WHERE job_id=? LIMIT 1", (job_id,), one=True)["id"]
        # 15. edit one question, add one by hand, then publish
        r = co.post(f"/company/jobs/{job_id}/questions/{qid}", {"text": "Edited?", "option_0": "a", "option_1": "b",
                                                                 "option_2": "c", "option_3": "d", "answer": "2", "topic": "T"})
        self.assertEqual(r.status_code, 302)
        r = co.post(f"/company/jobs/{job_id}/questions/new", {"text": "Manual?", "option_0": "w", "option_1": "x",
                                                               "option_2": "y", "option_3": "z", "answer": "0"})
        with self.app.app_context():
            self.assertEqual(query("SELECT answer_index FROM questions WHERE id=?", (qid,), one=True)["answer_index"], 2)
            self.assertEqual(query("SELECT COUNT(*) n FROM questions WHERE origin='manual'", one=True)["n"], 1)
        r = co.post(f"/company/jobs/{job_id}/publish")
        self.assertIn("applicants", r.headers["Location"])
        return co, job_id

    def _candidate(self, email="lina@test.test", cv="Lina_Haddad_CV.pdf"):
        ca = Client(self.app)
        r = ca.post("/register", {"role": "candidate", "name": "Temp", "email": email, "password": "password123"})
        self.assertIn("/candidate/cv", r.headers["Location"])
        r = ca.post("/candidate/cv", {"cv": self._file(cv)}, content_type="multipart/form-data")
        self.assertIn("/candidate/profile", r.headers["Location"])
        page = ca.get("/candidate/profile").get_data(as_text=True)
        self.assertIn("React", page)
        r = ca.post("/candidate/profile", {"name": "Lina Haddad", "headline": "Junior Web Developer", "location": "Beirut",
                                           "phone": "", "experience_years": "2", "experience": "WebWorks",
                                           "education": "BS CS", "skills": "React, SQL, Git, JavaScript"})
        self.assertIn("/jobs", r.headers["Location"])
        return ca

    def _take_test(self, ca, job_id, correct=True):
        r = ca.post(f"/jobs/{job_id}/test/start")
        attempt_id = int(re.search(r"/test/(\d+)", r.headers["Location"]).group(1))
        with self.app.app_context():
            att = query("SELECT * FROM test_attempts WHERE id=?", (attempt_id,), one=True)
            qids, orders = loads(att["question_ids_json"]), loads(att["option_orders_json"])
            answers = [query("SELECT answer_index FROM questions WHERE id=?", (q,), one=True)["answer_index"] for q in qids]
        for i in range(len(qids)):
            page = ca.get(f"/test/{attempt_id}").get_data(as_text=True)
            self.assertIn(f"Question {i + 1} of {len(qids)}", page)
            right = orders[i].index(answers[i])
            choice = right if correct else (right + 1) % 4
            r = ca.post(f"/test/{attempt_id}/answer", {"index": str(i), "choice": str(choice)})
        self.assertIn("/grading", r.headers["Location"])
        ca.get(f"/test/{attempt_id}/grading")
        return attempt_id

    def test_full_storyboard_flow(self):
        co, job_id = self._company_posts_job()
        ca = self._candidate()
        self.assertIn("Junior Web Developer", ca.get("/jobs").get_data(as_text=True))
        self.assertIn("Take Qualifi Test to apply", ca.get(f"/jobs/{job_id}").get_data(as_text=True))
        # answer key never reaches the browser
        attempt_id = self._take_test(ca, job_id, correct=True)
        page = ca.get(f"/test/{attempt_id}/result").get_data(as_text=True)
        self.assertIn("qualified to apply", page)
        page = ca.get(f"/jobs/{job_id}/match").get_data(as_text=True)
        self.assertIn("Your Qualifi Match", page)
        self.assertIn("Docker", page)  # missing skill shown
        r = ca.post(f"/jobs/{job_id}/apply")
        self.assertIn("/sent", r.headers["Location"])
        self.assertIn("Application sent", ca.get(r.headers["Location"]).get_data(as_text=True))
        self.assertIn("Under review", ca.get("/applications").get_data(as_text=True))
        # company side: ranked applicants, profile, invite
        page = co.get(f"/company/jobs/{job_id}/applicants").get_data(as_text=True)
        self.assertIn("Lina Haddad", page)
        with self.app.app_context():
            app_id = query("SELECT id FROM applications", one=True)["id"]
        self.assertIn("Invite to interview", co.get(f"/company/applications/{app_id}").get_data(as_text=True))
        self.assertEqual(co.get(f"/cv/{query_cand_id(self.app)}").status_code, 200)
        r = co.post(f"/company/applications/{app_id}/status", {"action": "invite"})
        self.assertIn("/invited", r.headers["Location"])
        self.assertIn("Interview invite sent", co.get(r.headers["Location"]).get_data(as_text=True))
        page = ca.get("/applications").get_data(as_text=True)
        self.assertIn("Interview", page)
        self.assertIn("invited you to an interview", page)

    def test_fail_path_and_cooldown(self):
        _co, job_id = self._company_posts_job()
        ca = self._candidate()
        attempt_id = self._take_test(ca, job_id, correct=False)
        page = ca.get(f"/test/{attempt_id}/result").get_data(as_text=True)
        self.assertIn("Not qualified yet", page)
        self.assertIn("Retake unlocks", page)
        # cannot apply or restart during the cooldown
        r = ca.post(f"/jobs/{job_id}/apply")
        self.assertIn(f"/jobs/{job_id}", r.headers["Location"])
        r = ca.post(f"/jobs/{job_id}/test/start")
        self.assertTrue(r.headers["Location"].endswith(f"/jobs/{job_id}"))

    def test_access_control(self):
        co, job_id = self._company_posts_job()
        ca = self._candidate()
        self.assertEqual(ca.get(f"/company/jobs/{job_id}/review").status_code, 302)  # candidate bounced
        other = Client(self.app)
        other.post("/register", {"role": "company", "name": "X", "company_name": "Other",
                                 "email": "x@other.test", "password": "password123"})
        self.assertEqual(other.get(f"/company/jobs/{job_id}/review").status_code, 404)
        self.assertEqual(other.get(f"/cv/{query_cand_id(self.app)}").status_code, 403)
        # missing CSRF token is rejected
        self.assertEqual(co.c.post(f"/company/jobs/{job_id}/publish").status_code, 400)
        # test pages never contain the answer key
        r = ca.post(f"/jobs/{job_id}/test/start")
        page = ca.get(r.headers["Location"]).get_data(as_text=True)
        self.assertNotIn("answer_index", page)
        self.assertNotIn("correct", page)

    def test_import_own_questions(self):
        co, job_id = self._company_posts_job()
        r = co.post(f"/company/jobs/{job_id}/documents", {"kind": "questions",
                    "files": [self._file("TechCo_Question_Bank_sample.pdf")]}, content_type="multipart/form-data")
        self.assertIn("/review", r.headers["Location"])
        with self.app.app_context():
            rows = query("SELECT * FROM questions WHERE job_id=? AND origin='imported'", (job_id,))
            self.assertEqual(len(rows), 6)
            q = next(r for r in rows if "Not Found" in r["text"])
            self.assertEqual(loads(q["options_json"])[q["answer_index"]], "404")
            doc_id = query("SELECT id FROM job_documents WHERE kind='questions'", one=True)["id"]
        self.assertIn("From your question file", co.get(f"/company/jobs/{job_id}/review").get_data(as_text=True))
        # removing the file removes its questions; questions built from documents stay
        co.post(f"/company/jobs/{job_id}/documents/{doc_id}/delete")
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) n FROM questions WHERE origin='imported'", one=True)["n"], 0)
            self.assertGreater(query("SELECT COUNT(*) n FROM questions WHERE origin='local'", one=True)["n"], 0)

    def test_login_logout(self):
        self._candidate()
        c = Client(self.app)
        self.assertEqual(c.post("/login", {"email": "lina@test.test", "password": "wrong"}).status_code, 200)
        r = c.post("/login", {"email": "lina@test.test", "password": "password123"})
        self.assertEqual(r.status_code, 302)
        r = c.post("/logout")
        self.assertIn("/login", r.headers["Location"])

    def test_login_lockout_after_repeated_wrong_passwords(self):
        self._candidate(email="lock@test.test")
        c = Client(self.app)
        for _ in range(5):
            self.assertIn("Wrong email or password", c.post("/login", {"email": "lock@test.test", "password": "nope"})
                          .get_data(as_text=True))
        r = c.post("/login", {"email": "lock@test.test", "password": "password123"})  # even the right one waits
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many wrong passwords", r.get_data(as_text=True))

    def test_security_headers_and_relative_upload_paths(self):
        ca = self._candidate(email="paths@test.test")
        r = ca.get("/candidate/profile")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        with self.app.app_context():
            stored = query("SELECT cv_path FROM candidate_profiles WHERE cv_path IS NOT NULL", one=True)["cv_path"]
        self.assertNotIn(os.sep, stored)   # only the file name, so the data folder can be moved
        self.assertEqual(ca.get(f"/cv/{query_cand_id(self.app)}").status_code, 200)

    # ---------------------------------------------------------------- forgot / reset / change password
    def _reset_link(self):
        body = self.app.config["MAIL_OUTBOX"][-1]["body"]
        return re.search(r"https?://[^/\s]+(/reset-password/\S+)", body).group(1)

    def test_forgot_and_reset_password(self):
        self._candidate(email="reset@test.test")
        c = Client(self.app)
        # unknown email: same answer, no email sent
        page = c.post("/forgot-password", {"email": "nobody@test.test"}).get_data(as_text=True)
        self.assertIn("Check your email", page)
        self.assertEqual(len(self.app.config.get("MAIL_OUTBOX", [])), 0)
        # known email: a link is emailed
        page = c.post("/forgot-password", {"email": "reset@test.test"}).get_data(as_text=True)
        self.assertIn("Check your email", page)
        self.assertEqual(self.app.config["MAIL_OUTBOX"][-1]["to"], "reset@test.test")
        link = self._reset_link()
        self.assertIn("Choose a new password", c.get(link).get_data(as_text=True))
        # mismatched passwords are refused
        self.assertIn("don’t match", c.post(link, {"password": "newpass123", "confirm": "other123"}).get_data(as_text=True))
        r = c.post(link, {"password": "newpass123", "confirm": "newpass123"})
        self.assertIn("/login", r.headers["Location"])
        # the link works only once
        r = c.get(link)
        self.assertIn("/forgot-password", r.headers["Location"])
        # old password no longer works, new one does
        self.assertIn("Wrong email or password",
                      c.post("/login", {"email": "reset@test.test", "password": "password123"}).get_data(as_text=True))
        self.assertEqual(c.post("/login", {"email": "reset@test.test", "password": "newpass123"}).status_code, 302)
        # a tampered link is refused
        self.assertIn("/forgot-password", Client(self.app).get(link[:-3] + "abc").headers["Location"])

    def test_reset_emails_are_rate_limited(self):
        self._candidate(email="spam@test.test")
        c = Client(self.app)
        c.post("/forgot-password", {"email": "spam@test.test"})
        c.post("/forgot-password", {"email": "spam@test.test"})
        self.assertEqual(len(self.app.config["MAIL_OUTBOX"]), 1)

    def test_change_password_logs_out_other_devices(self):
        laptop = self._candidate(email="change@test.test")
        phone = Client(self.app)
        phone.post("/login", {"email": "change@test.test", "password": "password123"})
        self.assertEqual(phone.get("/applications").status_code, 200)
        page = laptop.post("/account/password", {"current": "wrong-one", "password": "brandnew123",
                                                 "confirm": "brandnew123"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("current password isn’t right", page)
        page = laptop.post("/account/password", {"current": "password123", "password": "brandnew123",
                                                 "confirm": "brandnew123"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("Your password was changed", page)
        self.assertEqual(laptop.get("/applications").status_code, 200)          # this device stays logged in
        self.assertIn("/login", phone.get("/applications").headers["Location"])  # the other one is logged out

    # ---------------------------------------------------------------- delete account
    def test_candidate_deletes_account(self):
        co, job_id = self._company_posts_job()
        ca = self._candidate()
        self._take_test(ca, job_id, correct=True)
        ca.post(f"/jobs/{job_id}/apply")
        with self.app.app_context():
            cv = query("SELECT cv_path FROM candidate_profiles", one=True)["cv_path"]
        cv_file = os.path.join(self.app.config["UPLOAD_FOLDER"], cv)
        self.assertTrue(os.path.exists(cv_file))
        # wrong password: nothing happens
        page = ca.post("/account/delete", {"password": "nope"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("was not deleted", page)
        r = ca.post("/account/delete", {"password": "password123"})
        self.assertIn("/login", r.headers["Location"])
        with self.app.app_context():
            for table in ("candidate_profiles", "applications", "test_attempts"):
                self.assertEqual(query(f"SELECT COUNT(*) n FROM {table}", one=True)["n"], 0, table)
            self.assertEqual(query("SELECT COUNT(*) n FROM users WHERE role='candidate'", one=True)["n"], 0)
        self.assertFalse(os.path.exists(cv_file))
        self.assertNotIn("Lina Haddad", co.get(f"/company/jobs/{job_id}/applicants").get_data(as_text=True))
        self.assertIn("Wrong email or password",
                      Client(self.app).post("/login", {"email": "lina@test.test", "password": "password123"})
                      .get_data(as_text=True))

    def test_company_deletes_account(self):
        co, job_id = self._company_posts_job()
        ca = self._candidate()
        self._take_test(ca, job_id, correct=True)
        ca.post(f"/jobs/{job_id}/apply")
        with self.app.app_context():
            docs = [os.path.join(self.app.config["UPLOAD_FOLDER"], r["path"]) for r in query("SELECT path FROM job_documents")]
        self.assertTrue(docs and all(os.path.exists(d) for d in docs))
        self.assertIn("Delete my account", co.get("/account").get_data(as_text=True))
        r = co.post("/account/delete", {"password": "password123"})
        self.assertIn("/login", r.headers["Location"])
        with self.app.app_context():
            for table in ("companies", "jobs", "questions", "job_documents", "applications"):
                self.assertEqual(query(f"SELECT COUNT(*) n FROM {table}", one=True)["n"], 0, table)
        self.assertFalse(any(os.path.exists(d) for d in docs))
        page = ca.get("/applications").get_data(as_text=True)
        self.assertIn("closed its Qualifi account", page)
        self.assertNotIn("Junior Web Developer</", ca.get("/jobs").get_data(as_text=True))

    def test_empty_site_has_no_demo_accounts(self):
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) n FROM users", one=True)["n"], 0)
        c = Client(self.app)
        self.assertIn("Wrong email or password", c.post("/login", {"email": "lina@demo.com", "password": "demo1234"})
                      .get_data(as_text=True))


def query_cand_id(app):
    with app.app_context():
        return query("SELECT id FROM users WHERE role='candidate' LIMIT 1", one=True)["id"]


if __name__ == "__main__":
    unittest.main()
