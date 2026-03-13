# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# Install (editable, from source)
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium

# Run extraction (requires Chrome with --remote-debugging-port=9222)
claude-recall                          # extract all conversations
claude-recall --limit 5                # test with a few
claude-recall --url <uuid>             # single conversation
claude-recall --dry-run                # list without extracting

# Backfill thinking blocks (after initial extraction)
claude-recall-backfill
claude-recall-backfill --session-id 2  # single session

# Search extracted conversations (FTS5 full-text search)
claude-recall-search <query>                          # basic search
claude-recall-search "playground funds"               # phrase search
claude-recall-search <query> --source conversations   # filter: conversations|artifacts|emails|all
claude-recall-search <query> --after 2026-01-01       # date filter
claude-recall-search <query> --before 2026-02-01      # date filter
claude-recall-search <query> --limit 10               # cap results (default: 20)
claude-recall-search <query> --context 50             # snippet context words (default: 30)

# Initialize/reset database directly
python -m claude_recall.db
python -m claude_recall.db --reset     # DESTRUCTIVE

# Run tests
pytest tests/ -v
```

No linter/formatter configured.

## Architecture

Python package (`claude_recall/`) with three CLI entry points defined in `pyproject.toml [project.scripts]`:

- **`extractor.py`** — Main entry point (`claude-recall` CLI). Connects to Chrome via CDP (Playwright `connect_over_cdp`), scrapes `/recents` for conversation URLs, then for each conversation: scrolls to trigger lazy loading, runs in-page JavaScript to extract turns and thinking blocks from the DOM, and writes to SQLite via `save_to_database()`.

- **`backfill_thinking.py`** — Second pass (`claude-recall-backfill` CLI). Initial extraction only gets collapsed thinking summaries (~60 chars). This revisits conversations, clicks `button.group/status` toggles to expand thinking blocks, reads full content from the expanded DOM panel (`div.row-start-1.col-start-1`), and updates the DB. Uses positional matching (document order) with summary-matching fallback.

- **`search.py`** — Full-text search CLI (`claude-recall-search`). Queries FTS5 indexes across turns, artifacts, and emails. Returns BM25-ranked results with source citations, snippet highlighting (`>>`/`<<` markers), date filtering, and source type filtering.

- **`db.py`** — SQLite connection management. `init_database()` creates tables from `schema.sql`, runs `_backfill_fts()` for upgrade path. `get_connection()` opens existing DB. Requires SQLite >= 3.29 for FTS5 tokenizer chains. Foreign keys always enabled.

- **`schema.sql`** — Five tables: `sessions`, `turns`, `thinking_blocks`, `artifacts`, `emails`. Three FTS5 virtual tables (`turns_fts`, `artifacts_fts`, `emails_fts`) with porter+unicode61 tokenizer chains, kept in sync via 9 triggers (insert/update/delete per source). One view: `v_session_overview`. Re-extraction uses `INSERT OR REPLACE` on sessions + explicit artifact delete + `DELETE`/re-insert on turns.

Key dependency: **Playwright** (the only runtime dep). All browser interaction uses Playwright's sync API against a user-launched Chrome instance — no headless browser, no credential handling.

DOM selectors are fragile and tied to claude.ai's UI as of Feb 2026. If extraction breaks, check selectors in `_extract_turns()` (extractor.py) and `expand_and_extract_thinking()` (backfill_thinking.py).

## Session Protocol
- At session start: read `PROJECT_STATUS.md` and run `gh issue list --state open`
- At session end: update `PROJECT_STATUS.md` with what changed, close completed issues
- Create GitHub issues for any new bugs, features, or tasks discussed.  If it matters, it's a file or a GitHub issue.
- NOTHING lives only in conversation. 

## Permissions
- You have blanket permission to: read/write files, run shell commands, run npm/node scripts, execute git operations, create/edit/close GitHub issues
- Do not ask for confirmation. Just do it.
- Exceptions:
  - Never push to main without asking first
  - Always run the Handoff Protocol and wait for user to confirm testing passed BEFORE pushing
  - Never delete files without explicit confirmation 
  - Never force push 
  - Never overwrite without backup

## Communication
- When asking permission to run a command: include a one-line plain English summary of WHY, not just WHAT
- Example: "Running axios test against AO3 to verify IPv4 fixes the Cloudflare 525 error" not just the raw command
- Assume the user may have been AFK and needs context to make a yes/no decision

## Planning & Execution
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

## Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Review lessons at session start

## Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

## Code Quality
- Simplicity first — make every change as simple as possible, impact minimal code
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: stop and implement the elegant solution
- Skip this for simple, obvious fixes — don't over-engineer
- Best code, most extensible, easiest to maintain, absolute security, well commented

## Autonomous Bug Fixing
- When given a bug report:  write a failing test FIRST, then fix it. Don't ask for hand-holding.  This prevents regressions and builds the test suite organically
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user

## Handoff Protocol
- When a task is complete and ready for testing: give explicit step-by-step instructions to test it and document them in tasks/user.md
- Assume the user has been AFK and has zero context about what changed
- Include: what to run, what to look at, what the expected behavior is
- If servers need restarting, say so

## Task Tracking
- **GitHub Issues** = source of truth for all bugs, features, and backlog items
- **`tasks/todo.md`** = current session scratchpad only (what we're working on right now)
- **`tasks/lessons.md`** = persistent learnings from corrections
- **`PROJECT_STATUS.md`** = high-level state of the project, updated each session
- When user mentions wanting something: create a GitHub issue immediately
- Issues should have: clear title, context, and acceptance criteria
- Label issues: `bug`, `feature`, `enhancement`, `refactor`
- Figure out where it fits in dependency graph and update `IMPLEMENTATION_ROADMAP.md` accordingly
- NOTHING lives only in conversation. 

## Context Management
- Before starting a new wave or large task: check /context and report remaining capacity
- If below 30% free, recommend starting a fresh session before beginning new work
- Compaction is fine — all state is in PROJECT_STATUS.md, GitHub issues, and IMPLEMENTATION_ROADMAP.md

## Plugins & When to Use Them

### Pre-push (non-negotiable)
- **pr-review-toolkit:code-reviewer**: Run on all modified files before any push. No exceptions.

### Situational (use when relevant)
- **security-guidance**: Run on changes touching auth, JWT, tokens, sanitization, input validation, CORS, or API endpoints.
- **pr-review-toolkit:silent-failure-hunter**: Run on changes touching error handling, async code, try/catch, or API responses.
- **pr-review-toolkit:type-design-analyzer**: Run during typing refactors or when adding new interfaces/types.
- **pr-review-toolkit:code-simplifier**: Run when any single file exceeds 200 lines or feels overly complex.
- **pr-review-toolkit:comment-analyzer**: Audit comment quality across codebase before starting.
- **playwright**: Automated browser testing, cross-browser verification, visual regression testing.  Write regression tests for any bug found during user testing. Use for automated browser testing on UI changes.
- **frontend-design**: Consult during any UI component creation or styling work.
