"""The Qualifi Test engine: start a test, record answers, grade it, and decide who may apply."""
import json
import random

from flask import current_app

from .db import execute, loads, query
from .timeutil import iso, now, parse, plus


def start_attempt(job, candidate_id):
    """Pick random questions from the company's approved bank and shuffle their options."""
    bank = query("SELECT id, options_json FROM questions WHERE job_id = ?", (job["id"],))
    picked = random.sample(list(bank), min(job["questions_per_test"], len(bank)))
    orders = []
    for q in picked:
        order = list(range(len(loads(q["options_json"], []))))
        random.shuffle(order)
        orders.append(order)
    started = now()
    return execute(
        "INSERT INTO test_attempts (job_id, candidate_id, question_ids_json, option_orders_json, started_at, deadline)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (job["id"], candidate_id, json.dumps([q["id"] for q in picked]), json.dumps(orders),
         iso(started), iso(plus(started, minutes=job["time_limit_min"]))),
    )


def question_view(attempt, index):
    """The question at `index`, with options in this candidate's shuffled order (no answer key)."""
    qids = loads(attempt["question_ids_json"], [])
    orders = loads(attempt["option_orders_json"], [])
    q = query("SELECT * FROM questions WHERE id = ?", (qids[index],), one=True)
    if q is None:
        return None
    options = loads(q["options_json"], [])
    shown = [options[i] for i in orders[index] if i < len(options)]
    return {"id": q["id"], "text": q["text"], "options": shown}


def is_expired(attempt):
    return attempt["finished_at"] is None and now() > parse(attempt["deadline"])


def finish_attempt(attempt_id):
    attempt = query("SELECT * FROM test_attempts WHERE id = ?", (attempt_id,), one=True)
    if attempt["finished_at"]:
        return attempt
    job = query("SELECT * FROM jobs WHERE id = ?", (attempt["job_id"],), one=True)
    qids = loads(attempt["question_ids_json"], [])
    orders = loads(attempt["option_orders_json"], [])
    answers = loads(attempt["answers_json"], {})
    score, total = 0, 0
    for idx, qid in enumerate(qids):
        q = query("SELECT answer_index FROM questions WHERE id = ?", (qid,), one=True)
        if q is None:          # the company deleted this question after the test started
            continue
        total += 1
        shown = answers.get(str(idx))
        if shown is not None and 0 <= shown < len(orders[idx]) and orders[idx][shown] == q["answer_index"]:
            score += 1
    needed = job["pass_mark"] / max(job["questions_per_test"], 1)
    passed = total > 0 and score / total >= needed - 1e-9
    execute("UPDATE test_attempts SET finished_at = ?, score = ?, total = ?, passed = ? WHERE id = ?",
            (iso(now()), score, total, int(passed), attempt_id))
    return query("SELECT * FROM test_attempts WHERE id = ?", (attempt_id,), one=True)


def missed_topics(attempt, limit=4):
    qids = loads(attempt["question_ids_json"], [])
    orders = loads(attempt["option_orders_json"], [])
    answers = loads(attempt["answers_json"], {})
    topics = []
    for idx, qid in enumerate(qids):
        q = query("SELECT answer_index, topic FROM questions WHERE id = ?", (qid,), one=True)
        if q is None:
            continue
        shown = answers.get(str(idx))
        correct = shown is not None and orders[idx][shown] == q["answer_index"]
        if not correct and q["topic"] and q["topic"] not in topics:
            topics.append(q["topic"])
    return topics[:limit]


def status_for(job_id, candidate_id):
    """Where this candidate stands for this job.

    Returns a dict with: state in {'new', 'in_progress', 'passed', 'failed_wait', 'retake', 'applied'},
    plus the related attempt, application and retake date.
    """
    app_row = query("SELECT * FROM applications WHERE job_id = ? AND candidate_id = ?", (job_id, candidate_id), one=True)
    attempts = query("SELECT * FROM test_attempts WHERE job_id = ? AND candidate_id = ? ORDER BY id DESC",
                     (job_id, candidate_id))
    info = {"state": "new", "attempt": None, "application": app_row, "retake_at": None}
    if app_row:
        info["state"] = "applied"
        info["attempt"] = query("SELECT * FROM test_attempts WHERE id = ?", (app_row["attempt_id"],), one=True)
        return info
    for a in attempts:
        if a["finished_at"] is None:
            if is_expired(a):
                a = finish_attempt(a["id"])
            else:
                info.update(state="in_progress", attempt=a)
                return info
        if a["passed"]:
            info.update(state="passed", attempt=a)
            return info
        retake_at = plus(parse(a["finished_at"]), days=current_app.config["RETAKE_DAYS"])
        info.update(attempt=a, retake_at=retake_at)
        info["state"] = "failed_wait" if now() < retake_at else "retake"
        return info
    return info
