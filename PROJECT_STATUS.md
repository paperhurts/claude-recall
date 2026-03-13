# PROJECT STATUS

## Last Updated: 2026-03-13

## Current State
claude-recall v0.1.1 on branch `feat/session1-fts5-search` — conversation extraction with full-text search working. 38 automated tests passing. Manual verification done against real data (~137 conversations extracted, search confirmed working).

## What Changed This Session (Session 2 — PR Review Fixes)
- Ran comprehensive 6-agent parallel PR review (code, comments, tests, errors, types, simplify)
- **CRITICAL fix**: Empty `catch(e) {}` in browser JS now logs selector errors via `console.warn`
- **db.py**: Replaced `executescript` with individual `execute()` calls in `_backfill_fts` for atomicity; removed redundant PRAGMA re-enable
- **search.py**: Switched from positional `row[0]..row[9]` to `sqlite3.Row` named access; added `source_filter` validation; FTS-missing tables now show upgrade instructions; `context_tokens` bounded [1,500]; `Counter` for source counting; improved artifact title-only match fallback
- **extractor.py**: Fixed misleading CASCADE comment (now says "may not fire on older versions")
- **tests**: 33 → 38 tests. Added: artifact/email backfill, title-only artifact match, format_results with data, invalid source_filter, missing FTS tables. Renamed misleading test.
- **CLAUDE.md**: Added search CLI docs, updated architecture section

## Previous Session (Session 1)
- Created implementation plan from approved spec
- Schema: Added artifacts + emails tables, FTS5 virtual tables, 9 sync triggers
- search.py (NEW): `claude-recall-search` CLI with BM25 ranking, source/date filters, snippet highlighting
- extractor.py: upgrade path, explicit artifact delete, SPA wait loop
- 33 tests across test_schema.py, test_db.py, test_search.py

## Branch Status
- Branch `feat/session1-fts5-search` has ~20 commits ahead of main
- NOT YET MERGED — user should decide merge strategy
- All 38 tests pass, search verified against real data

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
