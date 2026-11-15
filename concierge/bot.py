"""Telegram interview bot (owner only).

Flow: photo (+ caption note) -> follow-up questions -> owner answers in one message
-> Claude drafts the Instagram post -> Publish / Rewrite / Drop buttons -> Zernio publishes.
Commands: /start (claim ownership or request access), /allow <id> (owner), /recap, /stats,
/export, /resume <ig username>, /cancel.
"""

import asyncio
import logging
import os
import time

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from concierge import llm, media, store, zernio

log = logging.getLogger("bot")
OWNER_KEY = "telegram_owner_id"
BUTTONS = InlineKeyboardMarkup(
    [[
        InlineKeyboardButton("✅ Publish", callback_data="publish"),
        InlineKeyboardButton("✏️ Rewrite", callback_data="rewrite"),
        InlineKeyboardButton("🗑 Drop", callback_data="drop"),
    ]]
)


def _owner_id() -> int | None:
    v = os.environ.get("TELEGRAM_OWNER_ID") or store.get_setting(OWNER_KEY)
    return int(v) if v else None


def _is_owner(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == _owner_id()


def _is_member(update: Update) -> bool:
    """Owner or a teammate the owner allowed with /allow."""
    u = update.effective_user
    return u is not None and (u.id == _owner_id() or u.id in store.allowed_ids())


def notify_owner(text: str) -> None:
    """Fire-and-forget message to the owner, usable from any thread."""
    owner = _owner_id()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not owner or not token:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": owner, "text": text[:4000], "disable_web_page_preview": True},
            timeout=10,
        )
    except httpx.HTTPError as e:
        log.warning("notify_owner failed: %s", type(e).__name__)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return
    if _owner_id() is None:
        store.set_setting(OWNER_KEY, str(user.id))
        await update.message.reply_text("You are now the owner of this concierge. Send a team photo with a one-line note to start an interview.")
    elif _is_member(update):
        await update.message.reply_text("Ready. Send a team photo with a one-line note (as the photo caption).")
    else:
        await update.message.reply_text("Access requested. The owner has been notified.")
        notify_owner(f"🔐 {user.full_name} (@{user.username or '-'}) asks for access.\nApprove: /allow {user.id}")


async def allow(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update) or update.message is None:
        return
    try:
        uid = int((ctx.args or [""])[0])
    except ValueError:
        await update.message.reply_text("Usage: /allow <telegram user id>")
        return
    store.allow_id(uid)
    await update.message.reply_text(f"Allowed {uid}. They can now interview and publish.")
    await ctx.bot.send_message(uid, "You're in ✅ Send a team photo with a one-line note (as the caption) to start an interview.")


async def resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_member(update) or update.message is None:
        return
    username = (ctx.args or [""])[0].lstrip("@")
    if not username:
        await update.message.reply_text("Usage: /resume <instagram username>")
        return
    store.set_handoff(username, None, False)
    await update.message.reply_text(f"Auto-replies resumed for @{username}.")


async def export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_member(update) or update.message is None:
        return
    if update.effective_chat is None or update.effective_chat.type != "private":
        await update.message.reply_text("Use /export in a private chat with the bot.")
        return
    for name, data in store.export_csv().items():
        await update.message.reply_document(document=data, filename=name)


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_member(update) or update.message is None:
        return
    ctx.chat_data.clear()
    await update.message.reply_text("Cleared. Send a new photo whenever you're ready.")


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not _is_member(update) or msg is None or not msg.photo:
        return
    f = await msg.photo[-1].get_file()
    raw = bytes(await f.download_as_bytearray())
    photo = await asyncio.to_thread(media.prepare_for_instagram, raw)
    ctx.chat_data.clear()
    ctx.chat_data.update(photo=photo, note=msg.caption or "", stage="need_note" if not msg.caption else "asking")
    if not msg.caption:
        await msg.reply_text("Got the photo. One line about this team / project?")
        return
    await _ask_followups(msg, ctx)


