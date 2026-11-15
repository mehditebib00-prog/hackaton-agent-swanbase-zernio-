"""Verified event facts and calls-to-action, from swanbase.co and Luma (checked 2026-11-15).

Only facts listed here may be stated about swanbase / upcoming events. CTAs are
time-boxed: an entry disappears automatically once `until` has passed.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

CTAS = [
    {
        "priority": 1,
        "title": "TheNest F26 — swanbase's free 7-day GTM program in Paris (18–25 Nov 2026): launch your product, "
        "find first paying customers. Free, on application. Applications close tonight 15 Nov at 23:59.",
        "url": "https://form.swanbase.co/to/oUW867Pb",
        "info_url": "https://swanbase.co/events/the-nest-paris-2026-10/",
        "until": datetime(2026, 11, 15, 23, 59, tzinfo=PARIS),
    },
    {
        "priority": 2,
        "title": "Tue 17 Nov 2026, 19:00, Paris 2e — talk: growth models & advanced growth strategies for startups "
        "from €300k to €10M revenue (Théo Sitjar). Free registration on Luma.",
        "url": "https://luma.com/kmecykgp",
        "until": datetime(2026, 11, 17, 19, 0, tzinfo=PARIS),
    },
    {
        "priority": 2,
        "title": "Thu 19 Nov 2026, 19:00, Paris 2e — Startup Recette: pivoting after Y Combinator, "
        "Thomas Minassian tells the .Wave story. Registration on Luma.",
        "url": "https://luma.com/p9zdkbni",
        "until": datetime(2026, 11, 19, 19, 0, tzinfo=PARIS),
    },
    {
        "priority": 3,
        "title": "All upcoming swanbase events (subscribe to the calendar).",
        "url": "https://luma.com/swanbase",
        "until": None,
    },
]

ABOUT = (
    "swanbase: a Paris growth & marketing accelerator for early-stage startups, taking founders "
    "'from your first 10 to your first 1000 customers'. Website: https://swanbase.co"
)


def active_ctas(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(PARIS)
    live = [c for c in CTAS if c["until"] is None or now < c["until"]]
    return sorted(live, key=lambda c: c["priority"])


def event_block(now: datetime | None = None) -> str:
    lines = [ABOUT, "Next steps to offer (highest priority first):"]
    for c in active_ctas(now):
        lines.append(f"- [P{c['priority']}] {c['title']} -> {c['url']}")
    return "\n".join(lines)


def allowed_urls(now: datetime | None = None) -> set[str]:
    urls = {"https://swanbase.co", "https://swanbase.co/"}
    for c in active_ctas(now):
        urls.add(c["url"])
        if c.get("info_url"):
            urls.add(c["info_url"])
    return urls
