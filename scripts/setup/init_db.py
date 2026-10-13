"""Create all database tables (idempotent).

    python scripts/setup/init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.database.connection import get_engine, init_db  # noqa: E402


def main() -> int:
    init_db()
    url = get_engine().url
    print(f"database ready: {url.render_as_string(hide_password=True)}")
    print(f"environment: {get_settings().environment}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
