"""
db.py — SQLite schema for v2. Tracks questions, series parts, content calendar,
posting results, and Telegram approval state. Committed to repo after each run.
"""

import sqlite3
import os
from datetime import datetime, date, timedelta
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "state.db")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    db = conn()
    db.executescript("""
    -- ── Master question bank ─────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS questions (
        slug            TEXT PRIMARY KEY,
        title           TEXT NOT NULL,
        category        TEXT NOT NULL,       -- dsa | system_design | lld | cs_fundamentals
        pattern         TEXT,                -- sliding_window | dp | graph | ...
        difficulty      TEXT,                -- easy | medium | hard
        companies       TEXT,                -- comma-sep: google,meta,amazon
        depth_score     INTEGER DEFAULT 3,   -- 1-10; >=7 triggers multi-part split
        total_parts     INTEGER DEFAULT 1,   -- AI-determined on first scheduling
        description     TEXT,
        dry_run         TEXT,
        approach        TEXT,
        what_interviewers_want TEXT,
        python_code     TEXT,
        java_code       TEXT,
        added_at        TEXT NOT NULL
    );

    -- ── Content calendar: one row per day ────────────────────────────
    CREATE TABLE IF NOT EXISTS calendar (
        cal_date        TEXT PRIMARY KEY,    -- YYYY-MM-DD
        question_slug   TEXT NOT NULL,
        part_number     INTEGER DEFAULT 1,
        total_parts     INTEGER DEFAULT 1,
        status          TEXT DEFAULT 'pending',  -- pending|approved|posting|done|failed|skipped
        approved_at     TEXT,
        telegram_msg_id INTEGER,
        FOREIGN KEY(question_slug) REFERENCES questions(slug)
    );

    -- ── Series tracker: multi-part questions ─────────────────────────
    CREATE TABLE IF NOT EXISTS series (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_slug     TEXT NOT NULL,
        part_number     INTEGER NOT NULL,
        total_parts     INTEGER NOT NULL,
        part_title      TEXT NOT NULL,
        part_focus      TEXT NOT NULL,       -- what this part covers
        scheduled_date  TEXT,               -- YYYY-MM-DD when this part will post
        status          TEXT DEFAULT 'queued',  -- queued|posted
        UNIQUE(parent_slug, part_number)
    );

    -- ── Posted content log ───────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS posted (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cal_date        TEXT NOT NULL,
        question_slug   TEXT NOT NULL,
        part_number     INTEGER DEFAULT 1,
        platform        TEXT NOT NULL,       -- youtube_short|youtube_long|instagram|linkedin_carousel
        platform_id     TEXT,               -- returned ID from platform
        status          TEXT NOT NULL,       -- success|failed|skipped
        posted_at       TEXT NOT NULL,
        error_msg       TEXT
    );

    -- ── Retry queue ──────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS retry_queue (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cal_date        TEXT NOT NULL,
        platform        TEXT NOT NULL,
        artifact_path   TEXT NOT NULL,
        attempts        INTEGER DEFAULT 0,
        next_retry_at   TEXT NOT NULL,
        status          TEXT DEFAULT 'pending'  -- pending|exhausted|resolved
    );
    """)
    db.commit()
    db.close()


# ── Question bank helpers ─────────────────────────────────────────────────────

def upsert_question(q: dict):
    q = {**q, "depth_score": q.get("depth_score", 3), "total_parts": q.get("total_parts", 1),
         "python_code": q.get("python_code", ""), "java_code": q.get("java_code", "")}
    db = conn()
    db.execute("""
        INSERT INTO questions
            (slug,title,category,pattern,difficulty,companies,depth_score,total_parts,
             description,dry_run,approach,what_interviewers_want,python_code,java_code,added_at)
        VALUES (:slug,:title,:category,:pattern,:difficulty,:companies,:depth_score,:total_parts,
                :description,:dry_run,:approach,:what_interviewers_want,:python_code,:java_code,:added_at)
        ON CONFLICT(slug) DO UPDATE SET
            depth_score=excluded.depth_score,
            total_parts=excluded.total_parts,
            python_code=excluded.python_code,
            java_code=excluded.java_code
    """, {**q, "added_at": q.get("added_at", datetime.utcnow().isoformat())})
    db.commit()
    db.close()


def get_posted_slugs() -> set:
    db = conn()
    rows = db.execute("SELECT DISTINCT question_slug FROM posted WHERE status='success'").fetchall()
    db.close()
    return {r["question_slug"] for r in rows}


def get_recent_patterns(days: int = 7) -> list:
    since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    db = conn()
    rows = db.execute("""
        SELECT q.pattern FROM calendar c
        JOIN questions q ON c.question_slug = q.slug
        WHERE c.cal_date >= ? AND c.status IN ('done','posting')
    """, (since,)).fetchall()
    db.close()
    return [r["pattern"] for r in rows if r["pattern"]]


def count_questions() -> dict:
    db = conn()
    total = db.execute("SELECT COUNT(*) as c FROM questions").fetchone()["c"]
    posted = len(get_posted_slugs())
    db.close()
    return {"total": total, "posted": posted, "remaining": total - posted}