async def _ask_followups(msg, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await msg.chat.send_action("typing")
    try:
        qs = await asyncio.to_thread(llm.follow_up_questions, ctx.chat_data["photo"], ctx.chat_data["note"])
    except Exception as e:  # noqa: BLE001
        log.error("follow_up_questions failed: %s", e)
        qs = ["What does it do, and for whom?", "Which AI tools / Zernio features do you use?", "Hardest moment so far?"]
    ctx.chat_data.update(stage="answers", questions=qs)
    await msg.reply_text("Ask them:\n\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(qs)) + "\n\nThen send me all their answers in one message.")


async def _draft(msg, ctx: ContextTypes.DEFAULT_TYPE, feedback: str | None = None) -> None:
    await msg.chat.send_action("typing")
    d = ctx.chat_data
    qa = "\n".join(f"Q{i+1}: {q}" for i, q in enumerate(d.get("questions", []))) + f"\nAnswers: {d.get('answers', '')}"
    try:
        draft = await asyncio.to_thread(llm.draft_post, d["photo"], d["note"], qa, feedback)
    except Exception as e:  # noqa: BLE001
        log.error("draft_post failed: %s", e)
        await msg.reply_text("Drafting failed, try ✏️ Rewrite or /cancel.")
        return
    d.update(stage="review", draft=draft.model_dump())
    await msg.reply_photo(d["photo"], caption=f"DRAFT · {draft.team} — {draft.project}")
    await msg.reply_text(draft.ig_caption, reply_markup=BUTTONS)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not _is_member(update) or msg is None or msg.text is None:
        return
    stage = ctx.chat_data.get("stage")
    if stage == "need_note":
        ctx.chat_data["note"] = msg.text
        await _ask_followups(msg, ctx)
    elif stage == "answers":
        ctx.chat_data["answers"] = msg.text
        await _draft(msg, ctx)
    elif stage == "rewrite":
        await _draft(msg, ctx, feedback=msg.text)
    else:
        await msg.reply_text("Send a team photo (with a one-line note as caption) to start an interview. /recap /stats")


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not _is_member(update):
        return
    await q.answer()
    d = ctx.chat_data
    if d.get("stage") not in ("review", "recap_review"):
        await q.edit_message_reply_markup(None)
        return
    if q.data == "drop":
        d.clear()
        await q.edit_message_reply_markup(None)
        await q.message.reply_text("Dropped.")
    elif q.data == "rewrite":
        d["stage"] = "rewrite" if d.get("stage") == "review" else "recap_rewrite"
        await q.message.reply_text("What should change? (e.g. 'shorter', 'more about the voice agent')")
    elif q.data == "publish":
        await q.edit_message_reply_markup(None)
        await q.message.reply_text("Publishing to Instagram via Zernio…")
        await _publish(q.message, ctx)


async def _publish(msg, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    d = ctx.chat_data
    is_recap = d.get("stage") == "recap_review"
    caption = d["recap_caption"] if is_recap else d["draft"]["ig_caption"]
    path = store.PHOTO_DIR / f"{'recap' if is_recap else 'team'}_{int(time.time())}.jpg"
    path.write_bytes(d["photo"])
    interview_id = None if is_recap else store.add_interview(d["draft"], str(path), caption)
    try:
        post_id, url = await asyncio.to_thread(_upload_and_post, str(path), caption)
    except Exception as e:  # noqa: BLE001
        log.error("publish failed: %s", e)
        await msg.reply_text(f"Publish failed: {str(e)[:300]}")
        return
    if interview_id is not None:
        store.mark_published(interview_id, post_id, url, caption)
    d.clear()
    await msg.reply_text(f"Live ✅ {url or post_id}\nComments and DMs on it are now handled by the concierge.")


def _upload_and_post(path: str, caption: str) -> tuple[str, str | None]:
    public_url = zernio.upload_media(path, "image/jpeg")
    account_id = zernio.instagram_account_id()
    res = zernio.publish_post(caption, [{"platform": "instagram", "accountId": account_id}], [public_url])
    post = res.get("post", res)
    post_id = post.get("_id", "")
    # Instagram finishes processing asynchronously; poll briefly for the permalink.
    for _ in range(12):
        for p in post.get("platforms", []):
            if p.get("platformPostUrl"):
                return post_id, p["platformPostUrl"]
            if p.get("status") == "failed":
                raise RuntimeError(p.get("errorMessage") or "Instagram publish failed")
        time.sleep(5)
        post = zernio.get_post(post_id)
    return post_id, None


async def recap(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not _is_member(update) or msg is None:
        return
    items = store.published_interviews()
    if not items:
        await msg.reply_text("No published interviews yet.")
        return
    await msg.chat.send_action("typing")
    leads = store.leads()
    stats = f"{len(items)} teams interviewed, {len(leads)} people chatted with the concierge"
    caption = await asyncio.to_thread(llm.recap_post, store.knowledge_base(), stats)
    photo = await asyncio.to_thread(media.collage, [i["photo_path"] for i in items])
    ctx.chat_data.clear()
    ctx.chat_data.update(stage="recap_review", photo=photo, recap_caption=caption)
    await msg.reply_photo(photo, caption="DRAFT · recap")
    await msg.reply_text(caption, reply_markup=BUTTONS)


async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not _is_member(update) or msg is None:
        return
    items, ls = store.published_interviews(), store.leads()
    top = "\n".join(f"• @{lead['username'] or '?'} — {', '.join(lead['interests'])} ({lead['touches']}x)" for lead in ls[:10])
    await msg.reply_text(f"Teams published: {len(items)}\nPeople engaged: {len(ls)}\n{top}")


async def on_recap_rewrite(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text when a recap rewrite was requested. Returns True if handled."""
    msg = update.message
    if ctx.chat_data.get("stage") != "recap_rewrite" or msg is None or msg.text is None:
        return False
    stats_line = f"{len(store.published_interviews())} teams interviewed, {len(store.leads())} people engaged. Rewrite request: {msg.text}"
    caption = await asyncio.to_thread(llm.recap_post, store.knowledge_base(), stats_line)
    ctx.chat_data.update(stage="recap_review", recap_caption=caption)
    await msg.reply_text(caption, reply_markup=BUTTONS)
    return True


async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_member(update):
        return
    if await on_recap_rewrite(update, ctx):
        return
    await on_text(update, ctx)


def build_application() -> Application:
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("recap", recap))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("export", export))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(CallbackQueryHandler(on_button))
    return app
