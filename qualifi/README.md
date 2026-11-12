# Qualifi

**A recruitment platform with skill-based application screening.** Get qualified before you apply.

Candidates build a profile from their CV, take a short test made from the company's own files,
and can apply only if they pass (6/10 by default). They then see their **Qualifi Match**: how well their
skills fit the job, out of 100%, and which skills are missing. Companies upload their own question file or
documents about the role, review the test, publish the job, and get applicants ranked by match.

Free and self-contained: Python, Flask, SQLite, pypdf and python-docx. No paid services, no AI APIs, no API keys.

---

## Run it on your computer

You need **Python 3.10 or newer** ([python.org](https://www.python.org/downloads/)).

```bash
cd qualifi
pip install -r requirements.txt
python run.py
```

Open **http://localhost:5000**. The site starts empty: register a company account to post jobs and a
candidate account to apply. In VS Code you can also press **F5** ("Run Qualifi").

## Where the data lives

Everything is kept in the `instance/` folder (or the folder set in `QUALIFI_DATA_DIR`):

| Path | What it is |
|---|---|
| `instance/qualifi.sqlite` | the database (users, jobs, questions, tests, applications, notifications) |
| `instance/uploads/` | uploaded CVs and company files |
| `instance/secret_key` | signs login cookies (keep it; if lost, everyone is logged out) |
| `instance/logs/qualifi.log` | server errors |

To view the database, open `qualifi.sqlite` with the free "SQLite Viewer" VS Code extension or DB Browser for SQLite.
**Back up the whole folder regularly**; it's the entire site's data. To start over, stop the site and delete it.

## Put it online

1. **Settings.** Copy `.env.example` to `.env` (or set the same variables on your host):
   - `QUALIFI_SECRET_KEY`: a long random value (`python -c "import secrets; print(secrets.token_hex(32))"`)
   - `QUALIFI_HTTPS=1`: the site must be served over https
   - `QUALIFI_BEHIND_PROXY=1`: if your host puts a proxy in front of the app (almost all do)
   - `QUALIFI_DATA_DIR`: a folder on a **persistent disk**, so the database and uploads survive restarts
   - `QUALIFI_BASE_URL`: the site's public address, e.g. `https://www.your-domain.com` (used in reset emails)
   - `QUALIFI_SMTP_HOST`, `QUALIFI_SMTP_PORT`, `QUALIFI_SMTP_USER`, `QUALIFI_SMTP_PASSWORD`, `QUALIFI_MAIL_FROM`:
     an email account for "Forgot password" emails (free: a Gmail app password, or Brevo). Without these,
     reset links are only printed in the server console, which is fine on your own computer.
2. **Start command.** Use a production server, never `run.py`:
   - any OS: `python serve.py` (Waitress, listens on `PORT`, default 8000)
   - Linux: `gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT wsgi:app`
3. **Hosting.** SQLite needs a host with a persistent disk: a VPS (DigitalOcean, Hetzner, Lightsail) behind
   Caddy or Nginx for https, or a platform with a mounted disk (Render, Railway, Fly.io). Hosts with
   throw-away disks (Heroku dynos, Vercel) would lose the data on restart.
4. **Before launch,** add a privacy policy and terms page: the site stores CVs, which are personal data.

## Accounts

- **Forgot password** (link on the login page): emails a reset link that works once, for 1 hour. The page
  gives the same answer whether or not the email has an account, and sends at most one email per address
  every 2 minutes.
- **Account** page (top menu): change password, or delete the account after entering the password.
  Changing or resetting a password logs the account out on every other device.
- **Deleting an account** removes everything linked to it, including uploaded files. A candidate's profile, CV,
  tests and applications go; a company's jobs, tests, files and received applications go, and the
  candidates who applied are notified.

## Sign in with Google, Apple or GitHub

Each button appears on the login and register pages once its keys are in `.env` (see `.env.example`).
New people pick candidate or company and confirm their name (and company name) on one short page;
candidates then upload their CV exactly as after a normal sign-up, and the CV is still required before any test.
If the provider confirms an email that already has a Qualifi account, the two are connected automatically.
From the **Account** page people can connect or disconnect providers, set a password, or delete the account.

The callback URL to register with each provider is `<your site>/auth/<provider>/callback`.

**Google** (free)
1. Go to console.cloud.google.com, create a project, open **APIs & Services → OAuth consent screen**, and
   fill in the app name and support email (audience: External).
2. **Credentials → Create credentials → OAuth client ID → Web application**.
3. Authorized redirect URIs: `http://localhost:5000/auth/google/callback` (for testing) and
   `https://your-domain.com/auth/google/callback`.
4. Put the client ID and secret in `QUALIFI_GOOGLE_CLIENT_ID` / `QUALIFI_GOOGLE_CLIENT_SECRET`.
   Publish the consent screen before launch, or only the test users you list can sign in.

**GitHub** (free)
1. github.com → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Homepage URL: your site. Authorization callback URL: `https://your-domain.com/auth/github/callback`
   (one URL per app, so make a second app with `http://localhost:5000/auth/github/callback` for testing).
3. Generate a client secret; put both in `QUALIFI_GITHUB_CLIENT_ID` / `QUALIFI_GITHUB_CLIENT_SECRET`.

**Apple** (needs the paid Apple Developer Program, and only works on a real https domain, not localhost)
1. developer.apple.com → **Certificates, IDs & Profiles → Identifiers**: create an **App ID** with
   "Sign in with Apple" turned on, then a **Services ID** (for example `com.yourname.qualifi.web`).
2. Configure the Services ID: primary App ID = the one above, domain = `your-domain.com`,
   return URL = `https://your-domain.com/auth/apple/callback`.
3. **Keys → +**: enable "Sign in with Apple", download the `.p8` file (only downloadable once) and note the Key ID.
4. Set `QUALIFI_APPLE_CLIENT_ID` (the Services ID), `QUALIFI_APPLE_TEAM_ID` (top right of the developer
   site), `QUALIFI_APPLE_KEY_ID`, and `QUALIFI_APPLE_PRIVATE_KEY_FILE` (path to the `.p8` file; keep it secret
   and out of git).

When testing on your computer, open the site as **http://localhost:5000** (not 127.0.0.1) so the address
matches the callback URL you registered, or set `QUALIFI_BASE_URL=http://localhost:5000`.

Built-in protection: hashed passwords, CSRF tokens on every form, login lock after 5 wrong passwords
(15 minutes), security headers (CSP, no framing, nosniff), HTTPS-only cookies when `QUALIFI_HTTPS=1`,
companies only see applications to their own jobs, and the test answer key never reaches the browser.

## Run the tests

```bash
python -m unittest discover tests
```

The tests walk both journeys end to end (company posts a job, candidate passes, applies, gets invited),
the fail path and retake cooldown, access control, login lockout and security headers.
Sample files they upload are in `tests/fixtures/`.

---

## Screens

| # | Screen | URL |
|---|---|---|
| 1 | Login / Register | `/login`, `/register` |
| 2 | Upload CV | `/candidate/cv` |
| 3 | Review profile (auto-filled) | `/candidate/profile` |
| 4 | Find a job (search, field, level) | `/jobs` |
| 5 | Job details | `/jobs/<id>` |
| 6 | Qualifi Test (timed, one question at a time) | `/test/<id>` |
| 7 | Grading | `/test/<id>/grading` |
| 8 | Result: qualified, or not qualified yet (topics to review, retake date) | `/test/<id>/result` |
| 9 | Qualifi Match | `/jobs/<id>/match` |
| 10 | Application sent | `/applications/<id>/sent` |
| 11 | My applications (with status updates) | `/applications` |
| 12 | Company dashboard | `/company/` |
| 13 | Post a job | `/company/jobs/new` |
| 14 | Add test files (your own questions, or documents to build from) | `/company/jobs/<id>/documents` |
| 15 | Review test (edit, delete, add questions; settings; publish) | `/company/jobs/<id>/review` |
| 16 | Ranked applicants | `/company/jobs/<id>/applicants` |
| 17 | Applicant profile (CV, scores, missing skills) | `/company/applications/<id>` |
| 18 | Invite sent (candidate is notified) | `/company/applications/<id>/invited` |

## How it works

**Qualifi Test** (`qualifi/services/question_gen.py`). Every question comes from the company's own files:
- **Import your own questions.** Upload a PDF, Word or text file: a numbered question, options A–D, then
  `Answer: B` (or mark the correct option with `*`, or put an answer key at the end). Questions are copied exactly.
- **Build from documents.** Upload guides, policies or manuals. Built-in rules find facts (numbers and limits,
  rules with "must" or "never", named tools and terms) and turn each into a multiple-choice question,
  citing its file and page.
- Companies can edit, delete or add questions before publishing.
- Each candidate gets a random 10 with shuffled options and a time limit. Pass mark 6/10, 14-day
  cooldown after a fail. Leaving the test tab is recorded and shown to the company.

**Qualifi Match** (`qualifi/services/matching.py`). The CV is parsed into a profile and skills are normalized
("JS" = "JavaScript"). **Match % = 60% skill coverage + 25% meaning similarity (TF-IDF) + 15% experience fit.**

## Project structure

```
run.py          start on your computer (development)
serve.py        start the live site (Waitress production server)
wsgi.py         entry point for gunicorn
schema.sql      database tables
qualifi/
  __init__.py   app setup, settings, CSRF, security headers, logging
  auth.py       register, login (with lockout), logout, role checks
  account.py    forgot / reset password, change password, delete account
  oauth.py      sign in with Google, Apple and GitHub
  mailer.py     sends email over SMTP (or prints it when no SMTP is set)
  candidate.py  candidate screens (1–11)
  company.py    company screens (12–18)
  testengine.py starting, grading and cooldown rules for the Qualifi Test
  services/     text extraction, CV parser, skills, matching, test questions
  templates/    HTML pages (Jinja)
  static/       CSS and a little JavaScript
tests/          end-to-end tests and their sample files
```
