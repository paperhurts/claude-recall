"""Tests for db.py: version check, reset ordering, FTS backfill."""

import sqlite3
import tempfile
from pathlib import Path as TmpPath
from unittest.mock import patch
import pytest
from claude_recall.db import init_database


def test_sqlite_version_sufficient():
    """init_database succeeds when SQLite version is >= 3.29."""
    conn = init_database(":memory:")
    conn.close()


def test_sqlite_version_too_old():
    """init_database raises RuntimeError when SQLite < 3.29."""
    with patch.object(sqlite3, "sqlite_version_info", (3, 28, 0)):
        with pytest.raises(RuntimeError, match="3.29"):
            init_database(":memory:")


def test_reset_drops_fts_before_regular_tables():
    """Reset successfully drops FTS5 virtual tables before regular tables.

    Uses a temp file DB so the same database is populated then reset.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = TmpPath(f.name)

    try:
        # Create and populate
        conn = init_database(db_path)
        conn.execute(
            "INSERT INTO sessions (claude_uuid, url) VALUES ('test', 'https://example.com')"
        )
        conn.commit()
        conn.close()

        # Reset the same populated database — should not error
        conn = init_database(db_path, reset=True)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "sessions" in table_names
        assert "turns_fts" in table_names

        # Verify data was cleared
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 0
        conn.close()
    finally:
        db_path.unlink(missing_ok=True)


def test_fts_backfill_populates_missing_rows():
    """_backfill_fts() populates FTS for rows that are missing from FTS.

    Simulates the upgrade scenario: data exists in source tables but not in FTS
    (because triggers didn't exist when data was originally inserted).
    """
    from claude_recall.db import _backfill_fts, SCHEMA_PATH

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")

    # Create full schema (with FTS and triggers)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("PRAGMA foreign_keys = ON")

    # Insert data (triggers will auto-populate FTS)
    conn.execute(
        "INSERT INTO sessions (claude_uuid, url) VALUES ('c1', 'https://claude.ai/chat/c1')"
    )
    sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO turns (session_id, turn_index, role, content, content_length) "
        "VALUES (?, 0, 'user', 'playground fundraising question', 33)",
        (sid,),
    )
    conn.execute(
        "INSERT INTO turns (session_id, turn_index, role, content, content_length) "
        "VALUES (?, 1, 'assistant', 'the funds were misallocated', 27)",
        (sid,),
    )

    # Now simulate pre-FTS state by wiping FTS content directly
    conn.execute("DELETE FROM turns_fts")

    # Verify FTS is empty
    count = conn.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0]
    assert count == 0

    # Run backfill — should repopulate FTS from source rows
    _backfill_fts(conn)

    # Verify FTS is repopulated
    results = conn.execute(
        "SELECT content FROM turns_fts WHERE turns_fts MATCH 'playground'"
    ).fetchall()
    assert len(results) == 1
    assert "playground" in results[0][0]

    total = conn.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0]
    assert total == 2  # both turns backfilled

    conn.close()


def test_fts_backfill_is_idempotent():
    """Running backfill multiple times doesn't create duplicates."""
    from claude_recall.db import _backfill_fts, SCHEMA_PATH

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("PRAGMA foreign_keys = ON")

    # Insert a turn (trigger populates FTS)
    conn.execute(
        "INSERT INTO sessions (claude_uuid, url) VALUES ('c1', 'https://claude.ai/chat/c1')"
    )
    sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO turns (session_id, turn_index, role, content, content_length) "
        "VALUES (?, 0, 'user', 'test content', 12)",
        (sid,),
    )

    # Run backfill — should be a no-op since trigger already inserted
    _backfill_fts(conn)
    _backfill_fts(conn)  # run twice to prove idempotence

    count = conn.execute(
        "SELECT COUNT(*) FROM turns_fts WHERE turns_fts MATCH 'test'"
    ).fetchone()[0]
    assert count == 1  # not duplicated

    conn.close()
