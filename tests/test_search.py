"""Tests for search.py: search_all(), formatting, filters."""

import sqlite3
import pytest
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "claude_recall" / "schema.sql"


@pytest.fixture
def search_db():
    """In-memory DB pre-populated with test data for search tests."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("PRAGMA foreign_keys = ON")

    # Session 1
    conn.execute(
        "INSERT INTO sessions (claude_uuid, title, url, created_at) "
        "VALUES ('uuid-1', 'Frazer School Investigation', "
        "'https://claude.ai/chat/uuid-1', '2026-01-15')"
    )
    sid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "INSERT INTO turns (session_id, turn_index, role, content, content_length) "
        "VALUES (?, 0, 'user', 'Tell me about the playground funds', 35)",
        (sid1,),
    )
    conn.execute(
        "INSERT INTO turns (session_id, turn_index, role, content, content_length) "
        "VALUES (?, 1, 'assistant', 'The playground funds totaling approximately "
        "$10,000 were raised by Dr. Dudas through parent contributions.', 90)",
        (sid1,),
    )
    tid_art = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "INSERT INTO artifacts (turn_id, title, content, content_length) "
        "VALUES (?, 'Financial Analysis Draft', "
        "'Missing Funds: playground fundraising $10-12K raised, $0 spent', 55)",
        (tid_art,),
    )

    # Session 2 (different topic)
    conn.execute(
        "INSERT INTO sessions (claude_uuid, title, url, created_at) "
        "VALUES ('uuid-2', 'Python Debugging Session', "
        "'https://claude.ai/chat/uuid-2', '2026-02-01')"
    )
    sid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "INSERT INTO turns (session_id, turn_index, role, content, content_length) "
        "VALUES (?, 0, 'user', 'How do I fix this TypeError?', 28)",
        (sid2,),
    )

    # Email
    conn.execute(
        "INSERT INTO emails (gmail_id, subject, sender, date, body_text, content_length) "
        "VALUES ('email-1', 'Re: Parent Meeting Notes', 'principal@frazer.edu', "
        "'2026-01-10', 'The playground project has been deferred to next year', 52)"
    )

    conn.commit()
    yield conn
    conn.close()


def test_search_finds_turn(search_db):
    """Search for a term that exists in a turn."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground")
    assert len(results) > 0
    turn_results = [r for r in results if r["source_type"] == "conversation"]
    assert len(turn_results) >= 1


def test_search_finds_artifact(search_db):
    """Search finds artifacts by content."""
    from claude_recall.search import search_all

    results = search_all(search_db, "Financial Analysis")
    artifact_results = [r for r in results if r["source_type"] == "artifact"]
    assert len(artifact_results) >= 1


def test_search_finds_email(search_db):
    """Search finds emails by body text."""
    from claude_recall.search import search_all

    results = search_all(search_db, "deferred")
    email_results = [r for r in results if r["source_type"] == "email"]
    assert len(email_results) == 1


def test_search_source_filter_conversations(search_db):
    """--source conversations only returns conversation turns."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground", source_filter="conversations")
    for r in results:
        assert r["source_type"] == "conversation"


def test_search_source_filter_artifacts(search_db):
    """--source artifacts only returns artifacts."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground", source_filter="artifacts")
    for r in results:
        assert r["source_type"] == "artifact"


def test_search_source_filter_emails(search_db):
    """--source emails only returns emails."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground", source_filter="emails")
    for r in results:
        assert r["source_type"] == "email"


def test_search_date_filter_after(search_db):
    """--after filters out older results."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground", after="2026-01-12")
    dates = [r.get("date", "") for r in results]
    for d in dates:
        if d:
            assert d >= "2026-01-12"


def test_search_date_filter_before(search_db):
    """--before filters out newer results."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground", before="2026-01-12")
    dates = [r.get("date", "") for r in results]
    for d in dates:
        if d:
            assert d <= "2026-01-12"


def test_search_limit(search_db):
    """--limit caps the number of results."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground", limit=1)
    assert len(results) <= 1


def test_search_no_results(search_db):
    """Search for nonexistent term returns empty list."""
    from claude_recall.search import search_all

    results = search_all(search_db, "xyznonexistent")
    assert results == []


def test_search_result_has_citation_fields(search_db):
    """Each result has the required citation fields."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground")
    assert len(results) > 0

    for r in results:
        assert "source_type" in r
        assert "snippet" in r
        assert "rank" in r
        if r["source_type"] == "conversation":
            assert "url" in r
            assert "session_title" in r


def test_search_ranking_order(search_db):
    """Results are sorted by BM25 rank (best first)."""
    from claude_recall.search import search_all

    results = search_all(search_db, "playground")
    if len(results) >= 2:
        ranks = [r["rank"] for r in results]
        assert ranks == sorted(ranks, reverse=True)


def test_search_empty_fts_returns_empty(test_db):
    """Search on empty DB returns empty list, not error."""
    from claude_recall.search import search_all

    results = search_all(test_db, "anything")
    assert results == []


def test_format_no_results():
    """format_results with empty list gives clear message."""
    from claude_recall.search import format_results

    output = format_results([])
    assert "NO RESULTS" in output


def test_search_invalid_fts_syntax_raises_value_error(search_db):
    """Invalid FTS5 query syntax raises ValueError, not OperationalError."""
    from claude_recall.search import search_all

    with pytest.raises(ValueError, match="Invalid FTS5 query syntax"):
        search_all(search_db, "AND AND")
