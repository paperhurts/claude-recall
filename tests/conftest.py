"""Shared fixtures for claude-recall tests."""

import sqlite3
import pytest
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "claude_recall" / "schema.sql"


@pytest.fixture
def test_db():
    """In-memory SQLite database with the full schema applied.

    Yields an open connection. Foreign keys are enabled.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema_sql = SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    # Re-enable foreign keys after executescript (which issues implicit COMMIT)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()
