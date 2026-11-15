import asyncio

from concierge import app


class FakeTG:
    fails = 2
    started = 0

    def __init__(self):
        self.updater = None

    async def initialize(self):
        if FakeTG.fails > 0:
            FakeTG.fails -= 1
            raise ConnectionError("network down")

    async def start(self):
        FakeTG.started += 1

    async def shutdown(self):
        pass


def test_retries_then_starts(monkeypatch):
    monkeypatch.setattr(app.bot, "build_application", FakeTG)
    monkeypatch.setattr(app, "TG_BACKOFF", (0,))
    state = {}
    asyncio.run(app.run_telegram(state))
    assert FakeTG.started == 1 and isinstance(state["tg"], FakeTG)


def test_gives_up_without_raising(monkeypatch):
    class AlwaysFail(FakeTG):
        async def initialize(self):
            raise ConnectionError("down")

    monkeypatch.setattr(app.bot, "build_application", AlwaysFail)
    monkeypatch.setattr(app, "TG_BACKOFF", (0,))
    monkeypatch.setattr(app, "TG_MAX_ATTEMPTS", 3)
    state = {}
    asyncio.run(app.run_telegram(state))  # must return, not raise
    assert "tg" not in state
