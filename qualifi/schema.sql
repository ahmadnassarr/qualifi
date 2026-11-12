-- Qualifi database schema (SQLite)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('candidate', 'company')),
    name          TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    headline         TEXT DEFAULT '',
    location         TEXT DEFAULT '',
    phone            TEXT DEFAULT '',
    experience_years REAL DEFAULT 0,
    experience       TEXT DEFAULT '',
    education        TEXT DEFAULT '',
    skills           TEXT DEFAULT '',          -- comma-separated
    cv_path          TEXT,
    cv_filename      TEXT,
    cv_text          TEXT DEFAULT '',
    updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS companies (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    location     TEXT DEFAULT '',
    about        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id         INTEGER NOT NULL REFERENCES companies(user_id) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    field              TEXT NOT NULL,
    level              TEXT NOT NULL CHECK (level IN ('fresh', 'junior', 'senior')),
    location           TEXT DEFAULT '',
    employment_type    TEXT DEFAULT 'Full-time',
    description        TEXT DEFAULT '',
    skills             TEXT DEFAULT '',        -- comma-separated
    status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'closed')),
    pass_mark          INTEGER NOT NULL DEFAULT 6,
    questions_per_test INTEGER NOT NULL DEFAULT 10,
    time_limit_min     INTEGER NOT NULL DEFAULT 15,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    published_at       TEXT
);

CREATE TABLE IF NOT EXISTS job_documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    path        TEXT NOT NULL,
    text        TEXT DEFAULT '',
    pages_json  TEXT DEFAULT '[]',           -- text per page, for citing sources
    kind        TEXT NOT NULL DEFAULT 'material' CHECK (kind IN ('material', 'questions')),
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    options_json TEXT NOT NULL,              -- JSON list of 4 options
    answer_index INTEGER NOT NULL,
    source_doc   TEXT DEFAULT '',
    source_page  INTEGER,
    topic        TEXT DEFAULT '',
    origin       TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('imported', 'local', 'manual')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_attempts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id             INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_id       INTEGER NOT NULL REFERENCES candidate_profiles(user_id) ON DELETE CASCADE,
    question_ids_json  TEXT NOT NULL,        -- the questions this candidate got, in order
    option_orders_json TEXT NOT NULL,        -- shuffled option order per question
    answers_json       TEXT NOT NULL DEFAULT '{}',
    current_index      INTEGER NOT NULL DEFAULT 0,
    started_at         TEXT NOT NULL,
    deadline           TEXT NOT NULL,
    finished_at        TEXT,
    score              INTEGER,
    total              INTEGER,
    passed             INTEGER,
    tab_switches       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_id   INTEGER NOT NULL REFERENCES candidate_profiles(user_id) ON DELETE CASCADE,
    attempt_id     INTEGER NOT NULL UNIQUE REFERENCES test_attempts(id),
    match_score    INTEGER NOT NULL,
    matched_json   TEXT NOT NULL DEFAULT '[]',
    missing_json   TEXT NOT NULL DEFAULT '[]',
    breakdown_json TEXT NOT NULL DEFAULT '{}',
    status         TEXT NOT NULL DEFAULT 'under_review' CHECK (status IN ('under_review', 'interview', 'rejected')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (job_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    link       TEXT DEFAULT '',
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Sign in with Google / Apple / GitHub: one row per connected provider account
CREATE TABLE IF NOT EXISTS user_identities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider   TEXT NOT NULL CHECK (provider IN ('google', 'apple', 'github')),
    subject    TEXT NOT NULL,                 -- the provider's permanent id for this person
    email      TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (provider, subject),
    UNIQUE (user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status      ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_questions_job    ON questions(job_id);
CREATE INDEX IF NOT EXISTS idx_attempts_cand    ON test_attempts(candidate_id, job_id);
CREATE INDEX IF NOT EXISTS idx_apps_job         ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_notifications    ON notifications(user_id, is_read);
