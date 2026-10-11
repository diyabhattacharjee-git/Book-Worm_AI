"""Developer CLI.

    python -m app.cli init-db            # apply Alembic migrations
    python -m app.cli seed               # real book catalogue + marketplace providers
    python -m app.cli create-admin --email you@example.com --username yourname
    python -m app.cli check-email --to you@example.com   # send a test email via SMTP
    python -m app.cli check-llm                          # test the configured LLM provider(s)
    python -m app.cli promote-admin --email existing@example.com
    python -m app.cli evaluate [--k 10]
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings


def _alembic_upgrade() -> None:
    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")


def cmd_init_db(_: argparse.Namespace) -> None:
    _alembic_upgrade()
    print("Database is up to date.")


def cmd_seed(_: argparse.Namespace) -> None:
    from app.db.seed import run_seed
    from app.db.session import SessionLocal

    _alembic_upgrade()
    with SessionLocal() as db:
        result = run_seed(db)
    print(f"Catalogue books created: {result['books_created']} (real metadata; no users, ratings or listings are created)")


def _read_password() -> str:
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password (min 12 chars): ")
    if len(pw) < 12:
        sys.exit("Password must be at least 12 characters.")
    return pw


def cmd_create_admin(args: argparse.Namespace) -> None:
    from app.db.session import SessionLocal
    from app.models.user import ROLE_ADMIN, User, UserProfile
    from app.schemas.users import validate_username
    from app.security.passwords import hash_password

    _alembic_upgrade()
    email = args.email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            sys.exit("A user with that email already exists. Use promote-admin instead.")
        username = validate_username(args.username)
        if db.scalar(select(User).where(User.username == username)):
            sys.exit("That username is taken.")
        user = User(email=email, username=username, password_hash=hash_password(_read_password()),
                    display_name=args.name, role=ROLE_ADMIN, email_verified=True)
        user.profile = UserProfile()
        db.add(user)
        db.commit()
    print(f"Administrator {email} created.")


def cmd_promote_admin(args: argparse.Namespace) -> None:
    from app.db.session import SessionLocal
    from app.models.user import ROLE_ADMIN, User

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if not user:
            sys.exit("No such user.")
        user.role = ROLE_ADMIN
        user.token_version += 1
        db.commit()
    print(f"{args.email} is now an administrator (existing sessions were signed out).")


def cmd_check_email(args: argparse.Namespace) -> None:
    from app.services.mailer import send_email

    if not get_settings().smtp_configured:
        sys.exit("SMTP is not configured: set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM in backend/.env")
    send_email(args.to, "BookWorm test email", "If you can read this, BookWorm can send one-time codes.")
    print(f"Test email sent to {args.to}.")


def cmd_check_llm(_: argparse.Namespace) -> None:
    from app.agents import llm

    status = llm.status()
    for name, info in status["providers"].items():
        print(f"{name:12} configured={info['configured']} model={info['model']}")
    try:
        res = llm.complete("Reply with exactly: OK", "Say OK", max_tokens=5)
    except llm.LLMUnavailable as exc:
        details = {k: v["last_error"] for k, v in llm.status()["providers"].items() if v["last_error"]}
        sys.exit(f"No working LLM: {exc}. {details or ''}")
    print(f"Connected: {res.provider} / {res.model} replied {res.text.strip()!r}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    from app.db.session import SessionLocal
    from app.recommender.evaluation import evaluate

    with SessionLocal() as db:
        out = evaluate(db, k=args.k)
    out.pop("methodology", None)
    print(json.dumps(out, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    p = sub.add_parser("create-admin")
    p.add_argument("--email", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--name", default="Administrator")
    p.set_defaults(fn=cmd_create_admin)
    p = sub.add_parser("check-email")
    p.add_argument("--to", required=True)
    p.set_defaults(fn=cmd_check_email)
    sub.add_parser("check-llm").set_defaults(fn=cmd_check_llm)
    p = sub.add_parser("promote-admin")
    p.add_argument("--email", required=True)
    p.set_defaults(fn=cmd_promote_admin)
    p = sub.add_parser("evaluate")
    p.add_argument("--k", type=int, default=10)
    p.set_defaults(fn=cmd_evaluate)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
