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

## Next Session — Start Here

**Priority 1: Fix thinking block backfill (issue #4)**
- `backfill_thinking.py` expands blocks but reads zero content — DOM selectors for reading expanded text are broken
- The expand/click selectors still work; it's the content-reading selector (`div.row-start-1.col-start-1`) that's stale
- Steps: open Chrome with `--remote-debugging-port=9222`, navigate to a conversation with thinking, expand a block, inspect the DOM, find the new selector, update `backfill_thinking.py`
- Also investigate #2: does the first-pass extractor now get full thinking content without needing backfill? (claude.ai may have changed)
- Test with: `python -m claude_recall.backfill_thinking --session-id <id>`

**Priority 2: Re-extract failed conversations** — ~8 still failed. Retry with `--url <uuid>`

**Priority 3: Artifact extraction** (Session 2 spec already approved)

**Priority 4: Gmail OAuth ingestion** (Session 3 spec already approved)

**Note:** Python scripts dir not on PATH. Use `python -m claude_recall.search` etc. instead of CLI names, or add `C:\Users\paper\AppData\Roaming\Python\Python314\Scripts` to PATH.

## Open Issues
- #2 — Investigate: do thinking blocks still need two-pass extraction?
- #3 — Add --backfill flag for single-command extraction
- #4 — Bug: backfill_thinking gets zero content (DOM selectors broken)

## Key Files
- `docs/superpowers/plans/2026-03-13-session1-fts5-search.md` — implementation plan
- `docs/superpowers/specs/2026-03-13-siege-evidence-database-design.md` — approved design spec
- `claude_recall/search.py` — search CLI
- `claude_recall/schema.sql` — FTS5 tables, triggers, artifacts, emails
- `claude_recall/db.py` — version check, reset, backfill
- `.siege/SIEGE_Master_Playbook_v0.1.md` — SIEGE framework
