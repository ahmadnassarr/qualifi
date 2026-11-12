"""Database helpers: one SQLite connection per request, plain SQL everywhere."""
import json
import os
import re
import sqlite3

from flask import current_app, g


def get_db():
    if "db" not in g:
        # timeout: wait (instead of failing) when another request is writing at the same moment
        g.db = sqlite3.connect(current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 15000")
    return g.db


def upload_path(stored):
    """Full path of an uploaded file. The database keeps only the file name, so the site
    keeps working if the instance folder is moved to another computer or restored from a backup.
    (Older rows that stored a full path are handled too.)"""
    if not stored:
        return None
    name = re.split(r"[\\/]", stored)[-1]
    return os.path.join(current_app.config["UPLOAD_FOLDER"], name)


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    schema_path = os.path.join(os.path.dirname(current_app.root_path), "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        db.executescript(f.read())
    # WAL lets visitors keep reading while someone else is saving (better for many users at once)
    db.execute("PRAGMA journal_mode = WAL")
    db.commit()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def loads(value, default=None):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def notify(user_id, message, link=""):
    execute("INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)", (user_id, message, link))
