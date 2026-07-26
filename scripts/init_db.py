#!/usr/bin/env python3
"""Initialize the SQLite database schema and default counters."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.database import init_database  # noqa: E402


def main() -> None:
    db_path = init_database()
    print(f"Database initialized at: {db_path}")


if __name__ == "__main__":
    main()
