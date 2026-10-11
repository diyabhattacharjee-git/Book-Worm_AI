"""Reading plan scheduling.

pages_per_day = max(1, floor(minutes_per_day * pages_per_minute))
Pages are assigned sequentially across the chosen books on the chosen weekdays
only. Books with an unknown page count cannot be scheduled unless the user
supplies the page count themselves. Reminders are not sent by the server: the
plan can be exported as an .ics file and imported into any free calendar app.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.reading import BookshelfEntry, ReadingPlan, ReadingPlanItem

MAX_DAYS = 730


@dataclass
class PlanBook:
    book_id: int
    title: str
    total_pages: int
    start_page: int  # first unread page (1-based)


@dataclass
class DaySlice:
    day: date
    book_id: int
    start_page: int
    end_page: int


def pages_per_day(minutes: int, ppm: float) -> int:
    return max(1, math.floor(minutes * ppm))


def reading_dates(start: date, weekdays: list[int]):
    d = start
    for _ in range(MAX_DAYS):
        if d.isoweekday() in weekdays:
            yield d
        d += timedelta(days=1)


def count_reading_days(start: date, end: date, weekdays: list[int]) -> int:
    return sum(1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).isoweekday() in weekdays)


def schedule(books: list[PlanBook], start: date, per_day: int, weekdays: list[int]) -> list[DaySlice]:
    slices: list[DaySlice] = []
    queue = [(b.book_id, b.start_page, b.total_pages) for b in books if b.start_page <= b.total_pages]
    if not queue:
        return slices
    qi = 0
    book_id, page, total = queue[0]
    for d in reading_dates(start, weekdays):
        budget = per_day
        while budget > 0 and qi < len(queue):
            end = min(total, page + budget - 1)
            slices.append(DaySlice(d, book_id, page, end))
            budget -= end - page + 1
            page = end + 1
            if page > total:
                qi += 1
                if qi < len(queue):
                    book_id, page, total = queue[qi]
        if qi >= len(queue):
            break
    return slices


def build_plan_preview(books: list[PlanBook], start: date, minutes: int, ppm: float, weekdays: list[int],
                       target: date | None, fit_to_target: bool) -> dict:
    total_pages = sum(max(0, b.total_pages - b.start_page + 1) for b in books)
    per_day = pages_per_day(minutes, ppm)
    note = None
    if target:
        days = count_reading_days(start, target, weekdays)
        if days == 0:
            note = "There are no selected reading days before the target date."
        else:
            needed = math.ceil(total_pages / days)
            needed_min = math.ceil(needed / ppm)
            if fit_to_target:
                per_day = max(1, needed)
                minutes = needed_min
                note = f"Fitted to your target: {needed} pages (~{needed_min} min) per reading day."
            elif needed > per_day:
                note = (f"At {per_day} pages/day you would finish after your target. To finish by {target.isoformat()} "
                        f"you need about {needed} pages (~{needed_min} minutes) per reading day.")
            else:
                note = f"On track: you need {needed} pages/day and your plan gives {per_day}."
    slices = schedule(books, start, per_day, weekdays)
    finish = slices[-1].day if slices else None
    return {"pages_per_day": per_day, "minutes_per_day": minutes, "total_pages": total_pages,
            "estimated_finish": finish, "feasibility_note": note, "slices": slices}


def plan_books_for(db: Session, user_id: int, book_ids: list[int], overrides: dict[int, int]) -> tuple[list[PlanBook], list[dict]]:
    out, missing = [], []
    for bid in book_ids:
        book = db.get(Book, bid)
        if not book:
            missing.append({"book_id": bid, "reason": "Book not found"})
            continue
        pages = overrides.get(bid) or book.page_count
        if not pages:
            missing.append({"book_id": bid, "title": book.title,
                            "reason": "Page count unknown. Enter the page count of your copy to schedule it."})
            continue
        entry = db.scalar(select(BookshelfEntry).where(BookshelfEntry.user_id == user_id, BookshelfEntry.book_id == bid))
        start_page = min(pages, (entry.pages_read if entry else 0)) + 1
        out.append(PlanBook(bid, book.title, pages, start_page))
    return out, missing


def progress_summary(plan: ReadingPlan, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    planned_to_date = sum(i.end_page - i.start_page + 1 for i in plan.items if i.day <= today)
    planned_total = sum(i.end_page - i.start_page + 1 for i in plan.items)
    actual = sum((i.actual_pages if i.actual_pages is not None else (i.end_page - i.start_page + 1)) if i.completed
                 else (i.actual_pages or 0) for i in plan.items)
    diff = actual - planned_to_date
    status = "ahead" if diff > 0 else "behind" if diff < 0 else "on_track"
    finish = plan.items[-1].day if plan.items else None
    return {"planned_pages_to_date": planned_to_date, "actual_pages": actual, "planned_total": planned_total,
            "difference": diff, "status": status, "scheduled_finish": finish,
            "percent_complete": round(100 * actual / planned_total, 1) if planned_total else None}


def to_items(slices: list[DaySlice]) -> list[ReadingPlanItem]:
    return [ReadingPlanItem(day=s.day, book_id=s.book_id, start_page=s.start_page, end_page=s.end_page) for s in slices]


def ics_calendar(plan: ReadingPlan, titles: dict[int, str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BookWorm//Reading Plan//EN", "CALSCALE:GREGORIAN"]
    for it in plan.items:
        title = titles.get(it.book_id, "Reading").replace(",", "\\,").replace(";", "\\;")
        d = it.day.strftime("%Y%m%d")
        nd = (it.day + timedelta(days=1)).strftime("%Y%m%d")
        lines += ["BEGIN:VEVENT", f"UID:bookworm-plan-{plan.id}-item-{it.id}@bookworm.local", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nd}",
                  f"SUMMARY:Read {title}: pages {it.start_page}-{it.end_page}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
