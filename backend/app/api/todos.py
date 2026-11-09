"""The reader's to-do list."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.core.ratelimit import rate_limit
from app.core.text import strip_control
from app.db.session import get_db
from app.models.reading import ReadingTask
from app.models.user import User
from app.security.deps import get_current_user

router = APIRouter(prefix="/todos", tags=["to-do list"])

TITLE_MAX = 200
NOTES_MAX = 1000
MAX_TASKS_PER_USER = 500
DUPLICATE_MESSAGE = "You already have this task on your list"


def normalized(title: str) -> str:
    return " ".join(title.split()).casefold()[:TITLE_MAX]


def _clean_title(v):
    return " ".join(v.split()) if isinstance(v, str) else v


def _clean_notes(v):
    if not isinstance(v, str):
        return v
    return v.strip() or None


class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    due_date: date | None = None

    _title = field_validator("title", mode="before")(_clean_title)
    _notes = field_validator("notes", mode="before")(_clean_notes)


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    due_date: date | None = None
    completed: bool | None = None

    _title = field_validator("title", mode="before")(_clean_title)
    _notes = field_validator("notes", mode="before")(_clean_notes)


def _out(t: ReadingTask) -> dict:
    return {"id": t.id, "title": t.title, "notes": t.notes, "due_date": t.due_date, "completed": t.completed,
            "completed_at": t.completed_at, "created_at": t.created_at, "updated_at": t.updated_at}


def _own(db: Session, task_id: int, user: User) -> ReadingTask:
    task = db.get(ReadingTask, task_id)
    if not task or task.user_id != user.id:
        raise not_found("Task")
    return task


def _commit_unique(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE_MESSAGE)


@router.get("")
def list_todos(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tasks = db.scalars(select(ReadingTask).where(ReadingTask.user_id == user.id)
                       .order_by(ReadingTask.completed, ReadingTask.created_at.desc(), ReadingTask.id.desc()))
    return [_out(t) for t in tasks]


@router.post("", status_code=201, dependencies=[Depends(rate_limit("todo_create", 120, 3600))])
def create_todo(body: TodoIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count(ReadingTask.id)).where(ReadingTask.user_id == user.id)) or 0
    if count >= MAX_TASKS_PER_USER:
        raise HTTPException(status_code=409, detail="Your list is full. Clear some finished tasks first.")
    task = ReadingTask(user_id=user.id, title=strip_control(body.title, TITLE_MAX), normalized_title=normalized(body.title),
                       notes=strip_control(body.notes, NOTES_MAX), due_date=body.due_date, completed=False)
    db.add(task)
    _commit_unique(db)
    return _out(task)


@router.patch("/{task_id}")
def update_todo(task_id: int, body: TodoUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _own(db, task_id, user)
    data = body.model_dump(exclude_unset=True)
    if data.get("title") is not None:
        task.title = strip_control(data["title"], TITLE_MAX)
        task.normalized_title = normalized(data["title"])
    elif "title" in data:
        raise HTTPException(status_code=422, detail="A task needs a title")
    if "notes" in data:
        task.notes = strip_control(data["notes"], NOTES_MAX)
    if "due_date" in data:
        task.due_date = data["due_date"]
    if data.get("completed") is not None and data["completed"] != task.completed:
        task.completed = data["completed"]
        task.completed_at = datetime.now(timezone.utc) if task.completed else None
    _commit_unique(db)
    return _out(task)


@router.delete("/completed", status_code=204)
def clear_completed(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(delete(ReadingTask).where(ReadingTask.user_id == user.id, ReadingTask.completed.is_(True)))
    db.commit()


@router.delete("/{task_id}", status_code=204)
def delete_todo(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, task_id, user))
    db.commit()
