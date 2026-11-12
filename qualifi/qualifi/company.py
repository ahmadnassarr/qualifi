"""Company journey: dashboard, post a job, add test files, review the test, publish, applicants."""
import json
import os
import uuid

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from . import FIELDS, LEVELS, EMPLOYMENT_TYPES
from .auth import login_required
from .db import execute, get_db, loads, notify, query, upload_path
from .services.question_gen import generate_questions, parse_question_bank
from .services.skills import split_skills
from .services.text_extract import allowed_file, extract_pages
from .timeutil import iso, now

bp = Blueprint("company", __name__, url_prefix="/company")

MAX_FILES_PER_JOB = 10


def _company():
    return query("SELECT * FROM companies WHERE user_id = ?", (g.user["id"],), one=True)


def _own_job(job_id):
    job = query("SELECT * FROM jobs WHERE id = ? AND company_id = ?", (job_id, g.user["id"]), one=True)
    if job is None:
        abort(404)
    return job


def _own_application(app_id):
    row = query(
        "SELECT a.*, j.title, j.level, j.company_id, j.id AS job_id, j.questions_per_test, "
        "u.name, u.email, p.headline, p.location, p.phone, p.experience_years, p.experience, p.education, "
        "p.skills, p.cv_filename, t.score AS test_score, t.total AS test_total, t.tab_switches, "
        "t.started_at, t.finished_at "
        "FROM applications a JOIN jobs j ON j.id = a.job_id JOIN users u ON u.id = a.candidate_id "
        "JOIN candidate_profiles p ON p.user_id = a.candidate_id JOIN test_attempts t ON t.id = a.attempt_id "
        "WHERE a.id = ?", (app_id,), one=True)
    if row is None or row["company_id"] != g.user["id"]:
        abort(404)
    return row


# ---------------------------------------------------------------- 12. Dashboard
@bp.route("/")
@login_required("company")
def dashboard():
    jobs = query(
        "SELECT j.*, "
        "(SELECT COUNT(*) FROM applications a WHERE a.job_id = j.id) AS applicants, "
        "(SELECT COUNT(*) FROM test_attempts t WHERE t.job_id = j.id AND t.finished_at IS NOT NULL) AS tests_taken, "
        "(SELECT COUNT(*) FROM questions q WHERE q.job_id = j.id) AS question_count "
        "FROM jobs j WHERE j.company_id = ? ORDER BY j.id DESC", (g.user["id"],))
    stats = {
        "open": sum(1 for j in jobs if j["status"] == "published"),
        "applicants": sum(j["applicants"] for j in jobs),
        "tests": sum(j["tests_taken"] for j in jobs),
    }
    notes = query("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 5", (g.user["id"],))
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (g.user["id"],))
    return render_template("company/dashboard.html", company=_company(), jobs=jobs, stats=stats, notes=notes)


# ---------------------------------------------------------------- 13. Post a job (and edit)
def _job_form_values():
    f = request.form
    level = f.get("level", "junior")
    return {
        "title": f.get("title", "").strip(),
        "field": f.get("field", "Other"),
        "level": level if level in LEVELS else "junior",
        "location": f.get("location", "").strip(),
        "employment_type": f.get("employment_type", "Full-time"),
        "description": f.get("description", "").strip(),
        "skills": ", ".join(split_skills(f.get("skills", ""))),
    }


@bp.route("/jobs/new", methods=["GET", "POST"])
@login_required("company")
def new_job():
    company = _company()
    values = {"title": "", "field": FIELDS[0], "level": "junior", "location": company["location"],
              "employment_type": "Full-time", "description": "", "skills": ""}
    if request.method == "POST":
        values = _job_form_values()
        if not values["title"] or not values["skills"]:
            flash("Add a job title and at least one required skill.", "error")
        elif values["field"] not in FIELDS or values["employment_type"] not in EMPLOYMENT_TYPES:
            flash("Choose a field and job type from the lists.", "error")
        else:
            job_id = execute(
                "INSERT INTO jobs (company_id, title, field, level, location, employment_type, description, skills)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (g.user["id"], values["title"], values["field"], values["level"], values["location"],
                 values["employment_type"], values["description"], values["skills"]))
            return redirect(url_for("company.documents", job_id=job_id))
    return render_template("company/job_form.html", values=values, job=None)


@bp.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@login_required("company")
def edit_job(job_id):
    job = _own_job(job_id)
    values = dict(job)
    if request.method == "POST":
        values = _job_form_values()
        if not values["title"] or not values["skills"]:
            flash("Add a job title and at least one required skill.", "error")
        else:
            execute("UPDATE jobs SET title = ?, field = ?, level = ?, location = ?, employment_type = ?, "
                    "description = ?, skills = ? WHERE id = ?",
                    (values["title"], values["field"], values["level"], values["location"],
                     values["employment_type"], values["description"], values["skills"], job_id))
            flash("Job updated.", "success")
            return redirect(url_for("company.dashboard"))
    return render_template("company/job_form.html", values=values, job=job)


