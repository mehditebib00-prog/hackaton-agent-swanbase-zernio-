from datetime import datetime

from concierge import event_info, guard

POST = "https://www.instagram.com/p/DfwyXEcABnl/"


def _allowed(monkeypatch):
    monkeypatch.setattr(guard, "allowed_urls", lambda: {guard._norm(POST), "https://form.swanbase.co/to/oUW867Pb", "https://luma.com/swanbase"})


def test_removes_unknown_link(monkeypatch):
    _allowed(monkeypatch)
    out, removed = guard.clean("Register here: https://evil.example.com/next and enjoy.")
    assert "evil" not in out and removed == ["https://evil.example.com/next"]


def test_keeps_whitelisted_link_with_punctuation(monkeypatch):
    _allowed(monkeypatch)
    out, removed = guard.clean(f"See the post: {POST}.")
    assert POST.rstrip("/") in out and removed == []


def test_drops_link_already_sent(monkeypatch):
    _allowed(monkeypatch)
    out, removed = guard.clean(f"Again: {POST} and apply https://form.swanbase.co/to/oUW867Pb", already_sent={POST})
    assert "instagram.com" not in out and "form.swanbase.co" in out and len(removed) == 1


def test_same_link_twice_in_one_reply(monkeypatch):
    _allowed(monkeypatch)
    out, _ = guard.clean(f"{POST} and again {POST}")
    assert out.count("instagram.com") == 1


def test_thenest_cta_expires_after_deadline():
    before = datetime(2026, 11, 15, 20, 0, tzinfo=event_info.PARIS)
    after = datetime(2026, 11, 16, 0, 1, tzinfo=event_info.PARIS)
    assert "https://form.swanbase.co/to/oUW867Pb" in event_info.allowed_urls(before)
    assert "https://form.swanbase.co/to/oUW867Pb" not in event_info.allowed_urls(after)
    assert "https://luma.com/swanbase" in event_info.allowed_urls(after)


def test_csv_formula_neutralised():
    from concierge import store
    assert store._csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert store._csv_safe("hello") == "hello" and store._csv_safe(3) == 3
