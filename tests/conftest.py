import pytest

from concierge import store


@pytest.fixture(autouse=True)
def _no_real_events(monkeypatch):
    """Tests must never write activity events into the live database."""
    monkeypatch.setattr(store, "log_event", lambda *a, **k: None)