# ---------------------------------------------------------------- 14. Add test files
def _save_upload(job_id, file):
    """Save one upload; return (path, pages) or (None, None) if it can't be read."""
    if not allowed_file(file.filename):
        return None, None
    ext = os.path.splitext(file.filename)[1].lower()
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], f"doc_{job_id}_{uuid.uuid4().hex}{ext}")
    file.save(path)
    try:
        pages = extract_pages(path)
    except Exception:
        pages = []
    if sum(len(p) for p in pages) < 40:
        os.remove(path)
        return None, None
    return path, pages


def _insert_questions(job_id, questions):
    db = get_db()
    db.executemany(
        "INSERT INTO questions (job_id, text, options_json, answer_index, source_doc, source_page, topic, origin)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(job_id, q["text"], json.dumps(q["options"]), q["answer_index"], q["source_doc"], q["source_page"],
          q["topic"], q["origin"]) for q in questions])
    db.commit()


@bp.route("/jobs/<int:job_id>/documents", methods=["GET", "POST"])
@login_required("company")
def documents(job_id):
    job = _own_job(job_id)
    docs = query("SELECT * FROM job_documents WHERE job_id = ? ORDER BY id", (job_id,))
    if request.method == "POST":
        kind = "questions" if request.form.get("kind") == "questions" else "material"
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            flash("Choose at least one file.", "error")
        elif len(docs) + len(files) > MAX_FILES_PER_JOB:
            flash(f"You can add up to {MAX_FILES_PER_JOB} files per job.", "error")
        else:
            added, skipped, imported, problems = 0, [], 0, []
            existing = {r["text"].strip().lower() for r in query("SELECT text FROM questions WHERE job_id = ?", (job_id,))}
            for file in files:
                path, pages = _save_upload(job_id, file)
                name = secure_filename(file.filename) or "document"
                if path is None:
                    skipped.append(file.filename)
                    continue
                if kind == "questions":
                    questions, bad = parse_question_bank(pages, name)
                    questions = [q for q in questions if q["text"].strip().lower() not in existing]
                    if not questions and not bad:
                        os.remove(path)
                        skipped.append(file.filename)
                        continue
                    if not questions:
                        os.remove(path)
                        problems.append(f"{file.filename} (no complete questions found)")
                        continue
                    _insert_questions(job_id, questions)
                    existing.update(q["text"].strip().lower() for q in questions)
                    imported += len(questions)
                    if bad:
                        problems.append(f"{file.filename}: question{'s' if len(bad) != 1 else ''} "
                                        + ", ".join(str(n) for n in bad[:10]))
                execute("INSERT INTO job_documents (job_id, filename, path, text, pages_json, kind) VALUES (?, ?, ?, ?, ?, ?)",
                        (job_id, name, os.path.basename(path), "\n\n".join(pages), json.dumps(pages), kind))
                added += 1
            if kind == "questions" and imported:
                flash(f"Imported {imported} question{'s' if imported != 1 else ''} exactly as written in your file.", "success")
                if problems:
                    flash("Skipped (needs 4 options and a marked answer): " + "; ".join(problems) + ".", "error")
                return redirect(url_for("company.review", job_id=job_id))
            if kind == "material" and added:
                flash(f"Added {added} file{'s' if added != 1 else ''}.", "success")
            if problems:
                flash("Couldn’t import: " + "; ".join(problems) + ". Check the question format below.", "error")
            if skipped:
                flash("Couldn’t read: " + ", ".join(skipped) + ". Use text-based PDF, Word or text files.", "error")
        return redirect(url_for("company.documents", job_id=job_id))
    question_count = query("SELECT COUNT(*) AS n FROM questions WHERE job_id = ?", (job_id,), one=True)["n"]
    return render_template("company/documents.html", job=job, question_count=question_count,
                           materials=[d for d in docs if d["kind"] == "material"],
                           banks=[d for d in docs if d["kind"] == "questions"])


@bp.route("/jobs/<int:job_id>/documents/<int:doc_id>/delete", methods=["POST"])
@login_required("company")
def delete_document(job_id, doc_id):
    _own_job(job_id)
    doc = query("SELECT * FROM job_documents WHERE id = ? AND job_id = ?", (doc_id, job_id), one=True)
    if doc:
        doc_file = upload_path(doc["path"])
        if doc_file and os.path.exists(doc_file):
            os.remove(doc_file)
        execute("DELETE FROM job_documents WHERE id = ?", (doc_id,))
        if doc["kind"] == "questions":
            execute("DELETE FROM questions WHERE job_id = ? AND origin = 'imported' AND source_doc = ?",
                    (job_id, doc["filename"]))
            flash(f"Removed {doc['filename']} and the questions imported from it.", "success")
        else:
            flash(f"Removed {doc['filename']}.", "success")
    return redirect(url_for("company.documents", job_id=job_id))


