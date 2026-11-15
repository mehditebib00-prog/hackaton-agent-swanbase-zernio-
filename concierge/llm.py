"""Claude calls: interview follow-ups, post drafting, comment/DM replies, recap."""

import base64
import logging
from typing import TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv(override=True)  # project .env wins over stale shell vars
log = logging.getLogger("llm")

MODEL = "claude-opus-5-5"
_client = anthropic.Anthropic()
T = TypeVar("T", bound=BaseModel)

EVENT_CONTEXT = (
    "Event: 'Social GTM Agents Hackathon' by swanbase with Zernio, Paris, 15 Nov 2026. "
    "About 30 builders (developers, growth marketers, founders) build in one day an AI agent "
    "that does go-to-market on social media using Zernio's social API/MCP. "
    "You are the event's AI concierge: you interview teams, publish their stories on Instagram, "
    "and answer people in comments and DMs about the projects."
)


def _parse(schema: type[T], system: str, content: list | str, effort: str = "low", max_tokens: int = 4000) -> T:
    resp = _client.beta.messages.parse(
        model=MODEL,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # pyright: ignore[reportCallIssue]  (verified working at runtime)
        output_config={"effort": effort},  # pyright: ignore[reportArgumentType]
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"LLM returned no output (stop_reason={resp.stop_reason})")
    return resp.parsed_output


def _image_block(jpeg: bytes) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()},
    }


# ---------- interview ----------

class FollowUps(BaseModel):
    questions: list[str] = Field(description="2-3 short interview questions")


def follow_up_questions(photo: bytes, note: str) -> list[str]:
    system = (
        EVENT_CONTEXT + "\nThe organizer just met a team and sent a photo plus a one-line note. "
        "Ask 2-3 short, concrete follow-up questions they can answer in one message, to learn: "
        "what the project does and for whom, which AI tools/Zernio features they use, the hardest moment "
        "or a surprising insight. Skip what the note already answers. English, max 15 words each."
    )
    out = _parse(FollowUps, system, [_image_block(photo), {"type": "text", "text": f"Note: {note}"}])
    return out.questions[:3]


class InterviewDraft(BaseModel):
    team: str = Field(description="Team or people names; 'Team <project>' if unknown")
    project: str = Field(description="Project name, short")
    one_liner: str = Field(description="What it does, for whom, max 20 words")
    ai_tools: list[str] = Field(description="AI tools / APIs / Zernio features they use")
    challenge: str = Field(description="Hardest moment or insight, one sentence")
    quote: str = Field(description="A short quote in their voice, faithful to the answers")
    tags: list[str] = Field(description="3-6 lowercase topic tags, e.g. ads, instagram, leads, voice")
    ig_caption: str = Field(description="Instagram caption, see rules")


CAPTION_RULES = (
    "Instagram caption rules: hook first line (no 'Meet team X'), 3 short paragraphs max, "
    "concrete details over hype, at most 2 emojis, then the line "
    "'Comment LINK and our AI concierge will DM you every project from today.' "
    "then 4-6 hashtags including #SocialGTMHackathon #Zernio #swanbase. Max 1200 characters. "
    "Never invent facts that are not in the note or answers."
)


def draft_post(photo: bytes, note: str, qa: str, feedback: str | None = None) -> InterviewDraft:
    system = EVENT_CONTEXT + "\nTurn this interview into a structured record and an Instagram post.\n" + CAPTION_RULES
    text = f"Organizer note: {note}\n\nFollow-up Q&A:\n{qa}"
    if feedback:
        text += f"\n\nRewrite request from the organizer: {feedback}"
    return _parse(InterviewDraft, system, [_image_block(photo), {"type": "text", "text": text}], effort="medium")


# ---------- engagement ----------

GROUNDING = (
    "GROUNDING RULES: State only facts found in the KNOWLEDGE BASE or EVENT INFO below. Never invent people, "
    "projects, dates, prices or links. If something is not covered, say you don't know and point to the closest "
    "thing you do know. Use only URLs that appear verbatim below; any other URL will be deleted before sending. "
    "Never repeat a URL listed under LINKS ALREADY SENT; refer to it by name instead."
)

