from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
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


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: int | None = None
    # Only for logged-out users: the context returned by the previous reply.
    context: dict | None = None


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


@router.post("/chat", dependencies=[Depends(rate_limit("assistant", 30, 60))])
def chat(body: ChatIn, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    conv = None
    if user:
        if body.conversation_id:
            conv = db.get(Conversation, body.conversation_id)
            if not conv or conv.user_id != user.id:
                raise not_found("Conversation")
        else:
            conv = Conversation(user_id=user.id, title=body.message.strip()[:80], context={})
            db.add(conv)
            db.flush()
        ctx = _clean_context(dict(conv.context or {}))
    else:
        ctx = _clean_context(body.context)
    reply = assistant.respond(db, user, body.message, ctx)
    ctx = _clean_context(ctx)
    if conv:
        db.add(ConversationMessage(conversation_id=conv.id, role="user", content=body.message.strip()))
        db.add(ConversationMessage(conversation_id=conv.id, role="assistant", content=reply["text"],
                                   payload={k: reply[k] for k in ("tool", "routed_by", "source", "payloads", "suggestions")}))
        conv.context = ctx
        db.commit()
    return {"conversation_id": conv.id if conv else None, "reply": reply, "context": None if conv else ctx,
            "persisted": conv is not None}


@router.get("/status")
def status():
    return {"llm": llm.status(), "persistence": PERSISTENCE_NOTE,
            "fallback": "Without an LLM, requests are routed by rules and answered from catalogue, recommendation "
                        "and marketplace services directly."}


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()))
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at, "messages": len(c.messages)} for c in rows]


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
