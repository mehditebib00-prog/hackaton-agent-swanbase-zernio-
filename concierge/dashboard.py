"""Live dashboard for the demo screen. Local-only: requests that came through the public
tunnel (Cloudflare headers) or from another machine are refused. Usernames are shortened
and contact details are never sent to the page."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from concierge import event_info, store

router = APIRouter()
PAGE = Path(__file__).with_name("dashboard.html")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _local_only(request: Request) -> None:
    proxied = any(h.startswith("cf-") or h in ("x-forwarded-for", "x-real-ip") for h in request.headers)
    host = request.client.host if request.client else ""
    if proxied or host not in LOOPBACK:
        raise HTTPException(status_code=404)


def _mask(username: str | None) -> str:
    if not username:
        return "someone"
    u = username.lstrip("@")
    return "@" + (u[:4] + "…" if len(u) > 5 else u)


@router.get("/dashboard", response_class=HTMLResponse)
def page(request: Request) -> HTMLResponse:
    _local_only(request)
    return HTMLResponse(PAGE.read_text())


@router.get("/dashboard/data")
def data(request: Request) -> dict:
    _local_only(request)
    d = store.dashboard_data()
    for e in d["feed"]:
        e["who"] = _mask(e["who"]) if e["who"] else None
    d["event"] = {k: event_info.EVENT[k] for k in ("name", "organizer", "partners", "date", "place")}
    return d


@router.get("/dashboard/photo/{interview_id}")
def photo(interview_id: int, request: Request) -> FileResponse:
    _local_only(request)
    iv = store.interview(interview_id)
    path = Path(iv["photo_path"]) if iv and iv.get("photo_path") else None
    # only serve files inside our photo directory
    if not path or not path.resolve().is_relative_to(store.PHOTO_DIR.resolve()) or not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg")
