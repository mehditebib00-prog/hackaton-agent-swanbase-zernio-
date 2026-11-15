# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex) working in this repo.

## Run / stop the service

- Start everything: `uv run python -m concierge.run` (run it in the background; wait for the line `READY`).
  It starts the app on :8000, a cloudflared quick tunnel, re-points the Zernio webhook to the new tunnel URL and sends a test event.
- Stop: `uv run python -m concierge.run --stop` (uvicorn needs a few seconds to shut down).
- Health: `curl localhost:8000/health`; dashboard (localhost only): `http://localhost:8000/dashboard`.
- Logs: `data/app.log`, `data/tunnel.log`.
- Prerequisites on a new machine: `uv`, `cloudflared`, a filled `.env` (see `.env.example` and README). The user fills `.env`; never read or print it.

## Checks before committing

- `uv run pytest -q` (tests never touch the network or the live database; `tests/conftest.py` stubs event logging).
- `uvx ruff check concierge tests --select F,B` and `uvx pyright --pythonpath .venv/bin/python concierge`.

## Rules

- Never print or log keys/tokens; `httpx` INFO logs are silenced in `app.py` because they contain the Telegram token.
- `data/` holds personal data (photos, usernames, contacts); it is git-ignored and must stay out of commits and screenshots.
- Prompts must stay event-agnostic: event facts live in `concierge/event_info.py`.
- Anything shared with Instagram users goes through `guard.clean` (links) and `contacts` (contact details).
- Claude model: `claude-opus-5-5` with structured outputs and server-side fallback (`concierge/llm.py`).
