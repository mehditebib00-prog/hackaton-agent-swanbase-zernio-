from types import SimpleNamespace as NS

from concierge import app

PUBLIC = {"id": 1, "team": "Sara & Tom", "project": "Ghostwriter", "contact": "https://linkedin.com/in/sara", "contact_public": 1}
PRIVATE = {"id": 2, "team": "Pizza Team", "project": "Pizza Agent", "contact": None, "contact_public": 0}


def _setup(monkeypatch):
    state = {"pending": None, "intros": [], "notes": []}
    monkeypatch.setattr(app.store, "interview", lambda i: {1: PUBLIC, 2: PRIVATE}.get(i))
    monkeypatch.setattr(app.store, "set_pending_intro", lambda u, i, t: state.__setitem__("pending", t))
    monkeypatch.setattr(app.store, "pending_intro", lambda u, i: state["pending"])
    monkeypatch.setattr(app.store, "add_intro", lambda *a: state["intros"].append(a) or 1)
    monkeypatch.setattr(app.bot, "notify_owner", lambda t: state["notes"].append(t))
    return state


def test_public_contact_appended_from_db(monkeypatch):
    _setup(monkeypatch)
    out = app._handle_contact(NS(contact_team_id=1, requester_contact=None), "Sharing it below!", "how do I reach Sara?", "bob", "1")
    assert out.endswith("https://linkedin.com/in/sara")


def test_private_team_two_step_intro(monkeypatch):
    st = _setup(monkeypatch)
    out = app._handle_contact(NS(contact_team_id=2, requester_contact=None), "Want an intro? Leave your email.", "how to contact pizza team", "bob", "1")
    assert st["pending"] == 2 and not st["intros"] and "pizza" not in out.split("email.")[-1].lower()
    app._handle_contact(NS(contact_team_id=None, requester_contact="bob@acme.com"), "Thanks!", "sure: bob@acme.com", "bob", "1")
    assert st["intros"] and st["intros"][0][3] == "bob@acme.com" and st["pending"] is None and st["notes"]


def test_hallucinated_contact_rejected(monkeypatch):
    st = _setup(monkeypatch)
    app._handle_contact(NS(contact_team_id=2, requester_contact="fake@x.com"), "ok", "I want to meet the pizza team", "bob", "1")
    assert not st["intros"]
