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
               quote, tags, photo_path, ig_caption, status, contact, contact_public)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'draft', ?, ?)""",
            (
                time.time(), data.get("team"), data.get("project"), data.get("one_liner"),
                json.dumps(data.get("ai_tools", [])), data.get("challenge"), data.get("quote"),
                json.dumps(data.get("tags", [])), photo_path, caption,
                data.get("contact"), 1 if data.get("contact_public") else 0,
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


def _usable(contact: str | None) -> bool:
    from concierge import contacts

    return contacts.is_valid(contact)


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
            f"    Quote: \"{i['quote']}\" | Tags: {', '.join(i['tags'])} | Post: {i['ig_url'] or 'n/a'}\n"
            f"    Contact: {'shared publicly (the system appends it)' if i.get('contact_public') and _usable(i.get('contact')) else 'not public (offer an intro)'}"
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


# ---------- guardrails state ----------

_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS sent_links (person TEXT, url TEXT, ts REAL, PRIMARY KEY (person, url));
    CREATE TABLE IF NOT EXISTS auto_replies (person TEXT, ts REAL);
    """
)
_db.commit()


def _person(username: str | None, user_id: str | None) -> str:
    # Comment author ids and DM sender ids can differ on Instagram; the username is shared by both.
    return f"u:{username.lower()}" if username else f"id:{user_id}"


def sent_links(username: str | None, user_id: str | None) -> set[str]:
    rows = _db.execute("SELECT url FROM sent_links WHERE person=?", (_person(username, user_id),)).fetchall()
    return {r["url"] for r in rows}


def record_sent(username: str | None, user_id: str | None, urls: set[str]) -> None:
    with _lock:
        for u in urls:
            _db.execute("INSERT OR IGNORE INTO sent_links VALUES (?,?,?)", (_person(username, user_id), u, time.time()))
        _db.commit()


def replies_last_24h(username: str | None, user_id: str | None) -> int:
    row = _db.execute(
        "SELECT COUNT(*) AS n FROM auto_replies WHERE person=? AND ts>?",
        (_person(username, user_id), time.time() - 86400),
    ).fetchone()
    return int(row["n"])


def count_reply(username: str | None, user_id: str | None) -> None:
    with _lock:
        _db.execute("INSERT INTO auto_replies VALUES (?,?)", (_person(username, user_id), time.time()))
        _db.commit()


def is_handed_off(username: str | None, user_id: str | None) -> bool:
    return get_setting(f"handoff:{_person(username, user_id)}") == "1"


def set_handoff(username: str | None, user_id: str | None, on: bool) -> None:
    set_setting(f"handoff:{_person(username, user_id)}", "1" if on else "0")


def allowed_ids() -> set[int]:
    raw = get_setting("telegram_allowed_ids")
    return set(json.loads(raw)) if raw else set()


def allow_id(user_id: int) -> None:
    ids = allowed_ids() | {user_id}
    set_setting("telegram_allowed_ids", json.dumps(sorted(ids)))


def _csv_safe(v):
    """Neutralise spreadsheet formulas in text written by Instagram users."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def export_csv() -> dict[str, bytes]:
    import csv
    import io

    out = {}
    for name, rows in (("interviews.csv", published_interviews()), ("leads.csv", leads()), ("intros.csv", intros())):
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow({k: _csv_safe(json.dumps(v) if isinstance(v, list) else v) for k, v in r.items()})
        out[name] = buf.getvalue().encode()
    return out


# ---------- contact / intros ----------

for _col, _type in (("contact", "TEXT"), ("contact_public", "INTEGER DEFAULT 0")):
    try:
        _db.execute(f"ALTER TABLE interviews ADD COLUMN {_col} {_type}")
    except sqlite3.OperationalError:
        pass  # column already exists
_db.execute(
    """CREATE TABLE IF NOT EXISTS intro_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL, interview_id INTEGER, team TEXT,
        requester TEXT, requester_contact TEXT, message TEXT, status TEXT)"""
)
_db.commit()


def interview(interview_id: int) -> dict | None:
    for i in published_interviews():
        if i["id"] == interview_id:
            return i
    return None


def add_intro(interview_id: int, team: str, requester: str | None, contact: str, message: str) -> int:
    with _lock:
        cur = _db.execute(
            "INSERT INTO intro_requests (created_at, interview_id, team, requester, requester_contact, message, status) "
            "VALUES (?,?,?,?,?,?, 'new')",
            (time.time(), interview_id, team, requester, contact, message),
        )
        _db.commit()
        return int(cur.lastrowid or 0)


def intros() -> list[dict]:
    return [dict(r) for r in _db.execute("SELECT * FROM intro_requests ORDER BY id").fetchall()]


def set_pending_intro(username: str | None, user_id: str | None, interview_id: int | None) -> None:
    set_setting(f"pending_intro:{_person(username, user_id)}", str(interview_id or ""))


def pending_intro(username: str | None, user_id: str | None) -> int | None:
    v = get_setting(f"pending_intro:{_person(username, user_id)}")
    return int(v) if v else None


def set_contact(interview_id: int, contact: str | None) -> None:
    with _lock:
        _db.execute(
            "UPDATE interviews SET contact=?, contact_public=? WHERE id=?",
            (contact, 1 if contact else 0, interview_id),
        )
        _db.commit()


# ---------- activity feed (dashboard) ----------

_db.execute(
    """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, who TEXT, detail TEXT, latency REAL)"""
)
_db.commit()


def log_event(kind: str, who: str | None, detail: str, latency: float | None = None) -> None:
    with _lock:
        _db.execute(
            "INSERT INTO events (ts, kind, who, detail, latency) VALUES (?,?,?,?,?)",
            (time.time(), kind, who, detail[:300], latency),
        )
        _db.commit()


def dashboard_data() -> dict:
    def q(sql: str, *a):
        return _db.execute(sql, a).fetchall()

    items = published_interviews()
    lead_rows = leads()
    interests: dict[str, int] = {}
    for lead in lead_rows:
        for t in lead["interests"]:
            interests[t] = interests.get(t, 0) + 1
    lat = q("SELECT latency FROM events WHERE kind='comment_dm' AND latency IS NOT NULL")
    lats = sorted(r["latency"] for r in lat)
    return {
        "stats": {
            "teams": len(items),
            "people": len(lead_rows),
            "dms": q("SELECT COUNT(*) n FROM events WHERE kind IN ('comment_dm','dm_reply')")[0]["n"],
            "intros": q("SELECT COUNT(*) n FROM intro_requests")[0]["n"],
            "contacts_shared": q("SELECT COUNT(*) n FROM events WHERE kind='contact_shared'")[0]["n"],
            "median_comment_to_dm": lats[len(lats) // 2] if lats else None,
        },
        "teams": [
            {
                "id": i["id"], "team": i["team"], "project": i["project"], "one_liner": i["one_liner"],
                "tags": i["tags"], "url": i["ig_url"], "contact_public": bool(i.get("contact_public")),
            }
            for i in reversed(items)
        ],
        "interests": sorted(interests.items(), key=lambda kv: -kv[1])[:10],
        "feed": [dict(r) for r in q("SELECT ts, kind, who, detail, latency FROM events ORDER BY id DESC LIMIT 25")],
    }