@bp.route("/jobs/<int:job_id>/generate", methods=["POST"])
@login_required("company")
def generate(job_id):
    job = _own_job(job_id)
    docs = query("SELECT * FROM job_documents WHERE job_id = ? AND kind = 'material' ORDER BY id", (job_id,))
    if not docs:
        flash("Upload at least one file about the role to build questions from.", "error")
        return redirect(url_for("company.documents", job_id=job_id))
    documents = [{"filename": d["filename"], "path": upload_path(d["path"]),"pages": loads(d["pages_json"], [d["text"]])}
                 for d in docs]
    questions = generate_questions(job, documents, current_app.config["QUESTIONS_TO_GENERATE"])
    if not questions:
        flash("We couldn’t find enough facts in these files to build questions. Add more detailed files "
              "(policies, guides, procedures), import your own questions, or add questions by hand.", "error")
        return redirect(url_for("company.documents", job_id=job_id))
    execute("DELETE FROM questions WHERE job_id = ? AND origin = 'local'", (job_id,))
    _insert_questions(job_id, questions)
    flash(f"{len(questions)} questions built from your {len(docs)} file{'s' if len(docs) != 1 else ''}. "
          "Check each one below; every question shows the file and page it came from.", "success")
    return redirect(url_for("company.review", job_id=job_id))


# ---------------------------------------------------------------- 15. Review test
@bp.route("/jobs/<int:job_id>/review")
@login_required("company")
def review(job_id):
    job = _own_job(job_id)
    rows = query("SELECT * FROM questions WHERE job_id = ? ORDER BY id", (job_id,))
    questions = [dict(r, options=loads(r["options_json"], [])) for r in rows]
    docs = query("SELECT filename FROM job_documents WHERE job_id = ?", (job_id,))
    return render_template("company/review.html", job=job, questions=questions, docs=docs)


def _question_from_form():
    f = request.form
    options = [f.get(f"option_{i}", "").strip() for i in range(4)]
    try:
        answer = int(f.get("answer", -1))
    except ValueError:
        answer = -1
    text = f.get("text", "").strip()
    if not text or any(not o for o in options) or not 0 <= answer < 4:
        return None
    if len({o.lower() for o in options}) < 4:
        return None
    return {"text": text, "options": options, "answer": answer, "topic": f.get("topic", "").strip()[:60]}


@bp.route("/jobs/<int:job_id>/questions/new", methods=["POST"])
@login_required("company")
def add_question(job_id):
    _own_job(job_id)
    q = _question_from_form()
    if q is None:
        flash("A question needs text, four different options and one correct answer.", "error")
    else:
        execute("INSERT INTO questions (job_id, text, options_json, answer_index, topic, origin, source_doc)"
                " VALUES (?, ?, ?, ?, ?, 'manual', 'Added by company')",
                (job_id, q["text"], json.dumps(q["options"]), q["answer"], q["topic"]))
        flash("Question added.", "success")
    return redirect(url_for("company.review", job_id=job_id) + "#add")


@bp.route("/jobs/<int:job_id>/questions/<int:qid>", methods=["POST"])
@login_required("company")
def edit_question(job_id, qid):
    _own_job(job_id)
    existing = query("SELECT id FROM questions WHERE id = ? AND job_id = ?", (qid, job_id), one=True)
    q = _question_from_form()
    if existing is None:
        abort(404)
    if q is None:
        flash("A question needs text, four different options and one correct answer.", "error")
    else:
        execute("UPDATE questions SET text = ?, options_json = ?, answer_index = ?, topic = ? WHERE id = ?",
                (q["text"], json.dumps(q["options"]), q["answer"], q["topic"], qid))
        flash("Question saved.", "success")
    return redirect(url_for("company.review", job_id=job_id) + f"#q{qid}")


@bp.route("/jobs/<int:job_id>/questions/<int:qid>/delete", methods=["POST"])
@login_required("company")
def delete_question(job_id, qid):
    _own_job(job_id)
    execute("DELETE FROM questions WHERE id = ? AND job_id = ?", (qid, job_id))
    flash("Question removed.", "success")
    return redirect(url_for("company.review", job_id=job_id))


