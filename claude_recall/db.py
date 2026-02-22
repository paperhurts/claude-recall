"""
Database initialization and connection management for claude-recall.

Usage:
    python -m claude_recall.db                  # creates recall.db in current directory
    python -m claude_recall.db --db path/to.db  # custom location
    python -m claude_recall.db --reset          # drop and recreate (DESTRUCTIVE)
"""

import argparse
import sqlite3
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB = Path("recall.db")


def init_database(db_path: Path = DEFAULT_DB, *, reset: bool = False) -> sqlite3.Connection:
    """Create or verify the recall database.

    Args:
        db_path: Path to the SQLite database file.
        reset: If True, drop all tables first (DESTRUCTIVE).

    Returns:
        Open sqlite3.Connection with foreign keys enabled.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    if reset:
        print(f"[RESET] Dropping all tables in {db_path}")
        cursor = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
        )
        objects = cursor.fetchall()
        for name, obj_type in sorted(objects, key=lambda x: x[1], reverse=True):
            conn.execute(f"DROP {obj_type.upper()} IF EXISTS [{name}]")
        conn.commit()

    schema_sql = SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    conn.commit()

    # Verify
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()

    print(f"[OK] Database: {db_path}")
    print(f"     Tables: {', '.join(t[0] for t in tables)}")

    return conn


def get_connection(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    """Get a connection to an existing database."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run: python -m claude_recall.db"
        )
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize claude-recall database")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Database path")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables")
    args = parser.parse_args()

    if args.reset:
        confirm = input(f"This will DELETE all data in {args.db}. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(1)

    conn = init_database(args.db, reset=args.reset)
    conn.close()
