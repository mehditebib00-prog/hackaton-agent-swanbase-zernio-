from concierge import app

ECHO = "[echo] You said Zernio"


def test_echo_bot_marker_detected():
    assert app.loop_reason([], ECHO) == "message looks automated"
    assert app.loop_reason([], "auto-reply: thanks for your message") == "message looks automated"


def test_repeat_detected_and_normal_messages_pass():
    hist = [{"role": "user", "text": "Can u give me the email"}, {"role": "assistant", "text": "Sure..."}]
    assert app.loop_reason(hist, "Can u give me the email") == "same message repeated"
    assert app.loop_reason(hist, "What do you do?") is None
    assert app.loop_reason([], "give me your email to contact") is None
    assert app.loop_reason([], "Echo chamber is my startup name, can we talk?") is None


def test_handler_skips_llm_on_loop(monkeypatch):
    calls = {"llm": 0, "sent": 0, "notes": []}
    monkeypatch.setattr(app.zernio, "conversation_history", lambda c, a: [{"role": "user", "text": ECHO}, {"role": "assistant", "text": "hi"}, {"role": "user", "text": ECHO}])
    monkeypatch.setattr(app.llm, "dm_answer", lambda *a, **k: calls.__setitem__("llm", calls["llm"] + 1))
    monkeypatch.setattr(app.zernio, "send_message", lambda *a: calls.__setitem__("sent", calls["sent"] + 1))
    monkeypatch.setattr(app.bot, "notify_owner", lambda t: calls["notes"].append(t))
    monkeypatch.setattr(app.store, "add_dm", lambda *a: None)
    settings = {}
    monkeypatch.setattr(app.store, "get_setting", lambda k: settings.get(k))
    monkeypatch.setattr(app.store, "set_setting", lambda k, v: settings.__setitem__(k, v))
    ev = {"message": {"conversationId": "c1", "direction": "incoming", "text": ECHO, "sender": {"username": "botty", "id": "9"}}, "account": {"accountId": "a"}}
    for _ in range(3):
        app.handle_message(ev)
    assert calls["llm"] == 0 and calls["sent"] == 0 and len(calls["notes"]) == 1  # notified once, not per message
