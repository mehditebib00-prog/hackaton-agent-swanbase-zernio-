"""SQLite storage: interviews (knowledge base), leads, DM history, settings."""

import json
import sqlite3
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "concierge.db"
PHOTO_DIR = DATA_DIR / "photos"

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    PHOTO_DIR.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


_db = _conn()
_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL,
        team TEXT, project TEXT, one_liner TEXT, ai_tools TEXT, challenge TEXT,
        quote TEXT, tags TEXT, photo_path TEXT, ig_caption TEXT,
        ig_post_id TEXT, ig_url TEXT, status TEXT
    );
    CREATE TABLE IF NOT EXISTS leads (
        user_key TEXT PRIMARY KEY,
        platform TEXT, username TEXT, interests TEXT,
        last_text TEXT, touches INTEGER, first_seen REAL, last_seen REAL
    );
    CREATE TABLE IF NOT EXISTS dm_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT, role TEXT, text TEXT, ts REAL
    );
    """
)
_db.commit()


def get_setting(key: str) -> str | None:
    row = _db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with _lock:
        _db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))
        _db.commit()


def add_interview(data: dict, photo_path: str, caption: str) -> int:
    with _lock:
        cur = _db.execute(
            """INSERT INTO interviews (created_at, team, project, one_liner, ai_tools, challenge,
               quote, tags, photo_path, ig_caption, status)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'draft')""",
            (
                time.time(), data.get("team"), data.get("project"), data.get("one_liner"),
                json.dumps(data.get("ai_tools", [])), data.get("challenge"), data.get("quote"),
                json.dumps(data.get("tags", [])), photo_path, caption,
            ),
        )
        _db.commit()
        return int(cur.lastrowid or 0)


def mark_published(interview_id: int, post_id: str, url: str | None, caption: str) -> None:
    with _lock:
        _db.execute(
            "UPDATE interviews SET status='published', ig_post_id=?, ig_url=?, ig_caption=? WHERE id=?",
            (post_id, url, caption, interview_id),
        )
        _db.commit()


def published_interviews() -> list[dict]:
    rows = _db.execute("SELECT * FROM interviews WHERE status='published' ORDER BY id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["ai_tools"] = json.loads(d["ai_tools"] or "[]")
        d["tags"] = json.loads(d["tags"] or "[]")
        out.append(d)
    return out


def knowledge_base() -> str:
    """Compact text of every published interview, for the LLM context."""
    items = published_interviews()
    if not items:
        return "(No teams interviewed yet.)"
    lines = []
    for i in items:
        lines.append(
            f"[{i['id']}] Team: {i['team']} | Project: {i['project']} | {i['one_liner']}\n"
            f"    AI tools: {', '.join(i['ai_tools'])} | Hardest part: {i['challenge']}\n"
            f"    Quote: \"{i['quote']}\" | Tags: {', '.join(i['tags'])} | Post: {i['ig_url'] or 'n/a'}"
        )
    return "\n".join(lines)


def upsert_lead(platform: str, user_id: str, username: str | None, interests: list[str], text: str) -> None:
    key = f"{platform}:{user_id}"
    now = time.time()
    with _lock:
        row = _db.execute("SELECT interests, touches FROM leads WHERE user_key=?", (key,)).fetchone()
        if row:
            merged = sorted(set(json.loads(row["interests"] or "[]")) | set(interests))
            _db.execute(
                "UPDATE leads SET username=COALESCE(?, username), interests=?, last_text=?, touches=?, last_seen=? WHERE user_key=?",
                (username, json.dumps(merged), text, row["touches"] + 1, now, key),
            )
        else:
            _db.execute(
                "INSERT INTO leads VALUES (?,?,?,?,?,?,?,?)",
                (key, platform, username, json.dumps(sorted(set(interests))), text, 1, now, now),
            )
        _db.commit()


def leads() -> list[dict]:
    rows = _db.execute("SELECT * FROM leads ORDER BY last_seen DESC").fetchall()
    return [dict(r) | {"interests": json.loads(r["interests"] or "[]")} for r in rows]


def add_dm(conversation_id: str, role: str, text: str) -> None:
    with _lock:
        _db.execute(
            "INSERT INTO dm_messages (conversation_id, role, text, ts) VALUES (?,?,?,?)",
            (conversation_id, role, text, time.time()),
        )
        _db.commit()


def dm_history(conversation_id: str, limit: int = 12) -> list[dict]:
    rows = _db.execute(
        "SELECT role, text FROM dm_messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]
