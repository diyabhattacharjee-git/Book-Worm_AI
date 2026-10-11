from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.db.base import as_utc
from app.db.session import get_db
from app.models.book import Book
from app.models.reading import (
    BookshelfEntry,
    ReadingGoal,
    ReadingList,
    ReadingListItem,
    ReadingPlan,
)
from app.models.social import INTERACTION_WEIGHTS, UserBookInteraction
from app.models.user import User
from app.repositories.books import get_books, summaries
from app.schemas.books import BookshelfIn, BookshelfUpdateIn
from app.security.deps import get_current_user
from app.services import reading_plan as rp

router = APIRouter(tags=["reading"])


# ------------------------------------------------------------------ bookshelf
def _entry_out(e: BookshelfEntry, summary) -> dict:
    pages = e.book.page_count
    return {
        "id": e.id, "book": summary.model_dump(), "status": e.status, "pages_read": e.pages_read,
        "total_pages": pages,
        # Percentage only when the page count is actually known.
        "percent": round(100 * min(e.pages_read, pages) / pages, 1) if pages else None,
        "started_on": e.started_on, "finished_on": e.finished_on, "notes": e.notes,
        "updated_at": e.updated_at,
    }


def _sync_shelf_signal(db: Session, user_id: int, book_id: int, status: str | None) -> None:
    db.execute(delete(UserBookInteraction).where(
        UserBookInteraction.user_id == user_id, UserBookInteraction.book_id == book_id,
        UserBookInteraction.type.like("shelf_%")))
    if status:
        typ = {"want_to_read": "shelf_want", "reading": "shelf_reading", "read": "shelf_read",
               "abandoned": "shelf_abandoned"}[status]
        db.add(UserBookInteraction(user_id=user_id, book_id=book_id, type=typ, weight=INTERACTION_WEIGHTS[typ]))