# ── Calendar helpers ──────────────────────────────────────────────────────────

def get_calendar_entry(for_date: str) -> dict | None:
    db = conn()
    row = db.execute("SELECT * FROM calendar WHERE cal_date=?", (for_date,)).fetchone()
    db.close()
    return dict(row) if row else None


def set_calendar_entry(for_date: str, question_slug: str, part_number: int,
                       total_parts: int, telegram_msg_id: int = None):
    db = conn()
    db.execute("""
        INSERT INTO calendar (cal_date, question_slug, part_number, total_parts, telegram_msg_id)
        VALUES (?,?,?,?,?)
        ON CONFLICT(cal_date) DO UPDATE SET
            question_slug=excluded.question_slug,
            part_number=excluded.part_number,
            total_parts=excluded.total_parts
    """, (for_date, question_slug, part_number, total_parts, telegram_msg_id))
    db.commit()
    db.close()


def set_calendar_status(for_date: str, status: str):
    db = conn()
    approved_at = datetime.utcnow().isoformat() if status == "approved" else None
    db.execute("""
        UPDATE calendar SET status=?, approved_at=COALESCE(?,approved_at)
        WHERE cal_date=?
    """, (status, approved_at, for_date))
    db.commit()
    db.close()


def get_question(slug: str) -> dict | None:
    db = conn()
    row = db.execute("SELECT * FROM questions WHERE slug=?", (slug,)).fetchone()
    db.close()
    return dict(row) if row else None


# ── Series helpers ────────────────────────────────────────────────────────────

def get_series_parts(parent_slug: str) -> list:
    db = conn()
    rows = db.execute(
        "SELECT * FROM series WHERE parent_slug=? ORDER BY part_number",
        (parent_slug,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def upsert_series(parent_slug: str, parts: list[dict]):
    """parts: [{"part_number":1,"total_parts":3,"part_title":"...","part_focus":"..."}]"""
    db = conn()
    for p in parts:
        db.execute("""
            INSERT INTO series (parent_slug, part_number, total_parts, part_title, part_focus)
            VALUES (?,?,?,?,?)
            ON CONFLICT(parent_slug, part_number) DO NOTHING
        """, (parent_slug, p["part_number"], p["total_parts"], p["part_title"], p["part_focus"]))
    db.commit()
    db.close()


def next_unposted_part(parent_slug: str) -> dict | None:
    db = conn()
    row = db.execute("""
        SELECT * FROM series WHERE parent_slug=? AND status='queued'
        ORDER BY part_number LIMIT 1
    """, (parent_slug,)).fetchone()
    db.close()
    return dict(row) if row else None


def mark_series_part_posted(parent_slug: str, part_number: int, posted_date: str):
    db = conn()
    db.execute("""
        UPDATE series SET status='posted', scheduled_date=?
        WHERE parent_slug=? AND part_number=?
    """, (posted_date, parent_slug, part_number))
    db.commit()
    db.close()


# ── Posting log ───────────────────────────────────────────────────────────────

def log_post(cal_date: str, slug: str, part_num: int,
             platform: str, status: str, platform_id: str = None, error: str = None):
    db = conn()
    db.execute("""
        INSERT INTO posted (cal_date, question_slug, part_number, platform, platform_id, status, posted_at, error_msg)
        VALUES (?,?,?,?,?,?,?,?)
    """, (cal_date, slug, part_num, platform, platform_id, status,
          datetime.utcnow().isoformat(), error))
    db.commit()
    db.close()


# ── Retry queue ───────────────────────────────────────────────────────────────

def enqueue_retry(cal_date: str, platform: str, artifact_path: str, delay_minutes: int = 30):
    next_retry = (datetime.utcnow() + timedelta(minutes=delay_minutes)).isoformat()
    db = conn()
    db.execute("""
        INSERT INTO retry_queue (cal_date, platform, artifact_path, next_retry_at)
        VALUES (?,?,?,?)
    """, (cal_date, platform, artifact_path, next_retry))
    db.commit()
    db.close()


def get_due_retries() -> list:
    now = datetime.utcnow().isoformat()
    db = conn()
    rows = db.execute("""
        SELECT * FROM retry_queue
        WHERE status='pending' AND next_retry_at <= ? AND attempts < 3
    """, (now,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def update_retry(retry_id: int, success: bool, next_delay_minutes: int = 120):
    db = conn()
    if success:
        db.execute("UPDATE retry_queue SET status='resolved' WHERE id=?", (retry_id,))
    else:
        next_retry = (datetime.utcnow() + timedelta(minutes=next_delay_minutes)).isoformat()
        db.execute("""
            UPDATE retry_queue SET attempts=attempts+1, next_retry_at=?
            WHERE id=?
        """, (next_retry, retry_id))
        db.execute("""
            UPDATE retry_queue SET status='exhausted'
            WHERE id=? AND attempts >= 3
        """, (retry_id,))
    db.commit()
    db.close()
