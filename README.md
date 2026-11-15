# Social GTM Concierge

An AI concierge that runs social-media go-to-market for an event, built on the [Zernio](https://zernio.com) social API and [Claude](https://www.anthropic.com) for the **Social GTM Agents Hackathon** (swanbase × Zernio, Paris, 15 Nov 2026).

The organizer walks around the room, sends a team photo to a Telegram bot and relays a few questions. The concierge turns each interview into an Instagram post, publishes it through Zernio, then answers everyone who comments or DMs: it recommends the most relevant projects, answers questions from the interviews, introduces people to teams and points them to the organizer's next event.

中文说明见 [README_zh.md](README_zh.md).

## How it works

```
Telegram (organizer) ─▶ bot.py ─▶ Claude: adaptive interview + draft ─▶ ✅ Publish ─▶ Zernio ─▶ Instagram
                                                                                   │
Instagram comment / DM ─▶ Zernio webhook ─▶ app.py ─▶ Claude (reads knowledge base) ┴─▶ Zernio private reply / DM
                                                    └─▶ guard (link whitelist) · intros · Telegram alerts · dashboard
```

1. **Interview (Telegram).** Send a team photo with a one-line caption. Claude asks one question at a time (up to 5, `/done` to stop early) in a configurable style, then asks how people may contact the team and whether that is public.
2. **Draft and publish.** Claude writes the caption and a structured record. Review it with ✅ Publish / ✏️ Rewrite / 🗑 Drop; Publish posts to Instagram through Zernio.
3. **Engage (Instagram).** A comment triggers a public reply plus a personal DM recommending the two most relevant projects. The DM thread continues with answers grounded in the published interviews; the conversation history is read from the Zernio inbox.
4. **Convert.** People get the organizer's next step (configured CTAs that expire on their own). Public team contacts are shared verbatim from the database; private teams get an intro request, sent to the organizer on Telegram.
5. **Watch.** A local live dashboard shows teams, activity, interests and the comment → DM latency.

## Guardrails

- **Grounding:** answers come only from published interviews and `concierge/event_info.py`; structured outputs for every Claude call.
- **Link whitelist:** any URL that is not a published post or a configured CTA is removed in code before sending; each link is sent at most once per person.
- **Contacts:** a contact is stored and shared only if it contains a real email, link, @handle or phone number; a requester's contact is saved only if they actually typed it.
- **Loop guard:** repeated messages and bot-marked messages (`[echo]`, `auto-reply:` …) are not answered.
- **Limits:** 30 automatic replies per person per day; "talk to a human" pauses the bot for that person (`/resume` hands back).
- **Webhooks:** HMAC signature check and event de-duplication.
- **Privacy:** the dashboard only answers on localhost; it shortens usernames and never shows contact details. Telegram access is owner + allow-listed teammates.

## Requirements

- macOS or Linux with [uv](https://docs.astral.sh/uv/) (it installs the pinned Python) and [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) (`brew install cloudflared`)
- A Zernio account with an Instagram **Business or Creator** account connected (Instagram Login is enough), and a Zernio API key
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An Anthropic API key

## Setup

```bash
git clone https://github.com/mehditebib00-prog/hackaton-agent-swanbase-zernio-.git
cd hackaton-agent-swanbase-zernio-
uv sync
cp .env.example .env          # then fill in the values below
uv run python -m probe.setup gen-secret   # writes ZERNIO_WEBHOOK_SECRET into .env
```

| Variable | Required | Description |
|---|---|---|
| `ZERNIO_API_KEY` | yes | Zernio API key |
| `ZERNIO_WEBHOOK_SECRET` | yes | Random string Zernio signs webhooks with (`gen-secret` creates it) |
| `ZERNIO_IG_ACCOUNT_ID` | no | Pin the Instagram account; defaults to the first connected one |
| `TELEGRAM_BOT_TOKEN` | yes | Token from @BotFather |
| `TELEGRAM_OWNER_ID` | no | Fix the owner; otherwise the first `/start` becomes owner |
| `ANTHROPIC_API_KEY` | yes | Claude API key |

`.env` values override variables already set in your shell. Never commit `.env`.

For another event, edit `EVENT`, `CTAS` and `STYLE_PRESETS` in `concierge/event_info.py`; no other code changes are needed.

## Run

```bash
uv run python -m concierge.run          # app + tunnel + webhook, one command (Ctrl-C to stop)
uv run python -m concierge.run --stop   # stop anything left running
```

It starts the server on `:8000`, opens a cloudflared tunnel, waits until the public URL answers, points the Zernio webhook at it (creating it if needed), sends a test event and waits for the Telegram bot. Quick tunnel URLs change on every start; the script re-points the webhook each time. Logs go to `data/app.log` and `data/tunnel.log`.

Dashboard: <http://localhost:8000/dashboard> (this computer only).

## Telegram commands

| Command | Who | What |
|---|---|---|
| `/start` | anyone | First user becomes owner; others request access |
| `/allow <id>` | owner | Let a teammate interview and publish |
| *(photo + caption)* | members | Start an interview |
| `/done` | members | Stop questions early and draft |
| `/style [preset or text]` | members | Interview style: journalist, casual, investor, storyteller or your own |
| `/contact [id] [contact\|none]` | members | List teams or set/clear a team's public contact |
| `/recap` | members | Collage + end-of-day recap post |
| `/stats` · `/export` | members | Engagement summary · CSV of interviews, leads, intros (private chat only) |
| `/resume <ig username>` | members | Hand a conversation back to the bot |
| `/cancel` | members | Clear the current interview |

## Project layout

```
concierge/
  run.py          One-command start/stop: app + tunnel + webhook
  app.py          FastAPI: Zernio webhook handlers, guards, intros; starts the Telegram bot
  bot.py          Telegram interview bot and commands
  llm.py          Claude calls (structured outputs): interview, drafting, comment/DM replies, recap
  event_info.py   Event config, CTAs, interview styles (edit per event)
  guard.py        Link whitelist; contacts.py: contact extraction
  store.py        SQLite: interviews, leads, DM history, intros, events
  dashboard.py/.html  Local-only live dashboard
  media.py        Instagram image prep and recap collage
  zernio.py       Zernio REST client
probe/            Setup CLI: webhooks, accounts, webhook secret
tests/            pytest suite (no network, no live database writes)
```

## Data

Runtime data stays in `data/` (git-ignored): the SQLite database, team photos and logs. It contains people's photos, usernames and contact details: do not share it, and delete it to reset the event.

## Tests

```bash
uv run pytest
```

## Built with

Zernio (social API: publishing, comment webhooks, private replies, DMs, inbox) · Claude Opus 5.5 · FastAPI · python-telegram-bot · SQLite · cloudflared