@router.get("/bookshelf")
def get_bookshelf(status: Literal["want_to_read", "reading", "read", "abandoned"] | None = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(BookshelfEntry).where(BookshelfEntry.user_id == user.id)
    if status:
        q = q.where(BookshelfEntry.status == status)
    entries = list(db.scalars(q.order_by(BookshelfEntry.updated_at.desc())).unique())
    sums = {s.id: s for s in summaries(db, [e.book for e in entries])}
    counts = dict(db.execute(select(BookshelfEntry.status, func.count(BookshelfEntry.id))
                             .where(BookshelfEntry.user_id == user.id).group_by(BookshelfEntry.status)).all())
    return {"items": [_entry_out(e, sums[e.book_id]) for e in entries], "counts": counts}


@router.post("/bookshelf", status_code=201)
def add_to_shelf(body: BookshelfIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    book = db.get(Book, body.book_id)
    if not book:
        raise not_found("Book")
    entry = db.scalar(select(BookshelfEntry).where(BookshelfEntry.user_id == user.id, BookshelfEntry.book_id == book.id))
    today = datetime.now(timezone.utc).date()
    if entry:
        entry.status = body.status
    else:
        entry = BookshelfEntry(user_id=user.id, book_id=book.id, status=body.status)
        db.add(entry)
    if body.status == "reading" and not entry.started_on:
        entry.started_on = today
    if body.status == "read":
        entry.finished_on = entry.finished_on or today
        if book.page_count:
            entry.pages_read = book.page_count
    _sync_shelf_signal(db, user.id, book.id, body.status)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This book is already on your shelf")
    return _entry_out(entry, summaries(db, [book])[0])


def _own_entry(db: Session, entry_id: int, user: User) -> BookshelfEntry:
    entry = db.get(BookshelfEntry, entry_id)
    if not entry or entry.user_id != user.id:
        raise not_found("Bookshelf entry")
    return entry


@router.patch("/bookshelf/{entry_id}")
def update_shelf(entry_id: int, body: BookshelfUpdateIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    entry = _own_entry(db, entry_id, user)
    data = body.model_dump(exclude_unset=True)
    today = datetime.now(timezone.utc).date()
    if "pages_read" in data and data["pages_read"] is not None:
        pages = entry.book.page_count
        if pages and data["pages_read"] > pages:
            raise HTTPException(status_code=422, detail=f"This book has {pages} pages")
        entry.pages_read = data["pages_read"]
        if entry.status == "want_to_read" and entry.pages_read > 0:
            data.setdefault("status", "reading")
    if data.get("status"):
        entry.status = data["status"]
        if entry.status == "reading" and not entry.started_on:
            entry.started_on = today
        if entry.status == "read":
            entry.finished_on = entry.finished_on or today
            if entry.book.page_count:
                entry.pages_read = entry.book.page_count
        _sync_shelf_signal(db, user.id, entry.book_id, entry.status)
    for k in ("started_on", "finished_on", "notes"):
        if k in data:
            setattr(entry, k, data[k])
    if entry.started_on and entry.finished_on and entry.finished_on < entry.started_on:
        raise HTTPException(status_code=422, detail="Finish date can't be before the start date")
    db.commit()
    return _entry_out(entry, summaries(db, [entry.book])[0])


@router.delete("/bookshelf/{entry_id}", status_code=204)
def remove_from_shelf(entry_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = _own_entry(db, entry_id, user)
    _sync_shelf_signal(db, user.id, entry.book_id, None)
    db.delete(entry)
    db.commit()


# ------------------------------------------------------------- custom lists
class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)


class ListItemIn(BaseModel):
    book_id: int


def _list_out(db: Session, rl: ReadingList) -> dict:
    books = [i.book for i in rl.items]
    sums = summaries(db, books)
    return {"id": rl.id, "name": rl.name, "description": rl.description, "created_at": rl.created_at,
            "books": [s.model_dump() for s in sums]}


def _own_list(db: Session, list_id: int, user: User) -> ReadingList:
    rl = db.get(ReadingList, list_id)
    if not rl or rl.user_id != user.id:
        raise not_found("List")
    return rl


@router.get("/reading-lists")
def get_lists(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lists = db.scalars(select(ReadingList).where(ReadingList.user_id == user.id).order_by(ReadingList.created_at))
    return [_list_out(db, rl) for rl in lists]


@router.post("/reading-lists", status_code=201)
def create_list(body: ListIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rl = ReadingList(user_id=user.id, name=body.name.strip(), description=body.description)
    db.add(rl)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a list with that name")
    return _list_out(db, rl)


@router.patch("/reading-lists/{list_id}")
def rename_list(list_id: int, body: ListIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rl = _own_list(db, list_id, user)
    rl.name, rl.description = body.name.strip(), body.description
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a list with that name")
    return _list_out(db, rl)


@router.delete("/reading-lists/{list_id}", status_code=204)
def delete_list(list_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own_list(db, list_id, user))
    db.commit()


@router.post("/reading-lists/{list_id}/items", status_code=201)
def add_list_item(list_id: int, body: ListItemIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rl = _own_list(db, list_id, user)
    if not db.get(Book, body.book_id):
        raise not_found("Book")
    if any(i.book_id == body.book_id for i in rl.items):
        raise HTTPException(status_code=409, detail="Book is already in this list")
    rl.items.append(ReadingListItem(book_id=body.book_id))
    db.commit()
    db.refresh(rl)
    return _list_out(db, rl)


@router.delete("/reading-lists/{list_id}/items/{book_id}", status_code=204)
def remove_list_item(list_id: int, book_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rl = _own_list(db, list_id, user)
    db.execute(delete(ReadingListItem).where(ReadingListItem.list_id == rl.id, ReadingListItem.book_id == book_id))
    db.commit()


# ------------------------------------------------------------------- goals
class GoalIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    target_books: int = Field(ge=1, le=1000)


def _finished_in(db: Session, user_id: int, year: int, month: int | None) -> list[BookshelfEntry]:
    entries = db.scalars(select(BookshelfEntry).where(BookshelfEntry.user_id == user_id,
                                                      BookshelfEntry.status == "read")).unique()
    out = []
    for e in entries:
        d = e.finished_on or as_utc(e.updated_at).date()
        if d.year == year and (month is None or d.month == month):
            out.append(e)
    return out


def _goal_out(db: Session, g: ReadingGoal) -> dict:
    done = len(_finished_in(db, g.user_id, g.year, g.month))
    return {"id": g.id, "year": g.year, "month": g.month, "target_books": g.target_books, "completed_books": done,
            "percent": round(min(100.0, 100 * done / g.target_books), 1)}


@router.get("/reading-goals")
def list_goals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goals = db.scalars(select(ReadingGoal).where(ReadingGoal.user_id == user.id)
                       .order_by(ReadingGoal.year.desc(), ReadingGoal.month))
    return [_goal_out(db, g) for g in goals]


@router.post("/reading-goals", status_code=201)
def set_goal(body: GoalIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create or update the goal for that year (and month, if given)."""
    q = select(ReadingGoal).where(ReadingGoal.user_id == user.id, ReadingGoal.year == body.year)
    q = q.where(ReadingGoal.month.is_(None) if body.month is None else ReadingGoal.month == body.month)
    goal = db.scalar(q)
    if goal:
        goal.target_books = body.target_books
    else:
        goal = ReadingGoal(user_id=user.id, year=body.year, month=body.month, target_books=body.target_books)
        db.add(goal)
    db.commit()
    return _goal_out(db, goal)


@router.delete("/reading-goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goal = db.get(ReadingGoal, goal_id)
    if not goal or goal.user_id != user.id:
        raise not_found("Goal")
    db.delete(goal)
    db.commit()


@router.get("/reading-history")
def reading_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = list(db.scalars(select(BookshelfEntry).where(BookshelfEntry.user_id == user.id,
                                                           BookshelfEntry.status == "read")).unique())
    sums = {s.id: s for s in summaries(db, [e.book for e in entries])}
    finished = sorted(entries, key=lambda e: e.finished_on or as_utc(e.updated_at).date(), reverse=True)
    by_year: dict[int, int] = {}
    pages_known = 0
    unknown_pages = 0
    for e in entries:
        d = e.finished_on or as_utc(e.updated_at).date()
        by_year[d.year] = by_year.get(d.year, 0) + 1
        if e.book.page_count:
            pages_known += e.book.page_count
        else:
            unknown_pages += 1
    viewed_ids = [bid for bid, _ in db.execute(
        select(UserBookInteraction.book_id, func.max(UserBookInteraction.created_at))
        .where(UserBookInteraction.user_id == user.id, UserBookInteraction.type == "view")
        .group_by(UserBookInteraction.book_id).order_by(func.max(UserBookInteraction.created_at).desc()).limit(12)
    ).all()]
    saved_ids = list(db.scalars(select(UserBookInteraction.book_id).where(
        UserBookInteraction.user_id == user.id, UserBookInteraction.type.in_(("save", "interested")))
        .order_by(UserBookInteraction.created_at.desc()).limit(24)))
    return {
        "finished": [{"entry_id": e.id, "book": sums[e.book_id].model_dump(), "finished_on": e.finished_on,
                      "started_on": e.started_on} for e in finished],
        "by_year": dict(sorted(by_year.items(), reverse=True)),
        "pages_read_known": pages_known,
        "books_with_unknown_pages": unknown_pages,
        "recently_viewed": [s.model_dump() for s in summaries(db, get_books(db, viewed_ids))],
        "saved": [s.model_dump() for s in summaries(db, get_books(db, list(dict.fromkeys(saved_ids))))],
    }


# ------------------------------------------------------------- reading plans
class PlanGenerateIn(BaseModel):
    book_ids: list[int] = Field(min_length=1, max_length=10)
    start_date: date | None = None
    target_date: date | None = None
    minutes_per_day: int = Field(default=30, ge=5, le=600)
    pages_per_minute: float = Field(default=0.8, gt=0.05, le=5)
    reading_days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], min_length=1, max_length=7)
    fit_to_target: bool = False
    page_overrides: dict[int, int] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=120)

    @field_validator("reading_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("reading_days uses ISO weekdays 1 (Mon) .. 7 (Sun)")
        return sorted(set(v))

    @field_validator("page_overrides")
    @classmethod
    def _overrides(cls, v: dict[int, int]) -> dict[int, int]:
        if any(p < 1 or p > 10000 for p in v.values()):
            raise ValueError("page counts must be between 1 and 10000")
        return v


def _plan_preview(db: Session, user: User, body: PlanGenerateIn) -> tuple[dict, list[rp.PlanBook], list[dict], date]:
    start = body.start_date or datetime.now(timezone.utc).date()
    if body.target_date and body.target_date < start:
        raise HTTPException(status_code=422, detail="Target date must be after the start date")
    books, missing = rp.plan_books_for(db, user.id, body.book_ids, body.page_overrides)
    if not books:
        raise HTTPException(status_code=422, detail={"message": "None of these books can be scheduled", "missing": missing})
    preview = rp.build_plan_preview(books, start, body.minutes_per_day, body.pages_per_minute, body.reading_days,
                                    body.target_date, body.fit_to_target)
    return preview, books, missing, start


@router.post("/reading-plans/generate")
def generate_plan(body: PlanGenerateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Preview a schedule without saving it."""
    preview, books, missing, _ = _plan_preview(db, user, body)
    titles = {b.book_id: b.title for b in books}
    return {
        "pages_per_day": preview["pages_per_day"], "minutes_per_day": preview["minutes_per_day"],
        "total_pages": preview["total_pages"], "estimated_finish": preview["estimated_finish"],
        "feasibility_note": preview["feasibility_note"], "unscheduled": missing,
        "days": [{"day": s.day, "book_id": s.book_id, "title": titles[s.book_id], "start_page": s.start_page,
                  "end_page": s.end_page} for s in preview["slices"]],
    }


def _plan_out(db: Session, plan: ReadingPlan) -> dict:
    titles = {b.id: b.title for b in get_books(db, list({i.book_id for i in plan.items} | set(plan.book_ids)))}
    return {
        "id": plan.id, "title": plan.title, "status": plan.status, "start_date": plan.start_date,
        "target_date": plan.target_date, "minutes_per_day": plan.minutes_per_day,
        "pages_per_minute": plan.pages_per_minute, "reading_days": plan.reading_days,
        "book_ids": plan.book_ids, "books": [{"id": i, "title": titles.get(i, "Removed book")} for i in plan.book_ids],
        "feasibility_note": plan.feasibility_note, "progress": rp.progress_summary(plan),
        "items": [{"id": i.id, "day": i.day, "book_id": i.book_id, "title": titles.get(i.book_id, ""),
                   "start_page": i.start_page, "end_page": i.end_page, "completed": i.completed,
                   "actual_pages": i.actual_pages} for i in plan.items],
        "reminders": "Not sent by BookWorm. Download the .ics file to add the schedule to your own calendar.",
    }


@router.get("/reading-plans")
def list_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plans = db.scalars(select(ReadingPlan).where(ReadingPlan.user_id == user.id).order_by(ReadingPlan.created_at.desc()))
    return [_plan_out(db, p) for p in plans]


@router.post("/reading-plans", status_code=201)
def create_plan(body: PlanGenerateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preview, books, missing, start = _plan_preview(db, user, body)
    plan = ReadingPlan(
        user_id=user.id, title=(body.title or f"Plan: {', '.join(b.title for b in books)}")[:120],
        start_date=start, target_date=body.target_date, minutes_per_day=preview["minutes_per_day"],
        pages_per_minute=body.pages_per_minute, reading_days=body.reading_days, book_ids=[b.book_id for b in books],
        feasibility_note=preview["feasibility_note"],
    )
    plan.items = rp.to_items(preview["slices"])
    db.add(plan)
    db.commit()
    out = _plan_out(db, plan)
    out["unscheduled"] = missing
    return out


def _own_plan(db: Session, plan_id: int, user: User) -> ReadingPlan:
    plan = db.get(ReadingPlan, plan_id)
    if not plan or plan.user_id != user.id:
        raise not_found("Reading plan")
    return plan


@router.get("/reading-plans/{plan_id}")
def get_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _plan_out(db, _own_plan(db, plan_id, user))


class PlanItemUpdate(BaseModel):
    completed: bool | None = None
    actual_pages: int | None = Field(default=None, ge=0, le=5000)


@router.patch("/reading-plans/{plan_id}/items/{item_id}")
def update_plan_item(plan_id: int, item_id: int, body: PlanItemUpdate, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    plan = _own_plan(db, plan_id, user)
    item = next((i for i in plan.items if i.id == item_id), None)
    if not item:
        raise not_found("Plan day")
    if body.completed is not None:
        item.completed = body.completed
    if body.actual_pages is not None:
        item.actual_pages = body.actual_pages
    # Keep the bookshelf in step with plan progress.
    if item.completed:
        entry = db.scalar(select(BookshelfEntry).where(BookshelfEntry.user_id == user.id,
                                                       BookshelfEntry.book_id == item.book_id))
        if entry is None:
            entry = BookshelfEntry(user_id=user.id, book_id=item.book_id, status="reading",
                                   started_on=datetime.now(timezone.utc).date())
            db.add(entry)
        entry.pages_read = max(entry.pages_read or 0, item.end_page)
    if all(i.completed for i in plan.items):
        plan.status = "completed"
    db.commit()
    return _plan_out(db, plan)


class PlanRescheduleIn(BaseModel):
    minutes_per_day: int | None = Field(default=None, ge=5, le=600)
    pages_per_minute: float | None = Field(default=None, gt=0.05, le=5)
    reading_days: list[int] | None = Field(default=None, min_length=1, max_length=7)
    target_date: date | None = None
    fit_to_target: bool = False


@router.post("/reading-plans/{plan_id}/reschedule")
def reschedule_plan(plan_id: int, body: PlanRescheduleIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Rebuild the remaining schedule from today, starting where the reader actually is."""
    plan = _own_plan(db, plan_id, user)
    today = datetime.now(timezone.utc).date()
    if body.minutes_per_day:
        plan.minutes_per_day = body.minutes_per_day
    if body.pages_per_minute:
        plan.pages_per_minute = body.pages_per_minute
    if body.reading_days:
        plan.reading_days = sorted({d for d in body.reading_days if 1 <= d <= 7})
    if body.target_date:
        plan.target_date = body.target_date
    # Furthest page completed per book (from plan progress or bookshelf).
    done: dict[int, int] = {}
    for i in plan.items:
        if i.completed:
            done[i.book_id] = max(done.get(i.book_id, 0), i.end_page)
        elif i.actual_pages:
            done[i.book_id] = max(done.get(i.book_id, 0), i.start_page + i.actual_pages - 1)
    totals = {}
    for i in plan.items:
        totals[i.book_id] = max(totals.get(i.book_id, 0), i.end_page)
    books = []
    for bid in plan.book_ids:
        entry = db.scalar(select(BookshelfEntry).where(BookshelfEntry.user_id == user.id, BookshelfEntry.book_id == bid))
        start_page = max(done.get(bid, 0), entry.pages_read if entry else 0) + 1
        total = totals.get(bid) or (db.get(Book, bid).page_count if db.get(Book, bid) else None)
        if total and start_page <= total:
            books.append(rp.PlanBook(bid, "", total, start_page))
    keep = [i for i in plan.items if i.completed or i.day < today]
    preview = rp.build_plan_preview(books, today, plan.minutes_per_day, plan.pages_per_minute, plan.reading_days,
                                    plan.target_date, body.fit_to_target)
    plan.items = keep + rp.to_items(preview["slices"])
    plan.minutes_per_day = preview["minutes_per_day"]
    plan.feasibility_note = preview["feasibility_note"]
    plan.status = "completed" if not books else "active"
    db.commit()
    db.refresh(plan)
    return _plan_out(db, plan)


@router.delete("/reading-plans/{plan_id}", status_code=204)
def delete_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own_plan(db, plan_id, user))
    db.commit()


@router.get("/reading-plans/{plan_id}/calendar.ics")
def plan_calendar(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = _own_plan(db, plan_id, user)
    titles = {b.id: b.title for b in get_books(db, plan.book_ids)}
    return Response(rp.ics_calendar(plan, titles), media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="reading-plan-{plan.id}.ics"'})

