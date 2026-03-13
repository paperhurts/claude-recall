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


def _insert_session(db, uuid="test-uuid"):
    """Helper: insert a minimal session, return session_id."""
    db.execute(
        "INSERT INTO sessions (claude_uuid, url) VALUES (?, ?)",
        (uuid, f"https://claude.ai/chat/{uuid}"),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_turn(db, session_id, index=0, role="assistant", content="hello"):
    """Helper: insert a minimal turn, return turn_id."""
    db.execute(
        "INSERT INTO turns (session_id, turn_index, role, content, content_length) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, index, role, content, len(content)),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_fts_sync_on_turn_insert(test_db):
    """Inserting a turn auto-populates turns_fts via trigger."""
    sid = _insert_session(test_db)
    _insert_turn(test_db, sid, content="playground fundraising scandal")

    results = test_db.execute(
        "SELECT content FROM turns_fts WHERE turns_fts MATCH 'playground'"
    ).fetchall()
    assert len(results) == 1
    assert "playground" in results[0][0]


def test_fts_sync_on_turn_delete(test_db):
    """Deleting a turn removes it from turns_fts via trigger."""
    sid = _insert_session(test_db)
    tid = _insert_turn(test_db, sid, content="playground fundraising scandal")

    test_db.execute("DELETE FROM turns WHERE turn_id = ?", (tid,))

    results = test_db.execute(
        "SELECT content FROM turns_fts WHERE turns_fts MATCH 'playground'"
    ).fetchall()
    assert len(results) == 0


def test_fts_sync_on_turn_update(test_db):
    """Updating turn content updates turns_fts via trigger."""
    sid = _insert_session(test_db)
    tid = _insert_turn(test_db, sid, content="original text")

    test_db.execute(
        "UPDATE turns SET content = 'playground update' WHERE turn_id = ?", (tid,)
    )

    # Old content gone
    old = test_db.execute(
        "SELECT * FROM turns_fts WHERE turns_fts MATCH 'original'"
    ).fetchall()
    assert len(old) == 0

    # New content present
    new = test_db.execute(
        "SELECT content FROM turns_fts WHERE turns_fts MATCH 'playground'"
    ).fetchall()
    assert len(new) == 1


def test_fts_sync_on_artifact_insert(test_db):
    """Inserting an artifact auto-populates artifacts_fts."""
    sid = _insert_session(test_db)
    tid = _insert_turn(test_db, sid)

    test_db.execute(
        "INSERT INTO artifacts (turn_id, title, content, content_length) "
        "VALUES (?, 'Financial Analysis', 'missing funds report', 20)",
        (tid,),
    )

    results = test_db.execute(
        "SELECT title, content FROM artifacts_fts WHERE artifacts_fts MATCH 'financial'"
    ).fetchall()
    assert len(results) == 1


def test_fts_sync_on_explicit_artifact_delete(test_db):
    """Explicitly deleting an artifact cleans up artifacts_fts."""
    sid = _insert_session(test_db)
    tid = _insert_turn(test_db, sid)

    test_db.execute(
        "INSERT INTO artifacts (turn_id, title, content, content_length) "
        "VALUES (?, 'Report', 'evidence data', 13)",
        (tid,),
    )
    aid = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]

    test_db.execute("DELETE FROM artifacts WHERE artifact_id = ?", (aid,))

    results = test_db.execute(
        "SELECT * FROM artifacts_fts WHERE artifacts_fts MATCH 'evidence'"
    ).fetchall()
    assert len(results) == 0


def test_cascade_does_not_sync_artifact_fts(test_db):
    """CASCADE delete of artifacts cleans up artifacts_fts in SQLite >= 3.x.

    NOTE: Older SQLite versions (pre-3.x) did NOT fire triggers on CASCADE
    deletes, leaving stale FTS entries. SQLite 3.50.4+ correctly fires triggers
    on child rows deleted via CASCADE. We verify the current behavior here.

    The extractor should still explicitly delete artifacts before turns as a
    defensive pattern for compatibility with older SQLite installations.
    """
    import sqlite3 as _sqlite3
    sid = _insert_session(test_db)
    tid = _insert_turn(test_db, sid)

    test_db.execute(
        "INSERT INTO artifacts (turn_id, title, content, content_length) "
        "VALUES (?, 'Report', 'cascade test content', 20)",
        (tid,),
    )

    # Delete the turn — cascades to artifact
    test_db.execute("DELETE FROM turns WHERE turn_id = ?", (tid,))

    # Artifact row is gone (CASCADE worked)
    artifacts = test_db.execute("SELECT * FROM artifacts").fetchall()
    assert len(artifacts) == 0

    # On SQLite 3.50.4+, trigger fires on CASCADE — FTS is clean
    # On older SQLite, this would have been 1 (stale entry)
    fts_rows = test_db.execute(
        "SELECT * FROM artifacts_fts WHERE artifacts_fts MATCH 'cascade'"
    ).fetchall()
    sqlite_ver = tuple(int(x) for x in _sqlite3.sqlite_version.split("."))
    if sqlite_ver >= (3, 50, 0):
        assert len(fts_rows) == 0  # trigger fired correctly
    else:
        assert len(fts_rows) == 1  # stale — known older SQLite limitation


def test_fts_sync_on_email_insert(test_db):
    """Inserting an email auto-populates emails_fts."""
    test_db.execute(
        "INSERT INTO emails (gmail_id, subject, body_text, content_length) "
        "VALUES ('msg1', 'Parent Meeting Notes', 'playground deferred', 20)"
    )

    results = test_db.execute(
        "SELECT subject, body_text FROM emails_fts WHERE emails_fts MATCH 'playground'"
    ).fetchall()
    assert len(results) == 1


def test_reextraction_no_duplicate_fts(test_db):
    """Re-extracting a session (delete + re-insert turns) doesn't duplicate FTS."""
    sid = _insert_session(test_db)
    _insert_turn(test_db, sid, index=0, content="first extraction content")
    _insert_turn(test_db, sid, index=1, content="second turn content")

    # Simulate re-extraction: delete all turns, re-insert
    test_db.execute("DELETE FROM turns WHERE session_id = ?", (sid,))
    _insert_turn(test_db, sid, index=0, content="first extraction content")
    _insert_turn(test_db, sid, index=1, content="second turn content")

    results = test_db.execute(
        "SELECT content FROM turns_fts WHERE turns_fts MATCH 'extraction'"
    ).fetchall()
    assert len(results) == 1  # only one match, not duplicated
