"""Candidate journey: CV upload, profile, jobs, the Qualifi Test, Qualifi Match and applications."""
import json
import os
import uuid

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   send_file, url_for)
from werkzeug.utils import secure_filename

from . import testengine
from .auth import login_required
from .db import execute, loads, notify, query, upload_path
from .services.cv_parser import parse_cv
from .services.matching import compute_match
from .services.skills import split_skills
from .services.text_extract import allowed_file, extract_text
from .timeutil import now, parse, plus

bp = Blueprint("candidate", __name__)


def _profile(uid=None):
    return query("SELECT * FROM candidate_profiles WHERE user_id = ?", (uid or g.user["id"],), one=True)


def _published_job(job_id):
    job = query("SELECT j.*, c.company_name, c.location AS company_location FROM jobs j "
                "JOIN companies c ON c.user_id = j.company_id WHERE j.id = ?", (job_id,), one=True)
    if job is None or job["status"] == "draft":
        abort(404)
    return job


def _own_attempt(attempt_id):
    attempt = query("SELECT * FROM test_attempts WHERE id = ?", (attempt_id,), one=True)
    if attempt is None or attempt["candidate_id"] != g.user["id"]:
        abort(404)
    return attempt


# ---------------------------------------------------------------- 2. Upload CV
@bp.route("/candidate/cv", methods=["GET", "POST"])
@login_required("candidate")
def upload_cv():
    profile = _profile()
    if request.method == "POST":
        file = request.files.get("cv")
        if not file or not file.filename:
            flash("Choose your CV file first.", "error")
        elif not allowed_file(file.filename):
            flash("Please upload a PDF, Word (.docx) or text file.", "error")
        else:
            ext = os.path.splitext(file.filename)[1].lower()
            stored_name = f"cv_{g.user['id']}_{uuid.uuid4().hex}{ext}"
            stored = os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name)
            file.save(stored)
            try:
                text = extract_text(stored)
            except Exception:
                text = ""
            if len(text.strip()) < 30:
                os.remove(stored)
                flash("We couldn’t read text from that file. If it’s a scanned image, please upload a text-based PDF or Word file.", "error")
                return redirect(url_for("candidate.upload_cv"))
            parsed = parse_cv(text)
            old_cv = upload_path(profile["cv_path"]) if profile else None
            if old_cv and os.path.exists(old_cv):
                os.remove(old_cv)
            execute(
                "UPDATE candidate_profiles SET headline = ?, location = ?, phone = ?, experience_years = ?, "
                "experience = ?, education = ?, skills = ?, cv_path = ?, cv_filename = ?, cv_text = ?, "
                "updated_at = datetime('now') WHERE user_id = ?",
                (parsed["headline"], parsed["location"], parsed["phone"], parsed["experience_years"],
                 parsed["experience"], parsed["education"], ", ".join(parsed["skills"]), stored_name,
                 secure_filename(file.filename) or "cv" + ext, text, g.user["id"]),
            )
            if parsed["name"] and len(parsed["name"]) > 2:
                execute("UPDATE users SET name = ? WHERE id = ?", (parsed["name"], g.user["id"]))
            flash("Your profile was filled in from your CV. Check it and fix anything that’s off.", "success")
            return redirect(url_for("candidate.profile", new=1))
    return render_template("candidate/upload_cv.html", profile=profile)


# ---------------------------------------------------------------- 3. Review profile
@bp.route("/candidate/profile", methods=["GET", "POST"])
@login_required("candidate")
def profile():
    prof = _profile()
    if request.method == "POST":
        name = request.form.get("name", "").strip() or g.user["name"]
        try:
            years = max(0.0, min(45.0, float(request.form.get("experience_years") or 0)))
        except ValueError:
            years = 0.0
        skills = ", ".join(split_skills(request.form.get("skills", "")))
        execute("UPDATE users SET name = ? WHERE id = ?", (name, g.user["id"]))
        execute(
            "UPDATE candidate_profiles SET headline = ?, location = ?, phone = ?, experience_years = ?, "
            "experience = ?, education = ?, skills = ?, updated_at = datetime('now') WHERE user_id = ?",
            (request.form.get("headline", "").strip(), request.form.get("location", "").strip(),
             request.form.get("phone", "").strip(), years, request.form.get("experience", "").strip(),
             request.form.get("education", "").strip(), skills, g.user["id"]),
        )
        flash("Profile saved.", "success")
        return redirect(url_for("candidate.jobs"))
    return render_template("candidate/profile.html", profile=prof, is_new=request.args.get("new"))


