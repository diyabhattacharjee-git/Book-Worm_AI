from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import assistant, llm
from app.core.errors import not_found
from app.core.ratelimit import rate_limit
from app.db.session import get_db
from app.models.reading import Conversation, ConversationMessage
from app.models.user import User
from app.security.deps import get_current_user, get_current_user_optional

router = APIRouter(prefix="/assistant", tags=["assistant"])

PERSISTENCE_NOTE = ("When you're logged in, conversations are saved to your account so you can continue them; you "
                    "can delete one or all at any time. When logged out, nothing is stored on the server.")
MAX_CONTEXT_IDS = 10
DEFAULT_RETRY_SECONDS = 30


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: int | None = None
    # Only for logged-out users: the context returned by the previous reply.
    context: dict | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Type a message first")
        return v


def _clean_history(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for m in raw[-assistant.HISTORY_MESSAGES:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            out.append({"role": m["role"], "content": m["content"][:assistant.HISTORY_CHARS]})
    return out


def _clean_context(ctx: dict | None) -> dict:
    """Context from the client is untrusted: keep only known keys with safe types."""
    ctx = ctx or {}
    out: dict = {}
    ids = ctx.get("last_book_ids")
    if isinstance(ids, list):
        out["last_book_ids"] = [i for i in ids if isinstance(i, int)][:MAX_CONTEXT_IDS]
    ls = ctx.get("last_search")
    if isinstance(ls, dict) and isinstance(ls.get("text"), str) and isinstance(ls.get("semantic_text"), str):
        allowed = {"text", "semantic_text", "pages_max", "pages_min", "language", "level", "similar_to_book_id",
                   "similar_to_title", "used_only", "sort_by_price", "notes"}
        out["last_search"] = {k: v for k, v in ls.items() if k in allowed}
    return out


def _saved_history(db: Session, conversation_id: int) -> list[dict]:
    rows = list(db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
                           .order_by(ConversationMessage.id.desc()).limit(assistant.HISTORY_MESSAGES)))
    return [assistant.history_entry(m.role, m.content, m.payload) for m in reversed(rows)]


@router.post("/chat", dependencies=[Depends(rate_limit("assistant", 20, 60)), Depends(rate_limit("assistant_day", 300, 86400))])
def chat(body: ChatIn, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    conv = None
    if user:
        if body.conversation_id:
            conv = db.get(Conversation, body.conversation_id)
            if not conv or conv.user_id != user.id:
                raise not_found("Conversation")
        ctx = _clean_context(dict(conv.context or {})) if conv else {}
        history = _saved_history(db, conv.id) if conv else []
    else:
        ctx = _clean_context(body.context)
        history = _clean_history((body.context or {}).get("history"))
    try:
        reply = assistant.respond(db, user, body.message, ctx, history)
    except assistant.AssistantUnavailable as exc:
        # Nothing is saved, so the reader can retry the same message without duplicating it.
        retry = exc.retry_after or DEFAULT_RETRY_SECONDS
        raise HTTPException(status_code=503, detail="I'm sorry, I can't answer just now. Please try again in a moment.",
                            headers={"Retry-After": str(retry)})
    ctx = _clean_context(ctx)
    text = body.message.strip()
    if user and conv is None:
        conv = Conversation(user_id=user.id, title=text[:80], context={})
        db.add(conv)
        db.flush()
    if conv:
        payload = {k: reply[k] for k in ("tool", "routed_by", "source", "payloads", "suggestions", "degraded")}
        db.add(ConversationMessage(conversation_id=conv.id, role="user", content=text))
        db.add(ConversationMessage(conversation_id=conv.id, role="assistant", content=reply["text"], payload=payload))
        conv.context = ctx
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
    else:
        ctx["history"] = [*history, assistant.history_entry("user", text),
                          assistant.history_entry("assistant", reply["text"], reply)][-assistant.HISTORY_MESSAGES:]
    return {"conversation_id": conv.id if conv else None, "reply": reply, "context": None if conv else ctx,
            "persisted": conv is not None}


@router.get("/status")
def status():
    return {"llm": llm.status(), "persistence": PERSISTENCE_NOTE,
            "fallback": "Without an LLM, requests are routed by rules and answered from catalogue, recommendation "
                        "and marketplace services directly."}


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Conversation.id, Conversation.title, Conversation.updated_at, func.count(ConversationMessage.id))
        .outerjoin(ConversationMessage, ConversationMessage.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id).group_by(Conversation.id).order_by(Conversation.updated_at.desc())
    ).all()
    return [{"id": i, "title": t, "updated_at": u, "messages": n} for i, t, u, n in rows]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise not_found("Conversation")
    return {"id": conv.id, "title": conv.title, "messages": [
        {"id": m.id, "role": m.role, "content": m.content, "payload": m.payload, "created_at": m.created_at}
        for m in conv.messages]}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise not_found("Conversation")
    db.delete(conv)
    db.commit()


@router.delete("/conversations", status_code=204)
def clear_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for conv in db.scalars(select(Conversation).where(Conversation.user_id == user.id)):
        db.delete(conv)
    db.commit()
