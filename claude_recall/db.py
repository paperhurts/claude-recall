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


def _backfill_fts(conn: sqlite3.Connection):
    """Backfill FTS5 indexes for any source rows missing from FTS.

    Safe to run multiple times -- skips rows already in FTS.
    This handles the upgrade case where data existed before FTS was added.
    """
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO turns_fts(rowid, content)
            SELECT turn_id, content FROM turns
            WHERE turn_id NOT IN (SELECT rowid FROM turns_fts)
    """)

    cursor.execute("""
        INSERT INTO artifacts_fts(rowid, title, content)
            SELECT artifact_id, title, content FROM artifacts
            WHERE artifact_id NOT IN (SELECT rowid FROM artifacts_fts)
    """)

    cursor.execute("""
        INSERT INTO emails_fts(rowid, subject, body_text)
            SELECT email_id, subject, body_text FROM emails
            WHERE email_id NOT IN (SELECT rowid FROM emails_fts)
    """)


def init_database(db_path=DEFAULT_DB, *, reset: bool = False) -> sqlite3.Connection:
    """Create or verify the recall database.

    Args:
        db_path: Path to the SQLite database file, or ":memory:" for testing.
        reset: If True, drop all tables first (DESTRUCTIVE).

    Returns:
        Open sqlite3.Connection with foreign keys enabled.
    """
    # FTS5 with porter+unicode61 tokenizer chain requires SQLite >= 3.29
    if sqlite3.sqlite_version_info < (3, 29, 0):
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} found, but >= 3.29 is required "
            f"for FTS5 porter+unicode61 tokenizer. Upgrade SQLite."
        )

    if isinstance(db_path, str) and db_path == ":memory:":
        conn = sqlite3.connect(":memory:")
    else:
        db_path = Path(db_path) if not isinstance(db_path, Path) else db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))

    conn.execute("PRAGMA foreign_keys = ON")

    if reset:
        print(f"[RESET] Dropping all objects in database")
        cursor = conn.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%'"
        )
        objects = cursor.fetchall()

        # 1. Drop triggers first — they reference FTS tables which we're about
        #    to remove. If triggers are still active when we CASCADE-delete rows
        #    from regular tables, they'll fail trying to update a dropped FTS table.
        triggers = [name for name, obj_type, _ in objects if obj_type == "trigger"]
        for name in triggers:
            conn.execute(f"DROP TRIGGER IF EXISTS [{name}]")

        # 2. Drop FTS5 virtual tables — auto-removes their shadow tables too
        fts_tables = [
            name for name, obj_type, sql in objects
            if obj_type == "table" and sql and "CREATE VIRTUAL TABLE" in sql
        ]
        for name in fts_tables:
            conn.execute(f"DROP TABLE IF EXISTS [{name}]")

        # 3. Drop views
        views = [name for name, obj_type, _ in objects if obj_type == "view"]
        for name in views:
            conn.execute(f"DROP VIEW IF EXISTS [{name}]")

        # 4. Drop regular tables (shadow tables are already gone with their FTS parents)
        regular_tables = [
            name for name, obj_type, sql in objects
            if obj_type == "table" and name not in fts_tables
            and not any(name.startswith(f"{ft}_") for ft in fts_tables)
        ]
        for name in regular_tables:
            conn.execute(f"DROP TABLE IF EXISTS [{name}]")

        conn.commit()

    schema_sql = SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    conn.execute("PRAGMA foreign_keys = ON")  # re-enable after executescript

    _backfill_fts(conn)

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