# ---------------------------------------------------------------- 4. Find a job
@bp.route("/jobs")
@login_required("candidate")
def jobs():
    q = request.args.get("q", "").strip()
    field = request.args.get("field", "")
    level = request.args.get("level", "")
    sql = ("SELECT j.*, c.company_name FROM jobs j JOIN companies c ON c.user_id = j.company_id "
           "WHERE j.status = 'published'")
    args = []
    if q:
        sql += " AND (j.title LIKE ? OR c.company_name LIKE ? OR j.skills LIKE ? OR j.description LIKE ?)"
        args += [f"%{q}%"] * 4
    if field:
        sql += " AND j.field = ?"
        args.append(field)
    if level:
        sql += " AND j.level = ?"
        args.append(level)
    sql += " ORDER BY j.published_at DESC, j.id DESC"
    rows = query(sql, args)
    statuses = {r["id"]: testengine.status_for(r["id"], g.user["id"]) for r in rows}
    return render_template("candidate/jobs.html", jobs=rows, statuses=statuses, q=q, field=field, level=level,
                           has_cv=bool(_profile()["cv_path"]))


# ---------------------------------------------------------------- 5. Job details
@bp.route("/jobs/<int:job_id>")
@login_required("candidate")
def job_detail(job_id):
    job = _published_job(job_id)
    status = testengine.status_for(job_id, g.user["id"])
    return render_template("candidate/job_detail.html", job=job, status=status,
                           skills=split_skills(job["skills"]), has_cv=bool(_profile()["cv_path"]))


@bp.route("/jobs/<int:job_id>/test/start", methods=["POST"])
@login_required("candidate")
def start_test(job_id):
    job = _published_job(job_id)
    if job["status"] != "published":
        flash("This job is closed.", "error")
        return redirect(url_for("candidate.job_detail", job_id=job_id))
    if not _profile()["cv_path"]:
        flash("Upload your CV first so companies can see your profile.", "error")
        return redirect(url_for("candidate.upload_cv"))
    status = testengine.status_for(job_id, g.user["id"])
    if status["state"] == "in_progress":
        return redirect(url_for("candidate.take_test", attempt_id=status["attempt"]["id"]))
    if status["state"] in ("passed", "applied", "failed_wait"):
        return redirect(url_for("candidate.job_detail", job_id=job_id))
    attempt_id = testengine.start_attempt(job, g.user["id"])
    return redirect(url_for("candidate.take_test", attempt_id=attempt_id))


# ---------------------------------------------------------------- 6. Qualifi Test
@bp.route("/test/<int:attempt_id>")
@login_required("candidate")
def take_test(attempt_id):
    attempt = _own_attempt(attempt_id)
    if attempt["finished_at"] or testengine.is_expired(attempt):
        testengine.finish_attempt(attempt_id)
        return redirect(url_for("candidate.result", attempt_id=attempt_id))
    job = _published_job(attempt["job_id"])
    total = len(loads(attempt["question_ids_json"], []))
    index = attempt["current_index"]
    question = testengine.question_view(attempt, index)
    if question is None:  # deleted by the company mid-test: skip it
        execute("UPDATE test_attempts SET current_index = current_index + 1 WHERE id = ?", (attempt_id,))
        if index + 1 >= total:
            testengine.finish_attempt(attempt_id)
            return redirect(url_for("candidate.grading", attempt_id=attempt_id))
        return redirect(url_for("candidate.take_test", attempt_id=attempt_id))
    seconds_left = max(0, int((parse(attempt["deadline"]) - now()).total_seconds()))
    return render_template("candidate/test.html", attempt=attempt, job=job, question=question,
                           index=index, total=total, seconds_left=seconds_left)


@bp.route("/test/<int:attempt_id>/answer", methods=["POST"])
@login_required("candidate")
def answer(attempt_id):
    attempt = _own_attempt(attempt_id)
    if attempt["finished_at"] or testengine.is_expired(attempt):
        testengine.finish_attempt(attempt_id)
        return redirect(url_for("candidate.result", attempt_id=attempt_id))
    total = len(loads(attempt["question_ids_json"], []))
    index = attempt["current_index"]
    try:
        posted_index = int(request.form.get("index", -1))
        choice = int(request.form.get("choice", -1))
    except ValueError:
        posted_index, choice = -1, -1
    if posted_index != index or not 0 <= choice <= 3:
        flash("Pick one answer to continue.", "error")
        return redirect(url_for("candidate.take_test", attempt_id=attempt_id))
    answers = loads(attempt["answers_json"], {})
    answers[str(index)] = choice
    execute("UPDATE test_attempts SET answers_json = ?, current_index = ? WHERE id = ?",
            (json.dumps(answers), index + 1, attempt_id))
    if index + 1 >= total:
        testengine.finish_attempt(attempt_id)
        return redirect(url_for("candidate.grading", attempt_id=attempt_id))
    return redirect(url_for("candidate.take_test", attempt_id=attempt_id))


@bp.route("/test/<int:attempt_id>/event", methods=["POST"])
@login_required("candidate")
def test_event(attempt_id):
    """Called by the page when the candidate leaves the test tab (shown to the company)."""
    attempt = _own_attempt(attempt_id)
    if not attempt["finished_at"]:
        execute("UPDATE test_attempts SET tab_switches = tab_switches + 1 WHERE id = ?", (attempt_id,))
    return jsonify(ok=True)


# ---------------------------------------------------------------- 7. Grading, 8. Result / 8b. Not qualified
@bp.route("/test/<int:attempt_id>/grading")
@login_required("candidate")
def grading(attempt_id):
    _own_attempt(attempt_id)
    testengine.finish_attempt(attempt_id)
    return render_template("candidate/grading.html", attempt_id=attempt_id)


