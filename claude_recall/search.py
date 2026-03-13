"""
Full-text search across claude-recall database.

Queries FTS5 indexes across conversation turns, artifacts, and emails.
Returns results ranked by BM25 relevance with source citations.

Usage:
    claude-recall-search <query>
    claude-recall-search <query> --source conversations|artifacts|emails|all
    claude-recall-search <query> --after YYYY-MM-DD --before YYYY-MM-DD
    claude-recall-search <query> --limit N
    claude-recall-search <query> --context N
    claude-recall-search <query> --db path/to.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from claude_recall.db import get_connection, DEFAULT_DB


def search_all(
    conn: sqlite3.Connection,
    query: str,
    *,
    source_filter: str = "all",
    after: Optional[str] = None,
    before: Optional[str] = None,
    limit: int = 20,
    context_tokens: int = 30,
) -> list[dict]:
    """Search FTS5 indexes and return ranked results with citations.

    Args:
        conn: Database connection.
        query: FTS5 query string.
        source_filter: "all", "conversations", "artifacts", or "emails".
        after: ISO date string -- exclude results before this date.
        before: ISO date string -- exclude results after this date.
        limit: Maximum results to return.
        context_tokens: Approximate tokens of context in snippets (default 30).

    Returns:
        List of result dicts sorted by BM25 rank (best first).
    """
    results = []

    try:
        if source_filter in ("all", "conversations"):
            results.extend(_search_turns(conn, query, after, before, context_tokens))

        if source_filter in ("all", "artifacts"):
            results.extend(_search_artifacts(conn, query, after, before, context_tokens))

        if source_filter in ("all", "emails"):
            results.extend(_search_emails(conn, query, after, before, context_tokens))
    except sqlite3.OperationalError as e:
        if "fts5: syntax error" in str(e).lower() or "parse error" in str(e).lower():
            raise ValueError(
                f"Invalid FTS5 query syntax: {query!r}. "
                f"Use double quotes for phrases, OR for alternatives. Error: {e}"
            ) from e
        raise

    # Sort by rank descending (higher = more relevant)
    results.sort(key=lambda r: r["rank"], reverse=True)

    return results[:limit]


def _search_turns(conn, query, after, before, context_tokens=30):
    """Search conversation turns via turns_fts."""
    sql = f"""
        SELECT
            snippet(turns_fts, 0, '>>', '<<', '...', {int(context_tokens)}) AS snippet,
            -rank AS relevance,
            t.turn_id,
            t.turn_index,
            t.role,
            s.title AS session_title,
            s.url,
            s.created_at
        FROM turns_fts
        JOIN turns t ON t.turn_id = turns_fts.rowid
        JOIN sessions s ON s.session_id = t.session_id
        WHERE turns_fts MATCH ?
    """
    params = [query]

    if after:
        sql += " AND s.created_at >= ?"
        params.append(after)
    if before:
        sql += " AND s.created_at <= ?"
        params.append(before)

    sql += " ORDER BY rank"

    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    return [
        {
            "source_type": "conversation",
            "snippet": row["snippet"],
            "rank": row["relevance"],
            "turn_id": row["turn_id"],
            "turn_index": row["turn_index"],
            "role": row["role"],
            "session_title": row["session_title"],
            "url": row["url"],
            "date": row["created_at"] or "",
        }
        for row in rows
    ]


def _search_artifacts(conn, query, after, before, context_tokens=30):
    """Search artifacts via artifacts_fts.

    When a match is in the title only (content snippet is empty),
    falls back to showing the title + first N chars of content.
    """
    sql = f"""
        SELECT
            snippet(artifacts_fts, 1, '>>', '<<', '...', {int(context_tokens)}) AS content_snippet,
            snippet(artifacts_fts, 0, '>>', '<<', '...', {int(context_tokens)}) AS title_snippet,
            -rank AS relevance,
            a.artifact_id,
            a.title AS artifact_title,
            a.artifact_type,
            s.title AS session_title,
            s.url,
            s.created_at,
            substr(a.content, 1, 200) AS content_preview
        FROM artifacts_fts
        JOIN artifacts a ON a.artifact_id = artifacts_fts.rowid
        JOIN turns t ON t.turn_id = a.turn_id
        JOIN sessions s ON s.session_id = t.session_id
        WHERE artifacts_fts MATCH ?
    """
    params = [query]

    if after:
        sql += " AND s.created_at >= ?"
        params.append(after)
    if before:
        sql += " AND s.created_at <= ?"
        params.append(before)

    sql += " ORDER BY rank"

    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    results = []
    for row in rows:
        # If content snippet is empty/ellipsis-only, use title + content preview
        snippet = row["content_snippet"]
        if not snippet or snippet.strip() == "...":
            snippet = f"Title: {row['title_snippet']}\n  {row['content_preview'] or ''}"

        results.append({
            "source_type": "artifact",
            "snippet": snippet,
            "rank": row["relevance"],
            "artifact_id": row["artifact_id"],
            "artifact_title": row["artifact_title"],
            "artifact_type": row["artifact_type"],
            "session_title": row["session_title"],
            "url": row["url"],
            "date": row["created_at"] or "",
        })
    return results


def _search_emails(conn, query, after, before, context_tokens=30):
    """Search emails via emails_fts."""
    sql = f"""
        SELECT
            snippet(emails_fts, 1, '>>', '<<', '...', {int(context_tokens)}) AS snippet,
            -rank AS relevance,
            e.email_id,
            e.subject,
            e.sender,
            e.date
        FROM emails_fts
        JOIN emails e ON e.email_id = emails_fts.rowid
        WHERE emails_fts MATCH ?
    """
    params = [query]

    if after:
        sql += " AND e.date >= ?"
        params.append(after)
    if before:
        sql += " AND e.date <= ?"
        params.append(before)

    sql += " ORDER BY rank"

    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    return [
        {
            "source_type": "email",
            "snippet": row["snippet"],
            "rank": row["relevance"],
            "email_id": row["email_id"],
            "subject": row["subject"],
            "sender": row["sender"],
            "date": row["date"] or "",
        }
        for row in rows
    ]


def format_results(results: list[dict]) -> str:
    """Format search results for CLI output."""
    if not results:
        return "=== NO RESULTS ==="

    source_counts = {}
    for r in results:
        source_counts[r["source_type"]] = source_counts.get(r["source_type"], 0) + 1

    source_summary = ", ".join(
        f"{count} {stype}{'s' if count != 1 else ''}"
        for stype, count in sorted(source_counts.items())
    )
    lines = [f"=== RESULTS ({len(results)} matches: {source_summary}) ===\n"]

    for i, r in enumerate(results, 1):
        if r["source_type"] == "conversation":
            lines.append(f"--- [{i}] Conversation Turn (rank: {r['rank']:.2f}) ---")
            lines.append(
                f"Source: Conv \"{r['session_title']}\" | "
                f"Turn {r['turn_index']} ({r['role']}) | {r['date']}"
            )
            lines.append(f"URL: {r['url']}")
        elif r["source_type"] == "artifact":
            lines.append(f"--- [{i}] Artifact (rank: {r['rank']:.2f}) ---")
            lines.append(
                f"Source: Artifact \"{r.get('artifact_title', '')}\" | "
                f"from Conv \"{r['session_title']}\" | {r['date']}"
            )
            lines.append(f"URL: {r['url']}")
        elif r["source_type"] == "email":
            lines.append(f"--- [{i}] Email (rank: {r['rank']:.2f}) ---")
            lines.append(
                f"Source: Email \"{r.get('subject', '')}\" | "
                f"from: {r.get('sender', '')} | {r['date']}"
            )

        lines.append(f"Snippet:\n  {r['snippet']}\n")

    lines.append("=== END RESULTS ===")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search claude-recall database via FTS5"
    )
    parser.add_argument("query", help="Search query (FTS5 syntax)")
    parser.add_argument(
        "--source",
        choices=["conversations", "artifacts", "emails", "all"],
        default="all",
        help="Filter by source type (default: all)",
    )
    parser.add_argument("--after", help="Only results after this date (YYYY-MM-DD)")
    parser.add_argument("--before", help="Only results before this date (YYYY-MM-DD)")
    parser.add_argument(
        "--limit", type=int, default=20, help="Max results (default: 20)"
    )
    parser.add_argument(
        "--context", type=int, default=30,
        help="Approximate tokens of context in snippets (default: 30)"
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help="Database path"
    )
    args = parser.parse_args()

    try:
        conn = get_connection(args.db)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run 'claude-recall' first to create and populate the database.", file=sys.stderr)
        sys.exit(1)

    # Warn if FTS tables are empty
    fts_count = conn.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0]
    if fts_count == 0:
        print(
            "Warning: FTS indexes are empty. Run 'claude-recall' to extract "
            "conversations, then 'python -m claude_recall.db' to backfill FTS.",
            file=sys.stderr,
        )

    try:
        results = search_all(
            conn,
            args.query,
            source_filter=args.source,
            after=args.after,
            before=args.before,
            limit=args.limit,
            context_tokens=args.context,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_results(results))
    conn.close()


if __name__ == "__main__":
    main()
