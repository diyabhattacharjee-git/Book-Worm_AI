"""Safe image uploads.

* Size limit enforced while streaming (MAX_UPLOAD_MB).
* Content is decoded with Pillow; the declared filename/content-type is ignored.
* Only JPEG / PNG / WEBP are accepted; images are re-encoded, which strips
  EXIF metadata (including GPS location) and any trailing payload.
* Files get random names. With CLOUDINARY_URL set they are stored in Cloudinary
  (free plan; required on hosts without a persistent disk such as Vercel) and the
  stored path is the HTTPS URL; otherwise they go to UPLOAD_DIR and are served
  with nosniff + a restrictive CSP.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import secrets
import time
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings

logger = logging.getLogger("bookworm.uploads")

ALLOWED = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
CLOUDINARY_FOLDER = "bookworm"
MAX_PIXELS = 40_000_000
MAX_DIMENSION = 1600
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


async def read_limited(file: UploadFile) -> bytes:
    limit = int(get_settings().max_upload_mb * 1024 * 1024)
    chunks, size = [], 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"Image exceeds {get_settings().max_upload_mb:g} MB")
        chunks.append(chunk)
    if not size:
        raise HTTPException(status_code=422, detail="Empty file")
    return b"".join(chunks)


def save_image(data: bytes, subdir: str) -> str:
    """Validate, re-encode and store an image. Returns a path relative to UPLOAD_DIR."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED:
            raise HTTPException(status_code=415, detail="Only JPEG, PNG or WEBP images are allowed")
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            out = io.BytesIO()
            if fmt == "JPEG":
                img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
            elif fmt == "PNG":
                img.save(out, "PNG", optimize=True)
            else:
                img.save(out, "WEBP", quality=85)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError):
        raise HTTPException(status_code=415, detail="File is not a valid image")
    token = secrets.token_hex(16)
    if get_settings().cloudinary:
        return _cloudinary_upload(out.getvalue(), f"{CLOUDINARY_FOLDER}/{subdir}/{token}")
    root = Path(get_settings().upload_dir)
    folder = root / subdir
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{token}.{ALLOWED[fmt]}"
    (folder / name).write_bytes(out.getvalue())
    return f"{subdir}/{name}"


def public_url(path: str | None) -> str | None:
    """Browser URL for a stored upload (Cloudinary URL or local /uploads path)."""
    if not path:
        return None
    return path if path.startswith("https://") else f"/uploads/{path}"


def _cloudinary_sign(params: dict, secret: str) -> str:
    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1((payload + secret).encode()).hexdigest()


def _cloudinary_upload(data: bytes, public_id: str) -> str:
    c = get_settings().cloudinary
    params = {"public_id": public_id, "timestamp": int(time.time())}
    form = {**{k: str(v) for k, v in params.items()}, "api_key": c["api_key"],
            "signature": _cloudinary_sign(params, c["api_secret"])}
    try:
        resp = httpx.post(f"https://api.cloudinary.com/v1_1/{c['cloud_name']}/image/upload",
                          data=form, files={"file": ("image", data)}, timeout=30)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Image storage is unavailable. Please try again.")
    if resp.status_code != 200 or not str(resp.json().get("secure_url", "")).startswith("https://"):
        logger.error("cloudinary upload failed", extra={"data": {"status": resp.status_code}})
        raise HTTPException(status_code=502, detail="Image storage rejected the upload. Please try again.")
    return resp.json()["secure_url"]


def _cloudinary_delete(url: str) -> None:
    c = get_settings().cloudinary
    m = re.search(r"/image/upload/(?:v\d+/)?(.+?)\.[a-z0-9]+$", url)
    if not c or not m:
        return
    params = {"public_id": m.group(1), "timestamp": int(time.time())}
    form = {**{k: str(v) for k, v in params.items()}, "api_key": c["api_key"],
            "signature": _cloudinary_sign(params, c["api_secret"])}
    try:
        httpx.post(f"https://api.cloudinary.com/v1_1/{c['cloud_name']}/image/destroy", data=form, timeout=15)
    except httpx.HTTPError:
        logger.warning("cloudinary delete failed")


def delete_upload(rel_path: str | None) -> None:
    if not rel_path:
        return
    if rel_path.startswith("https://"):
        _cloudinary_delete(rel_path)
        return
    root = Path(get_settings().upload_dir).resolve()
    target = (root / rel_path).resolve()
    if root in target.parents and target.is_file():
        target.unlink(missing_ok=True)
