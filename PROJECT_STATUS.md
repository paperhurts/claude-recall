# PROJECT STATUS

## Last Updated: 2026-03-13

## Current State
claude-recall v0.1.1 on branch `feat/session1-fts5-search` — conversation extraction with full-text search working. 33 automated tests passing. Manual verification done against real data (~137 conversations extracted, search confirmed working).

## What Changed This Session (Session 1)
- Created implementation plan from approved spec
- **Schema**: Added artifacts + emails tables, FTS5 virtual tables (turns_fts, artifacts_fts, emails_fts), 9 sync triggers
- **db.py**: SQLite >= 3.29 version check, FTS-aware reset (triggers→FTS→views→tables), `_backfill_fts()`, `:memory:` support
- **search.py** (NEW): `claude-recall-search` CLI with BM25 ranking, source/date filters, `--context` flag, snippet highlighting, artifact title fallback, FTS5 syntax error handling
- **extractor.py**: Always calls `init_database()` (upgrade path for existing DBs), explicit artifact delete for FTS safety, wait up to 30s for SPA message rendering
- **33 tests** across test_schema.py, test_db.py, test_search.py
- Found: SQLite 3.50.4 fires triggers on CASCADE deletes (newer than spec assumed)
- Found: Plan's reset ordering had a bug (triggers must drop before FTS tables)
- Found: Large conversations need SPA wait — fixed with polling loop

## Branch Status
- Branch `feat/session1-fts5-search` has 13 commits ahead of main
- NOT YET MERGED — user should decide merge strategy next session
- All tests pass, search verified against real data

## Pending Work
- **Merge decision**: Merge feat branch to main (or create PR)
- **Re-extract failed conversations**: ~8 conversations still failed extraction (some may have Frazer content). Retry with `--url <uuid>` now that wait fix is in place
- **Session 2**: Artifact extraction (spec already approved)
- **Session 3**: Gmail OAuth ingestion (spec already approved)

## Key Files
- `docs/superpowers/plans/2026-03-13-session1-fts5-search.md` — implementation plan
- `docs/superpowers/specs/2026-03-13-siege-evidence-database-design.md` — approved design spec
- `claude_recall/search.py` — search CLI
- `claude_recall/schema.sql` — FTS5 tables, triggers, artifacts, emails
- `claude_recall/db.py` — version check, reset, backfill
- `.siege/SIEGE_Master_Playbook_v0.1.md` — SIEGE framework
