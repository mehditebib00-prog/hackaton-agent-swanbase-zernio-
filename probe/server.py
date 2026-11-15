"""Probe webhook receiver.

Goal: prove that an Instagram comment reaches us in real time and that we can
answer it with a private DM + public reply, and answer DMs, through Zernio.

Run:  uv run uvicorn probe.server:app --port 8000
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response

from probe import zernio

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("probe")

app = FastAPI()
_seen_event_ids: set[str] = set()
_account_id: str | None = None

PRIVATE_REPLY = "Hi {name}! Thanks for your comment. This DM was sent automatically by our event agent, built on Zernio."
PUBLIC_REPLY = "Thanks {name}! Check your DMs."
DM_REPLY = "Got your message: \"{text}\". The event agent will answer questions about today's projects here soon."


def _account() -> str:
    global _account_id
    if _account_id is None:
        _account_id = zernio.instagram_account_id()
        log.info("using instagram account_id=%s", _account_id)
    return _account_id


def _verify(raw: bytes, signature: str) -> bool:
    secret = os.environ.get("ZERNIO_WEBHOOK_SECRET", "")
    if not secret:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _latency_seconds(created_at: str | None) -> float | None:
    if not created_at:
        return None
    try:
        t = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - t).total_seconds(), 1)
    except ValueError:
        return None


def handle_comment(event: dict) -> None:
    c = event["comment"]
    author = c.get("author") or {}
    if author.get("isOwnAccount"):
        log.info("skip own comment id=%s", c.get("id"))
        return
    log.info(
        "comment.received platform=%s post=%s comment=%s from=@%s latency=%ss text=%r",
        c.get("platform"), c.get("platformPostId"), c.get("id"),
        author.get("username"), _latency_seconds(c.get("createdAt")), c.get("text"),
    )
    if c.get("platform") not in ("instagram", "facebook"):
        return
    name = author.get("name") or author.get("username") or "there"
    post_id = c.get("postId") or c["platformPostId"]
    account_id = _account()
    try:
        zernio.private_reply(post_id, c["id"], account_id, PRIVATE_REPLY.format(name=name))
        log.info("private reply sent to @%s", author.get("username"))
    except Exception as e:  # noqa: BLE001 - probe: log and keep going
        log.error("private reply failed: %s", e)
    try:
        zernio.public_reply(post_id, c["id"], account_id, PUBLIC_REPLY.format(name=name))
        log.info("public reply posted")
    except Exception as e:  # noqa: BLE001
        log.error("public reply failed: %s", e)


def handle_message(event: dict) -> None:
    m = event.get("message") or {}
    meta = event.get("metadata") or {}
    if meta.get("standby") or m.get("direction") != "incoming":
        return
    account_id = (event.get("account") or {}).get("accountId") or _account()
    sender = m.get("sender") or {}
    log.info(
        "message.received platform=%s conv=%s from=@%s latency=%ss text=%r",
        m.get("platform"), m.get("conversationId"), sender.get("username"),
        _latency_seconds(m.get("sentAt")), m.get("text"),
    )
    try:
        zernio.send_message(m["conversationId"], account_id, DM_REPLY.format(text=(m.get("text") or "")[:80]))
        log.info("dm reply sent")
    except Exception as e:  # noqa: BLE001
        log.error("dm reply failed: %s", e)


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
    if event_id in _seen_event_ids:
        return Response("duplicate", status_code=200)
    _seen_event_ids.add(event_id)

    kind = event.get("event")
    if kind == "comment.received":
        tasks.add_task(handle_comment, event)
    elif kind == "message.received":
        tasks.add_task(handle_message, event)
    else:
        log.info("event %s id=%s test=%s", kind, event_id, event.get("test", False))
    return Response("ok", status_code=200)