CTA_RULES = (
    "NEXT STEP: when the person shows interest in building, startups, growth, events or 'what's next', offer the "
    "highest-priority next step from EVENT INFO (one at a time, with its link, at most once per conversation). "
    "Mention a deadline only if EVENT INFO states it."
)


def _context_block(kb: str, sent_links: set[str]) -> str:
    from concierge import event_info

    sent = "\n".join(sorted(sent_links)) or "(none)"
    return f"\n\nKNOWLEDGE BASE:\n{kb}\n\nEVENT INFO:\n{event_info.event_block()}\n\nLINKS ALREADY SENT:\n{sent}"


class CommentReply(BaseModel):
    wants_dm: bool = Field(description="True unless the comment is spam, hostile or from a bot")
    public_reply: str = Field(description="Short friendly public reply, max 20 words, mentions to check DMs if wants_dm")
    dm: str = Field(description="Personal DM, see rules")
    interests: list[str] = Field(description="1-3 lowercase singular interest tags inferred from the comment")


def comment_reply(comment: str, username: str | None, post_caption: str | None, kb: str, sent_links: set[str] | None = None) -> CommentReply:
    system = (
        EVENT_CONTEXT + "\nSomeone commented on one of our Instagram posts. Write a public reply and a private DM. "
        "DM rules: greet by name if known; react to what they actually wrote; recommend the 2 most relevant "
        "projects from the knowledge base with one line each (why it matches them) and their post link; "
        "invite them to reply with a question about any project or topic. Plain text, max 600 characters, "
        "no markdown. If the knowledge base is empty, explain we are interviewing teams live today and ask what "
        "they are curious about.\n" + GROUNDING + "\n" + CTA_RULES + _context_block(kb, sent_links or set())
    )
    text = f"Post caption: {post_caption or '(unknown)'}\nCommenter: @{username or 'unknown'}\nComment: {comment}"
    return _parse(CommentReply, system, text)


class DmAnswer(BaseModel):
    reply: str = Field(description="Answer, plain text, max 700 characters")
    interests: list[str] = Field(description="1-3 lowercase singular interest tags inferred from the message")
    wants_human: bool = Field(description="True if the person asks to talk to a human / the organizers / a real person")


def dm_answer(history: list[dict], message: str, username: str | None, kb: str, sent_links: set[str] | None = None) -> DmAnswer:
    system = (
        EVENT_CONTEXT + "\nYou are chatting in Instagram DMs about the hackathon projects (who built what, which "
        "tools) and swanbase's next steps. Be warm and concise, plain text, no markdown, don't restate what you "
        "already said earlier in the conversation. If they ask for a human, set wants_human and tell them an "
        "organizer will reply here soon.\n" + GROUNDING + "\n" + CTA_RULES + _context_block(kb, sent_links or set())
    )
    convo = "\n".join(f"{m['role']}: {m['text']}" for m in history)
    text = f"Conversation so far:\n{convo or '(none)'}\n\nNew message from @{username or 'unknown'}: {message}"
    return _parse(DmAnswer, system, text)


# ---------- recap ----------

class Recap(BaseModel):
    ig_caption: str


def recap_post(kb: str, stats: str) -> str:
    system = (
        EVENT_CONTEXT + "\nWrite the end-of-day recap Instagram caption: what this room of builders made today, "
        "grouped by theme, naming each team in one line, plus 1 striking number from the stats. "
        "End with 'Comment LINK and our AI concierge will DM you the full list.' and hashtags "
        "#SocialGTMHackathon #Zernio #swanbase #AIagents. Max 2000 characters, at most 3 emojis.\n\n"
        "KNOWLEDGE BASE:\n" + kb
    )
    return _parse(Recap, system, f"Stats: {stats}", effort="medium").ig_caption
