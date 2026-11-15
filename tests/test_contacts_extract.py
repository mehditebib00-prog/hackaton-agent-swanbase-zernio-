from types import SimpleNamespace as NS

from concierge import app, contacts


def test_word_only_is_not_a_contact():
    assert contacts.extract("Email") == []
    assert contacts.extract("LinkedIn") == []
    assert not contacts.is_valid("Email")


def test_extracts_real_contacts():
    assert contacts.extract("Email: sara@acme.io.") == ["sara@acme.io"]
    assert contacts.extract("linkedin.com/in/sara-b and @sara_builds") == ["linkedin.com/in/sara-b", "@sara_builds"]
    assert contacts.extract("https://acme.io") == ["https://acme.io"]
    assert contacts.extract("+33 6 12 34 56 78") == ["+33 6 12 34 56 78"]


def test_regression_word_email_not_appended(monkeypatch):
    bad = {"id": 3, "team": "T3", "project": "P3", "contact": "Email", "contact_public": 1}
    pending = {}
    monkeypatch.setattr(app.store, "interview", lambda i: bad if i == 3 else None)
    monkeypatch.setattr(app.store, "set_pending_intro", lambda u, i, t: pending.__setitem__("t", t))
    monkeypatch.setattr(app.store, "pending_intro", lambda u, i: pending.get("t"))
    out = app._handle_contact(NS(contact_team_id=3, requester_contact=None), "reply", "give me the email", "idir", "1")
    assert out == "reply" and pending["t"] == 3  # falls back to the intro flow
