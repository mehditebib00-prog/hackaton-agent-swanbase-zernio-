"""Setup helper. Prints ids and statuses only, never keys or secrets.

  uv run python -m probe.setup gen-secret          # append a webhook secret to .env if missing
  uv run python -m probe.setup accounts            # list connected accounts
  uv run python -m probe.setup register <https-url> # create webhook -> <url>/webhooks/zernio
  uv run python -m probe.setup webhooks            # list webhooks
  uv run python -m probe.setup test <webhook-id>   # send a webhook.test event
"""

import os
import secrets
import sys
from pathlib import Path

EVENTS = ["comment.received", "message.received", "post.published", "post.failed"]
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def gen_secret() -> None:
    from dotenv import dotenv_values

    values = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    if values.get("ZERNIO_WEBHOOK_SECRET"):
        print("ZERNIO_WEBHOOK_SECRET already set in .env; left unchanged.")
        return
    with ENV_PATH.open("a") as f:
        f.write(f"\nZERNIO_WEBHOOK_SECRET={secrets.token_hex(32)}\n")
    print("Wrote a new ZERNIO_WEBHOOK_SECRET to .env (value not shown).")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "gen-secret":
        gen_secret()
        return

    from probe import zernio

    if cmd == "accounts":
        for a in zernio.list_accounts():
            print(a.get("_id") or a.get("id"), a.get("platform"), a.get("username") or a.get("displayName"), a.get("status", ""))
    elif cmd == "register":
        base = args[0].rstrip("/")
        res = zernio.create_webhook(f"{base}/webhooks/zernio", EVENTS)
        w = res.get("webhook", res)
        print("webhook id:", w.get("_id"), "active:", w.get("isActive"), "events:", w.get("events"))
    elif cmd == "webhooks":
        res = zernio.list_webhooks()
        for w in res.get("webhooks", res if isinstance(res, list) else []):
            print(w.get("_id"), w.get("url"), w.get("isActive"), w.get("events"))
    elif cmd == "test":
        print(zernio.send_test_webhook(args[0]))
    else:
        print(__doc__)


if __name__ == "__main__":
    os.chdir(ENV_PATH.parent)
    main()
