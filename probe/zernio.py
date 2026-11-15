"""Minimal Zernio REST client for the probe. Never logs the API key."""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://zernio.com/api/v1"


def _client() -> httpx.Client:
    key = os.environ.get("ZERNIO_API_KEY", "")
    if not key:
        raise SystemExit("ZERNIO_API_KEY is missing in .env")
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {key}"},
        timeout=20,
    )


def _check(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        # Response bodies carry error details only, never the key.
        raise RuntimeError(f"{resp.request.method} {resp.request.url.path} -> {resp.status_code}: {resp.text[:500]}")
    return resp.json() if resp.content else {}


def list_accounts(platform: str | None = None) -> list[dict]:
    params = {"platform": platform} if platform else {}
    with _client() as c:
        data = _check(c.get("/accounts", params=params))
    return data.get("accounts", data if isinstance(data, list) else [])


def instagram_account_id() -> str:
    pinned = os.environ.get("ZERNIO_IG_ACCOUNT_ID", "").strip()
    if pinned:
        return pinned
    accounts = list_accounts("instagram")
    if not accounts:
        raise RuntimeError("No Instagram account connected in Zernio")
    return str(accounts[0].get("_id") or accounts[0].get("id"))


def create_webhook(url: str, events: list[str]) -> dict:
    secret = os.environ.get("ZERNIO_WEBHOOK_SECRET", "")
    if not secret:
        raise SystemExit("ZERNIO_WEBHOOK_SECRET is missing in .env")
    body = {"name": "event-concierge-probe", "url": url, "events": events, "secret": secret}
    with _client() as c:
        return _check(c.post("/webhooks/settings", json=body))


def list_webhooks() -> dict:
    with _client() as c:
        return _check(c.get("/webhooks/settings"))


def send_test_webhook(webhook_id: str) -> dict:
    with _client() as c:
        return _check(c.post("/webhooks/test", json={"webhookId": webhook_id}))


def private_reply(post_id: str, comment_id: str, account_id: str, message: str) -> dict:
    with _client() as c:
        return _check(
            c.post(
                f"/inbox/comments/{post_id}/{comment_id}/private-reply",
                json={"accountId": account_id, "message": message},
            )
        )


def public_reply(post_id: str, comment_id: str, account_id: str, message: str) -> dict:
    with _client() as c:
        return _check(
            c.post(
                f"/inbox/comments/{post_id}",
                json={"accountId": account_id, "commentId": comment_id, "message": message},
            )
        )


def upload_media(path: str, content_type: str) -> str:
    """Upload a local file via presigned URL; return its public URL."""
    import pathlib

    with _client() as c:
        presign = _check(
            c.post("/media/presign", json={"filename": pathlib.Path(path).name, "contentType": content_type})
        )
    with open(path, "rb") as f:
        put = httpx.put(presign["uploadUrl"], content=f.read(), headers={"Content-Type": content_type}, timeout=60)
    if put.status_code >= 400:
        raise RuntimeError(f"media upload failed: {put.status_code}")
    return presign["publicUrl"]


def publish_post(content: str, targets: list[dict], media_urls: list[str]) -> dict:
    body = {
        "content": content,
        "publishNow": True,
        "platforms": targets,
        "mediaItems": [{"type": "image", "url": u} for u in media_urls],
    }
    with _client() as c:
        return _check(c.post("/posts", json=body, timeout=120))


def send_message(conversation_id: str, account_id: str, message: str) -> dict:
    with _client() as c:
        return _check(
            c.post(
                f"/inbox/conversations/{conversation_id}/messages",
                json={"accountId": account_id, "message": message},
            )
        )
