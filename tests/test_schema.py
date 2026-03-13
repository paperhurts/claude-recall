"""Tests for schema: tables, FTS triggers, and backfill behavior."""

import sqlite3
import pytest


def test_artifacts_table_exists(test_db):
    """Artifacts table is created by schema."""
    result = test_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
    ).fetchone()
    assert result is not None


def test_emails_table_exists(test_db):
    """Emails table is created by schema."""
    result = test_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='emails'"
    ).fetchone()
    assert result is not None


def test_artifacts_foreign_key(test_db):
    """Artifact insert without valid turn_id fails."""
    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            "INSERT INTO artifacts (turn_id, content, content_length) VALUES (9999, 'x', 1)"
        )


def test_emails_unique_gmail_id(test_db):
    """Duplicate gmail_id is rejected."""
    test_db.execute(
        "INSERT INTO emails (gmail_id, body_text, content_length) VALUES ('abc', 'text', 4)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            "INSERT INTO emails (gmail_id, body_text, content_length) VALUES ('abc', 'other', 5)"
        )
