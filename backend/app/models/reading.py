"""Bookshelf, custom lists, goals, reading plans and assistant conversations."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.models.book import Book

SHELF_STATUSES = ("want_to_read", "reading", "read", "abandoned")


class BookshelfEntry(TimestampMixin, Base):
    __tablename__ = "bookshelf_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id"),
        CheckConstraint("pages_read >= 0", name="pages_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    pages_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_on: Mapped[date | None] = mapped_column(Date)
    finished_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    book: Mapped[Book] = relationship(lazy="joined")


class ReadingList(TimestampMixin, Base):
    __tablename__ = "reading_lists"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))

    items: Mapped[list[ReadingListItem]] = relationship(
        back_populates="reading_list", cascade="all, delete-orphan", lazy="selectin"
    )


class ReadingListItem(Base):
    __tablename__ = "reading_list_items"
    __table_args__ = (UniqueConstraint("list_id", "book_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("reading_lists.id", ondelete="CASCADE"), nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    reading_list: Mapped[ReadingList] = relationship(back_populates="items")
    book: Mapped[Book] = relationship(lazy="joined")


class ReadingGoal(TimestampMixin, Base):
    __tablename__ = "reading_goals"
    __table_args__ = (
        UniqueConstraint("user_id", "year", "month"),
        CheckConstraint("target_books > 0", name="target_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int | None] = mapped_column(Integer)  # NULL = annual goal
    target_books: Mapped[int] = mapped_column(Integer, nullable=False)


class ReadingPlan(TimestampMixin, Base):
    __tablename__ = "reading_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    minutes_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_per_minute: Mapped[float] = mapped_column(Float, nullable=False)
    reading_days: Mapped[list] = mapped_column(JSON, nullable=False)  # ISO weekday numbers 1..7
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active|completed|archived
    book_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    feasibility_note: Mapped[str | None] = mapped_column(String(300))

    items: Mapped[list[ReadingPlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="ReadingPlanItem.day", lazy="selectin"
    )


class ReadingPlanItem(Base):
    __tablename__ = "reading_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("reading_plans.id", ondelete="CASCADE"), index=True, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    actual_pages: Mapped[int | None] = mapped_column(Integer)

    plan: Mapped[ReadingPlan] = relationship(back_populates="items")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="New conversation", nullable=False)
    # Short-term context: last referenced book ids, last search params (for refinements).
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.id",
        lazy="selectin",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user|assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # structured tool results
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
