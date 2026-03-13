# PROJECT STATUS

## Last Updated: 2026-03-13

## Current State
claude-recall v0.1.1 — conversation extraction with full-text search. Session 1 implementation complete on `feat/session1-fts5-search` branch. 33 automated tests passing. Awaiting manual verification (re-pull + search test) before merge.

## What Changed This Session
- Created implementation plan from approved spec
- Implemented Session 1: FTS5 schema, search CLI, pytest infrastructure
  - Added artifacts + emails tables to schema
  - Added FTS5 virtual tables (turns_fts, artifacts_fts, emails_fts) with sync triggers
  - Updated db.py: SQLite >= 3.29 version check, FTS-aware reset, FTS backfill, :memory: support
  - Created search.py: `claude-recall-search` CLI with BM25 ranking, source/date filters, snippet highlighting
  - Updated extractor.py: always call init_database() (upgrade path), explicit artifact delete for FTS safety
  - 33 tests across test_schema.py, test_db.py, test_search.py
- Found: SQLite 3.50.4 fires triggers on CASCADE deletes (newer behavior than spec assumed)
- Found: Plan's reset ordering had a bug (triggers must be dropped before FTS tables, not after)

## Pending: Manual Verification (Task 12)
Needs Chrome with `--remote-debugging-port=9222` and claude.ai login:
1. Reset DB: `python -m claude_recall.db --reset`
2. Re-pull: `claude-recall --limit 5` (smoke test), then `claude-recall` (full)
3. Verify FTS: `python -c "import sqlite3; c=sqlite3.connect('recall.db'); print('FTS rows:', c.execute('SELECT COUNT(*) FROM turns_fts').fetchone()[0])"`
4. Test search: `claude-recall-search "Frazer" --limit 10`
5. If all good: merge branch, close issue #1

## Delivery Plan (from spec)
- **Session 1**: FTS5 schema + search CLI + pytest suite + re-pull conversations ← DONE (pending verification)
- **Session 2**: Artifact extraction + re-pull with artifacts
- **Session 3**: Gmail OAuth ingestion (readonly) + security review

## Key Files
- `docs/superpowers/plans/2026-03-13-session1-fts5-search.md` — implementation plan
- `docs/superpowers/specs/2026-03-13-siege-evidence-database-design.md` — approved design spec
- `claude_recall/search.py` — NEW: search CLI
- `claude_recall/schema.sql` — UPDATED: FTS5 tables, triggers, artifacts, emails
- `claude_recall/db.py` — UPDATED: version check, reset, backfill
- `.siege/SIEGE_Master_Playbook_v0.1.md` — SIEGE framework
- `.siege/FRAZER/frazer/` — existing Frazer school research (9 docs)
