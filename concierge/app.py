"""Event concierge: Zernio webhook receiver + Telegram interview bot in one process.

Run:  uv run uvicorn concierge.app:app --port 8000
"""

import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response

load_dotenv(override=True)  # project .env wins over stale shell vars
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines include the bot token URL

from concierge import bot, guard, llm, store, zernio  # noqa: E402

log = logging.getLogger("app")
_seen: set[str] = set()
_account_id: str | None = None

FALLBACK_DM = (
    "Hi {name}! Thanks for your comment. I'm the AI concierge of today's Social GTM Agents Hackathon in Paris "
    "(built on Zernio). Ask me anything about the projects built today."
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tg = None
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        tg = bot.build_application()
        await tg.initialize()
        await tg.start()
        if tg.updater:
            await tg.updater.start_polling(drop_pending_updates=True)
        log.info("telegram bot polling")
    yield
    if tg:
        if tg.updater:
            await tg.updater.stop()
        await tg.stop()
        await tg.shutdown()


app = FastAPI(lifespan=lifespan)


def _account() -> str:
    global _account_id
    if _account_id is None:
        _account_id = zernio.instagram_account_id()
    return str(_account_id)


def _verify(raw: bytes, signature: str) -> bool:
    secret = os.environ.get("ZERNIO_WEBHOOK_SECRET", "")
    if not secret:
        return False
    return hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), signature)


def _latency(ts: str | None) -> float | None:
    try:
        return round((datetime.now(UTC) - datetime.fromisoformat(ts or "")).total_seconds(), 1)
    except ValueError:
        return None


DAILY_REPLY_CAP = 30


def handle_comment(event: dict) -> None:
    c = event["comment"]
    author = c.get("author") or {}
    if author.get("isOwnAccount"):
        return
    username, uid = author.get("username"), author.get("id")
    log.info("comment from=@%s latency=%ss text=%r", username, _latency(c.get("createdAt")), c.get("text"))
    if c.get("platform") not in ("instagram", "facebook"):
        return
    if store.replies_last_24h(username, uid) >= DAILY_REPLY_CAP:
        log.warning("daily cap reached for @%s; skipping", username)
        return
    post_id = c.get("postId") or c["platformPostId"]
    caption = None
    if c.get("postId"):
        try:
            caption = zernio.get_post(c["postId"]).get("content")
        except Exception:  # noqa: BLE001
            caption = None
    sent = store.sent_links(username, uid)
    try:
        r = llm.comment_reply(c.get("text", ""), username, caption, store.knowledge_base(), sent)
        dm, public, interests, wants_dm = r.dm, r.public_reply, r.interests, r.wants_dm
    except Exception as e:  # noqa: BLE001
        log.error("comment_reply LLM failed: %s", e)
        dm, public, interests, wants_dm = FALLBACK_DM.format(name=author.get("name") or username or "there"), "Thanks! Check your DMs.", [], True
    dm, removed = guard.clean(dm, sent)
    public, removed_pub = guard.clean(public, set())
    if removed or removed_pub:
        log.warning("guard removed links: %s", removed + removed_pub)
    account_id = _account()
    if wants_dm:
        try:
            zernio.private_reply(post_id, c["id"], account_id, dm)
            store.record_sent(username, uid, guard.urls_in(dm))
            store.count_reply(username, uid)
            log.info("private reply sent to @%s", username)
        except Exception as e:  # noqa: BLE001
            log.error("private reply failed: %s", e)
    try:
        zernio.public_reply(post_id, c["id"], account_id, public)
    except Exception as e:  # noqa: BLE001
        log.error("public reply failed: %s", e)
    store.upsert_lead("instagram", uid or "?", username, interests, c.get("text", ""))
    bot.notify_owner(f"💬 @{username} commented: {c.get('text')}\n→ interests: {', '.join(interests) or '-'}\n→ DM sent: {wants_dm}")


def handle_message(event: dict) -> None:
    m = event.get("message") or {}
    if (event.get("metadata") or {}).get("standby") or m.get("direction") != "incoming":
        return
    text = m.get("text") or ""
    if not text.strip():
        return
    sender = m.get("sender") or {}
    username, uid = sender.get("username"), sender.get("id")
    conv = m["conversationId"]
    account_id = (event.get("account") or {}).get("accountId") or _account()
    log.info("dm from=@%s latency=%ss text=%r", username, _latency(m.get("sentAt")), text)
    try:
        history = zernio.conversation_history(conv, account_id)
        # The thread already contains the message we are answering; drop it from the history.
        if history and history[-1]["role"] == "user" and history[-1]["text"] == text.strip():
            history = history[:-1]
    except Exception as e:  # noqa: BLE001
        log.warning("zernio history failed, using local copy: %s", e)
        history = store.dm_history(conv)
    store.add_dm(conv, "user", text)
    if store.is_handed_off(username, uid):
        bot.notify_owner(f"🙋 (human mode) @{username}: {text}\nReply in the Zernio inbox. /resume {username} to hand back to the bot.")
        return
    if store.replies_last_24h(username, uid) >= DAILY_REPLY_CAP:
        log.warning("daily cap reached for @%s; skipping", username)
        return
    sent = store.sent_links(username, uid)
    wants_human = False
    try:
        r = llm.dm_answer(history, text, username, store.knowledge_base(), sent)
        reply, interests, wants_human = r.reply, r.interests, r.wants_human
    except Exception as e:  # noqa: BLE001
        log.error("dm_answer LLM failed: %s", e)
        reply, interests = "Thanks for your message! I'll get back to you shortly.", []
    reply, removed = guard.clean(reply, sent)
    if removed:
        log.warning("guard removed links: %s", removed)
    try:
        zernio.send_message(conv, account_id, reply)
        store.add_dm(conv, "assistant", reply)
        store.record_sent(username, uid, guard.urls_in(reply))
        store.count_reply(username, uid)
    except Exception as e:  # noqa: BLE001
        log.error("dm send failed: %s", e)
    store.upsert_lead("instagram", uid or "?", username, interests, text)
    if wants_human:
        store.set_handoff(username, uid, True)
        bot.notify_owner(f"🙋 @{username} asked for a human: {text}\nAuto-replies paused for them. Answer in the Zernio inbox; /resume {username} to hand back.")
    else:
        bot.notify_owner(f"✉️ @{username}: {text}\n🤖 {reply[:300]}")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/webhooks/zernio")
async def zernio_webhook(request: Request, tasks: BackgroundTasks) -> Response:
    raw = await request.body()
    if not _verify(raw, request.headers.get("X-Zernio-Signature", "")):
        log.warning("rejected webhook with bad signature")
        return Response("Invalid signature", status_code=400)
    event = json.loads(raw)
    event_id = event.get("id") or request.headers.get("X-Zernio-Event-Id", "")
    if event_id in _seen:
        return Response("duplicate")
    _seen.add(event_id)
    kind = event.get("event")
    if kind == "comment.received":
        tasks.add_task(handle_comment, event)
    elif kind == "message.received":
        tasks.add_task(handle_message, event)
    else:
        log.info("event %s", kind)
    return Response("ok")