@bp.route("/jobs/<int:job_id>/settings", methods=["POST"])
@login_required("company")
def test_settings(job_id):
    _own_job(job_id)
    try:
        per_test = max(3, min(50, int(request.form.get("questions_per_test", 10))))
        pass_mark = max(1, min(per_test, int(request.form.get("pass_mark", 6))))
        minutes = max(3, min(120, int(request.form.get("time_limit_min", 15))))
    except ValueError:
        flash("Use whole numbers for the test settings.", "error")
        return redirect(url_for("company.review", job_id=job_id))
    execute("UPDATE jobs SET questions_per_test = ?, pass_mark = ?, time_limit_min = ? WHERE id = ?",
            (per_test, pass_mark, minutes, job_id))
    flash("Test settings saved.", "success")
    return redirect(url_for("company.review", job_id=job_id))


@bp.route("/jobs/<int:job_id>/publish", methods=["POST"])
@login_required("company")
def publish(job_id):
    job = _own_job(job_id)
    n = query("SELECT COUNT(*) AS n FROM questions WHERE job_id = ?", (job_id,), one=True)["n"]
    if n < job["questions_per_test"]:
        flash(f"Your bank has {n} questions but each test uses {job['questions_per_test']}. "
              "Add questions or lower the number per test.", "error")
        return redirect(url_for("company.review", job_id=job_id))
    execute("UPDATE jobs SET status = 'published', published_at = COALESCE(published_at, ?) WHERE id = ?",
            (iso(now()), job_id))
    return redirect(url_for("company.applicants", job_id=job_id, published=1))


@bp.route("/jobs/<int:job_id>/close", methods=["POST"])
@login_required("company")
def close_job(job_id):
    job = _own_job(job_id)
    new_status = "published" if job["status"] == "closed" else "closed"
    execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
    flash("Job reopened." if new_status == "published" else "Job closed. Candidates can no longer apply.", "success")
    return redirect(url_for("company.dashboard"))


# ---------------------------------------------------------------- 16. Ranked applicants
@bp.route("/jobs/<int:job_id>/applicants")
@login_required("company")
def applicants(job_id):
    job = _own_job(job_id)
    rows = query(
        "SELECT a.*, u.name, p.headline, t.score AS test_score, t.total AS test_total, t.tab_switches "
        "FROM applications a JOIN users u ON u.id = a.candidate_id JOIN candidate_profiles p ON p.user_id = a.candidate_id "
        "JOIN test_attempts t ON t.id = a.attempt_id WHERE a.job_id = ? "
        "ORDER BY CASE a.status WHEN 'rejected' THEN 1 ELSE 0 END, a.match_score DESC, t.score DESC, a.id",
        (job_id,))
    tests = query("SELECT COUNT(*) AS taken, COALESCE(SUM(passed), 0) AS passed FROM test_attempts "
                  "WHERE job_id = ? AND finished_at IS NOT NULL", (job_id,), one=True)
    return render_template("company/applicants.html", job=job, apps=rows, tests=tests,
                           just_published=request.args.get("published"))


# ---------------------------------------------------------------- 17. Applicant profile, 18. Invite sent
@bp.route("/applications/<int:app_id>")
@login_required("company")
def applicant(app_id):
    app_row = _own_application(app_id)
    return render_template("company/applicant.html", a=app_row, matched=loads(app_row["matched_json"], []),
                           missing=loads(app_row["missing_json"], []), breakdown=loads(app_row["breakdown_json"], {}),
                           skills=split_skills(app_row["skills"]))


@bp.route("/applications/<int:app_id>/status", methods=["POST"])
@login_required("company")
def set_status(app_id):
    app_row = _own_application(app_id)
    action = request.form.get("action")
    company = _company()["company_name"]
    if action == "invite":
        execute("UPDATE applications SET status = 'interview', updated_at = datetime('now') WHERE id = ?", (app_id,))
        notify(app_row["candidate_id"], f"{company} invited you to an interview for {app_row['title']}.",
               url_for("candidate.applications"))
        return redirect(url_for("company.invited", app_id=app_id))
    if action == "reject":
        execute("UPDATE applications SET status = 'rejected', updated_at = datetime('now') WHERE id = ?", (app_id,))
        notify(app_row["candidate_id"], f"{company} decided not to move forward with your application for "
                                        f"{app_row['title']}.", url_for("candidate.applications"))
        flash(f"{app_row['name']} was marked as not selected and has been notified.", "success")
        return redirect(url_for("company.applicants", job_id=app_row["job_id"]))
    if action == "review":
        execute("UPDATE applications SET status = 'under_review', updated_at = datetime('now') WHERE id = ?", (app_id,))
        flash("Moved back to under review.", "success")
        return redirect(url_for("company.applicant", app_id=app_id))
    abort(400)


@bp.route("/applications/<int:app_id>/invited")
@login_required("company")
def invited(app_id):
    app_row = _own_application(app_id)
    return render_template("company/invited.html", a=app_row)
