"""One command to run everything: app + public tunnel + webhook re-pointing.

  uv run python -m concierge.run          # start (Ctrl-C stops both processes)
  uv run python -m concierge.run --stop   # stop anything left running

Steps: start uvicorn on :8000 -> start a cloudflared quick tunnel -> wait until the public
URL answers /health -> point the Zernio webhook at it (create one if none) -> send a test
event and confirm it arrived. Prints ids and URLs only, never keys.
Logs: data/app.log, data/tunnel.log.
"""

import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PORT = 8000
WEBHOOK_PATH = "/webhooks/zernio"
EVENTS = ["comment.received", "message.received", "post.published", "post.failed"]
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def stop() -> None:
    for pattern in (f"concierge.app:app --port {PORT}", f"cloudflared tunnel --url http://localhost:{PORT}"):
        subprocess.run(["pkill", "-f", pattern], check=False)
    print("stopped app and tunnel (if they were running)")


def _wait(check, what: str, timeout: float, every: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check()
        if result:
            return result
        time.sleep(every)
    raise SystemExit(f"timed out after {timeout:.0f}s waiting for {what}")


def _healthy(url: str) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=5).json().get("ok") is True
    except (httpx.HTTPError, ValueError):
        return False


def _point_webhook(public_url: str) -> str:
    from concierge import zernio

    target = public_url + WEBHOOK_PATH
    hooks = zernio.list_webhooks()
    hooks = hooks.get("webhooks", hooks if isinstance(hooks, list) else [])
    ours = [h for h in hooks if str(h.get("url", "")).endswith(WEBHOOK_PATH)]
    if ours:
        hook_id = ours[0]["_id"]
        zernio.update_webhook_url(hook_id, target)
        for extra in ours[1:]:  # stale duplicates pointing at dead tunnels
            zernio.delete_webhook(extra["_id"])
    else:
        hook_id = zernio.create_webhook(target, EVENTS).get("webhook", {}).get("_id")
    zernio.send_test_webhook(hook_id)
    return hook_id


def start() -> None:
    DATA.mkdir(exist_ok=True)
    stop()
    time.sleep(1)
    app_log = open(DATA / "app.log", "w")
    tunnel_log_path = DATA / "tunnel.log"
    tunnel_log = open(tunnel_log_path, "w")
    app = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "concierge.app:app", "--port", str(PORT)],
        cwd=ROOT, stdout=app_log, stderr=subprocess.STDOUT,
    )
    tunnel = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{PORT}"],
        cwd=ROOT, stdout=tunnel_log, stderr=subprocess.STDOUT,
    )

    def shutdown(*_):
        for p in (tunnel, app):
            p.terminate()
        print("\nstopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    _wait(lambda: _healthy(f"http://localhost:{PORT}"), "the local app", 60)
    print(f"app up: http://localhost:{PORT}  (dashboard: http://localhost:{PORT}/dashboard)")
    public = _wait(lambda: (m := TUNNEL_RE.search(tunnel_log_path.read_text())) and m.group(0), "the tunnel URL", 60)
    _wait(lambda: _healthy(public), "the public URL to answer (DNS can take ~1 min)", 180, every=5)
    print(f"tunnel up: {public}")
    hook_id = _point_webhook(public)
    time.sleep(2)
    got = "event webhook.test" in (DATA / "app.log").read_text()
    print(f"webhook {hook_id} -> {public}{WEBHOOK_PATH} | test event received: {got}")
    bot_ok = _wait(lambda: "telegram bot polling" in (DATA / "app.log").read_text(), "the Telegram bot", 90)
    print(f"telegram bot polling: {bot_ok}")
    print("READY. Ctrl-C (or `uv run python -m concierge.run --stop`) to stop.")
    while True:
        if app.poll() is not None or tunnel.poll() is not None:
            which = "app" if app.poll() is not None else "tunnel"
            print(f"{which} exited unexpectedly; see data/{'app' if which == 'app' else 'tunnel'}.log")
            shutdown()
        time.sleep(5)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # progress lines show up even when run in the background
        sys.stdout.reconfigure(line_buffering=True)  # pyright: ignore[reportAttributeAccessIssue]
    stop() if "--stop" in sys.argv else start()
