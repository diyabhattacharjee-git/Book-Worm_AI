from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

book_authors = Table(
    "book_authors",
    Base.metadata,
    Column("book_id", ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("author_id", ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, nullable=False, default=0),
)

book_genres = Table(
    "book_genres",
    Base.metadata,
    Column("book_id", ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)


class Genre(Base):
    """Genres and subjects share a table; `kind` distinguishes curated genres
    (shown in filters) from free-form subjects imported from metadata sources."""

    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="genre", nullable=False)  # genre|subject


class Book(TimestampMixin, Base):
    """A work (e.g. 'Atomic Habits'). Edition-specific data lives on BookEdition."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300))
    normalized_title: Mapped[str] = mapped_column(String(300), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(12), index=True)
    first_published_year: Mapped[int | None] = mapped_column(Integer, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    publisher: Mapped[str | None] = mapped_column(String(200))
    series: Mapped[str | None] = mapped_column(String(200))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    difficulty: Mapped[str | None] = mapped_column(String(16))  # beginner|intermediate|advanced (only when sourced)

    # Ratings supplied by an external metadata provider, kept separate from app reviews.
    external_rating_avg: Mapped[float | None] = mapped_column(Float)
    external_rating_count: Mapped[int | None] = mapped_column(Integer)
    external_rating_source: Mapped[str | None] = mapped_column(String(40))

    # Provenance
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    openlibrary_work_key: Mapped[str | None] = mapped_column(String(40), unique=True)
    google_volume_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    authors: Mapped[list[Author]] = relationship(
        secondary=book_authors, order_by=book_authors.c.position, lazy="selectin"
    )
    genres: Mapped[list[Genre]] = relationship(secondary=book_genres, lazy="selectin")
    editions: Mapped[list[BookEdition]] = relationship(
        back_populates="book", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def author_names(self) -> list[str]:
        return [a.name for a in self.authors]

    @property
    def primary_isbn(self) -> str | None:
        for e in self.editions:
            if e.isbn13:
                return e.isbn13
        return None


class BookEdition(TimestampMixin, Base):
    __tablename__ = "book_editions"
    __table_args__ = (UniqueConstraint("isbn13"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    isbn13: Mapped[str | None] = mapped_column(String(13), index=True)
    isbn10: Mapped[str | None] = mapped_column(String(10), index=True)
    format: Mapped[str | None] = mapped_column(String(20))  # paperback|hardcover|ebook|audiobook
    edition_label: Mapped[str | None] = mapped_column(String(100))
    publisher: Mapped[str | None] = mapped_column(String(200))
    published_year: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(12))
    is_translation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    book: Mapped[Book] = relationship(back_populates="editions")


class ExternalCache(Base):
    """Generic response cache for metadata / pricing providers."""

    __tablename__ = "external_cache"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
