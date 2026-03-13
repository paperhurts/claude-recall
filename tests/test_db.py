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