@bp.route("/test/<int:attempt_id>/result")
@login_required("candidate")
def result(attempt_id):
    attempt = _own_attempt(attempt_id)
    if not attempt["finished_at"]:
        if not testengine.is_expired(attempt):
            return redirect(url_for("candidate.take_test", attempt_id=attempt_id))
        attempt = testengine.finish_attempt(attempt_id)
    job = _published_job(attempt["job_id"])
    retake_at = None
    topics = []
    if not attempt["passed"]:
        retake_at = plus(parse(attempt["finished_at"]), days=current_app.config["RETAKE_DAYS"])
        topics = testengine.missed_topics(attempt)
    return render_template("candidate/result.html", attempt=attempt, job=job, retake_at=retake_at, topics=topics)


# ---------------------------------------------------------------- 9. Qualifi Match + apply
def _match_for(job):
    corpus = [r["title"] + " " + (r["description"] or "") + " " + (r["skills"] or "")
              for r in query("SELECT title, description, skills FROM jobs WHERE status = 'published' LIMIT 200")]
    return compute_match(job, _profile(), corpus)


@bp.route("/jobs/<int:job_id>/match")
@login_required("candidate")
def match(job_id):
    job = _published_job(job_id)
    status = testengine.status_for(job_id, g.user["id"])
    if status["state"] == "applied":
        return redirect(url_for("candidate.applications"))
    if status["state"] != "passed":
        flash("Pass the Qualifi Test for this job first.", "error")
        return redirect(url_for("candidate.job_detail", job_id=job_id))
    result = _match_for(job)
    return render_template("candidate/match.html", job=job, m=result, attempt=status["attempt"])


@bp.route("/jobs/<int:job_id>/apply", methods=["POST"])
@login_required("candidate")
def apply(job_id):
    job = _published_job(job_id)
    status = testengine.status_for(job_id, g.user["id"])
    if status["state"] == "applied":
        return redirect(url_for("candidate.applications"))
    if status["state"] != "passed" or job["status"] != "published":
        flash("You can apply after passing the Qualifi Test.", "error")
        return redirect(url_for("candidate.job_detail", job_id=job_id))
    m = _match_for(job)
    app_id = execute(
        "INSERT INTO applications (job_id, candidate_id, attempt_id, match_score, matched_json, missing_json, breakdown_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, g.user["id"], status["attempt"]["id"], m["score"], json.dumps(m["matched"]),
         json.dumps(m["missing"]), json.dumps(m["breakdown"])),
    )
    notify(job["company_id"], f"{g.user['name']} applied to {job['title']} (test {status['attempt']['score']}/"
                              f"{status['attempt']['total']}, match {m['score']}%).",
           url_for("company.applicant", app_id=app_id))
    return redirect(url_for("candidate.sent", app_id=app_id))


# ---------------------------------------------------------------- 10. Sent, 11. My applications
@bp.route("/applications/<int:app_id>/sent")
@login_required("candidate")
def sent(app_id):
    app_row = query("SELECT a.*, j.title, c.company_name FROM applications a JOIN jobs j ON j.id = a.job_id "
                    "JOIN companies c ON c.user_id = j.company_id WHERE a.id = ? AND a.candidate_id = ?",
                    (app_id, g.user["id"]), one=True)
    if app_row is None:
        abort(404)
    return render_template("candidate/sent.html", app=app_row)


@bp.route("/applications")
@login_required("candidate")
def applications():
    rows = query(
        "SELECT a.*, j.title, j.id AS job_id, c.company_name, t.score AS test_score, t.total AS test_total "
        "FROM applications a JOIN jobs j ON j.id = a.job_id JOIN companies c ON c.user_id = j.company_id "
        "JOIN test_attempts t ON t.id = a.attempt_id WHERE a.candidate_id = ? ORDER BY a.updated_at DESC, a.id DESC",
        (g.user["id"],))
    notes = query("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 5", (g.user["id"],))
    unread_ids = [n["id"] for n in notes if not n["is_read"]]
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (g.user["id"],))
    return render_template("candidate/applications.html", apps=rows, notes=notes, unread_ids=unread_ids)


# ---------------------------------------------------------------- CV download (candidate or a company they applied to)
@bp.route("/cv/<int:user_id>")
@login_required()
def download_cv(user_id):
    prof = _profile(user_id)
    cv_file = upload_path(prof["cv_path"]) if prof else None
    if not cv_file or not os.path.exists(cv_file):
        abort(404)
    allowed = g.user["id"] == user_id
    if not allowed and g.user["role"] == "company":
        allowed = query("SELECT 1 FROM applications a JOIN jobs j ON j.id = a.job_id "
                        "WHERE a.candidate_id = ? AND j.company_id = ?", (user_id, g.user["id"]), one=True) is not None
    if not allowed:
        abort(403)
    return send_file(cv_file, download_name=prof["cv_filename"] or "cv.pdf", as_attachment=False)
