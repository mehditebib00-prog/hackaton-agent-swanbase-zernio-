"""Deterministic output guard: only whitelisted links, each at most once per conversation."""

import re

from concierge import event_info, store

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_TRAILING = ".,;:!?"


def _norm(url: str) -> str:
    return url.rstrip(_TRAILING).rstrip("/")


def allowed_urls() -> set[str]:
    urls = {_norm(u) for u in event_info.allowed_urls()}
    for i in store.published_interviews():
        if i.get("ig_url"):
            urls.add(_norm(i["ig_url"]))
    return urls


def urls_in(text: str) -> set[str]:
    return {_norm(u) for u in URL_RE.findall(text or "")}


def clean(text: str, already_sent: set[str] | None = None) -> tuple[str, list[str]]:
    """Remove links that are not whitelisted or were already sent. Returns (text, removed)."""
    allowed = allowed_urls()
    sent = {_norm(u) for u in (already_sent or set())}
    removed: list[str] = []

    def repl(m: re.Match) -> str:
        raw = m.group(0)
        url = _norm(raw)
        tail = raw[len(raw.rstrip(_TRAILING)):]
        if url not in allowed or url in sent:
            removed.append(url)
            return tail
        sent.add(url)  # a link may also appear only once within the same reply
        return raw

    out = URL_RE.sub(repl, text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\(\s*\)|:\s*(?=\n|$)", "", out).strip()
    return out, removed
