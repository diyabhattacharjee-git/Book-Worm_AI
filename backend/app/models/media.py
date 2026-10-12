"""Uploaded images kept in the database (used when there is no persistent disk and no Cloudinary)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class StoredImage(Base):
    __tablename__ = "stored_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "<subdir>/<random token>.<ext>", the same shape as a local upload path.
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
