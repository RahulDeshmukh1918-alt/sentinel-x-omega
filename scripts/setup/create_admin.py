"""Create (or reset the password of) a dashboard user.

    python scripts/setup/create_admin.py --email admin@example.com --name "Admin"
    python scripts/setup/create_admin.py --email op@example.com --name "Operator" --role OPERATOR

The password is prompted for (never pass it on the command line in shared terminals);
set SENTINEL_ADMIN_PASSWORD to run non-interactively.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from backend.app.core.enums import UserRole  # noqa: E402
from backend.app.core.security import PasswordPolicyError, hash_password  # noqa: E402
from backend.app.database.connection import get_session_factory, init_db  # noqa: E402
from backend.app.models import User  # noqa: E402
from backend.app.schemas.user import UserCreate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", default="Administrator")
    ap.add_argument("--role", default="ADMIN", choices=[r.value for r in UserRole])
    args = ap.parse_args(argv)

    password = os.environ.get("SENTINEL_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password (8-72 characters): ")
        if password != getpass.getpass("Repeat password: "):
            print("passwords do not match")
            return 1
    try:
        data = UserCreate(name=args.name, email=args.email, password=password, role=UserRole(args.role))
        password_hash = hash_password(data.password)
    except (ValidationError, PasswordPolicyError) as exc:
        print(f"invalid input: {exc}")
        return 1

    init_db()
    with get_session_factory()() as session:
        user = session.scalars(select(User).where(func.lower(User.email) == data.email.lower())).first()
        if user:
            user.password_hash, user.role, user.name, user.is_active = password_hash, data.role, data.name, True
            action = "updated"
        else:
            session.add(User(name=data.name, email=data.email.lower(), password_hash=password_hash, role=data.role))
            action = "created"
        session.commit()
    print(f"{data.role.value} user {data.email} {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
