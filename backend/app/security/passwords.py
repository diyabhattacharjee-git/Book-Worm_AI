"""Password hashing with bcrypt.

bcrypt only uses the first 72 bytes of its input, so the password is first
reduced with SHA-256 and base64-encoded (44 bytes). This keeps long passphrases
fully significant without hitting bcrypt's length limit."""

from __future__ import annotations

import base64
import hashlib

import bcrypt


def _prehash(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except ValueError:
        return False


# Used to equalise timing when the email is unknown.
DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")
