"""
Backfill full thinking block content from claude.ai conversations.

The initial extraction captures only the collapsed summary text for thinking
blocks (typically ~60 chars). This script revisits conversations, expands each
thinking block in the DOM, reads the full extended thinking text, and updates
the database.

DOM structure (as of Feb 2026):
  <div class="grid grid-rows-[auto] min-w-0">
    <button class="group/status ..." aria-expanded>    <- toggle
    <div class="grid transition-[grid-template-rows]"  <- expandable container
         style="grid-template-rows: 0fr | 1fr">
      <div class="row-start-1 col-start-1 min-w-0">   <- content panel
        <div class="min-w-0 pl-2 py-1.5">             <- actual thinking text
          ...paragraphs...
        </div>
      </div>
    </div>
  </div>

Strategy:
  1. Find all button.group/status elements (thinking block toggles)
  2. Click collapsed ones (aria-expanded="false") to expand
  3. Read full text from div.row-start-1.col-start-1.min-w-0
  4. Update database with full content

Prerequisites:
  Same as extractor.py -- Chrome running with --remote-debugging-port=9222

Usage:
    python -m claude_recall.backfill_thinking                      # all sessions
    python -m claude_recall.backfill_thinking --session-id 2       # single session
    python -m claude_recall.backfill_thinking --limit 5            # test with 5
    python -m claude_recall.backfill_thinking --dry-run            # preview
"""

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

from claude_recall.db import DEFAULT_DB

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CDP_ENDPOINT = "http://localhost:9222"
BASE_URL = "https://claude.ai"
PAGE_LOAD_TIMEOUT = 90_000  # ms
DELAY_BETWEEN_PAGES = 2.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")


# ---------------------------------------------------------------------------
# Thinking block extraction
# ---------------------------------------------------------------------------
def expand_and_extract_thinking(page: Page) -> list[dict]:
    """Expand all thinking blocks and extract their full content.

    Returns list of dicts: [{summary, content, position, contentLength, gotFullContent}, ...]
    """

    # Step 1: Count thinking blocks and expand collapsed ones
    block_count = page.evaluate("""
    () => {
        const buttons = Array.from(document.querySelectorAll('button'))
            .filter(btn => {
                const cls = btn.className || '';
                return (cls.includes('group/status') || cls.includes('group\\\\/status'))
                    && btn.hasAttribute('aria-expanded');
            });

        let expandedCount = 0;
        for (const btn of buttons) {
            if (btn.getAttribute('aria-expanded') === 'false') {
                btn.click();
                expandedCount++;
            }
        }

        return { total: buttons.length, expanded: expandedCount };
    }
    """)

    log.info(f"    Found {block_count['total']} thinking blocks, "
             f"expanded {block_count['expanded']} collapsed ones")

    if block_count['total'] == 0:
        return []

    # Step 2: Wait for expansion animations
    if block_count['expanded'] > 0:
        time.sleep(1.0 + block_count['expanded'] * 0.05)

    # Step 3: Read all expanded thinking block content
    blocks = page.evaluate("""
    () => {
        const results = [];

        const buttons = Array.from(document.querySelectorAll('button'))
            .filter(btn => {
                const cls = btn.className || '';
                return (cls.includes('group/status') || cls.includes('group\\\\/status'))
                    && btn.hasAttribute('aria-expanded');
            });

        for (const btn of buttons) {
            // Summary text
            const summarySpan = btn.querySelector('span.truncate') ||
                                btn.querySelector('span[class*="truncate"]');
            const summary = summarySpan ? summarySpan.innerText.trim() : btn.innerText.trim();

            // Full content
            let content = '';
            const parent = btn.parentElement;
            if (parent) {
                // Find expandable grid container
                const expandableGrid = parent.querySelector(
                    'div[class*="transition-"][class*="grid-template-rows"]'
                );

                if (expandableGrid) {
                    const contentPanel = expandableGrid.querySelector(
                        '.row-start-1.col-start-1'
                    ) || expandableGrid.querySelector(
                        'div[class*="row-start-1"][class*="col-start-1"]'
                    );
                    if (contentPanel) {
                        content = contentPanel.innerText.trim();
                    }
                }

                // Fallback: sibling approach
                if (!content) {
                    let sibling = btn.nextElementSibling;
                    while (sibling) {
                        if (sibling.tagName === 'DIV') {
                            const panel = sibling.querySelector(
                                '.row-start-1.col-start-1'
                            ) || sibling.querySelector(
                                'div[class*="row-start-1"]'
                            );
                            if (panel) {
                                content = panel.innerText.trim();
                                break;
                            }
                            const text = sibling.innerText.trim();
                            if (text.length > 100) {
                                content = text;
                                break;
                            }
                        }
                        sibling = sibling.nextElementSibling;
                    }
                }

                // Last resort: parent's sibling
                if (!content && parent.nextElementSibling) {
                    const panel = parent.nextElementSibling.querySelector(
                        '.row-start-1.col-start-1'
                    );
                    if (panel) {
                        content = panel.innerText.trim();
                    }
                }
            }

            results.push({
                summary: summary,
                content: content || summary,
                position: btn.getBoundingClientRect().top + window.scrollY,
                contentLength: content.length,
                gotFullContent: content.length > summary.length,
            });
        }

        results.sort((a, b) => a.position - b.position);
        return results;
    }
    """)

    got_full = sum(1 for b in blocks if b.get('gotFullContent', False))
    avg_len = sum(b.get('contentLength', 0) for b in blocks) / max(len(blocks), 1)
    log.info(f"    Content: {got_full}/{len(blocks)} got full text, avg length={avg_len:.0f}")

    return blocks


def extract_thinking_for_session(page: Page, uuid: str, title: str) -> list[dict]:
    """Navigate to a conversation and extract all thinking block content."""
    url = f"{BASE_URL}/chat/{uuid}"
    log.info(f"  Loading: {title[:60]}...")

    page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
    time.sleep(4)

    # Scroll through entire conversation to load all lazy content
    scroll_count = 0
    for _ in range(200):
        old_height = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.3)
        new_height = page.evaluate("document.body.scrollHeight")
        scroll_count += 1
        if new_height == old_height:
            time.sleep(1.0)
            final_height = page.evaluate("document.body.scrollHeight")
            if final_height == new_height:
                break

    log.info(f"    Scrolled {scroll_count} times to load full conversation")

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)

    blocks = expand_and_extract_thinking(page)
    return blocks


# ---------------------------------------------------------------------------
# Database update
# ---------------------------------------------------------------------------
def update_thinking_blocks(conn: sqlite3.Connection, session_id: int,
                           blocks: list[dict]) -> int:
    """Update thinking_blocks table with full content.

    Matching strategy: correlate by position order. Both DB blocks and
    extracted blocks are in document order, so they align 1:1. Falls
    back to summary matching when counts don't align.
    """
    cursor = conn.cursor()

    existing = cursor.execute("""
        SELECT tb.block_id, tb.content, tb.content_length, t.turn_index
        FROM thinking_blocks tb
        JOIN turns t ON tb.turn_id = t.turn_id
        WHERE t.session_id = ?
        ORDER BY t.turn_index, tb.block_index
    """, (session_id,)).fetchall()

    if not existing:
        log.info(f"    No existing thinking blocks to update")
        return 0

    updated = 0

    if len(blocks) == len(existing):
        # Perfect alignment
        for (block_id, old_content, old_len, _), new_block in zip(existing, blocks):
            new_content = new_block["content"]
            if len(new_content) > len(old_content):
                cursor.execute("""
                    UPDATE thinking_blocks
                    SET content = ?, content_length = ?
                    WHERE block_id = ?
                """, (new_content, len(new_content), block_id))
                updated += 1

    elif len(blocks) > 0:
        # Count mismatch -- use summary matching
        log.warning(f"    Block count mismatch: {len(existing)} in DB vs "
                    f"{len(blocks)} extracted. Using summary matching.")

        used_block_ids = set()

        for new_block in blocks:
            summary = new_block.get("summary", "")
            content = new_block["content"]

            if len(content) <= 50:
                continue

            best_match = None
            best_score = 0

            for block_id, old_content, old_len, _ in existing:
                if block_id in used_block_ids:
                    continue

                old_stripped = old_content.strip()
                if old_stripped in summary or summary.startswith(old_stripped[:30]):
                    score = len(old_stripped) + 100
                elif old_stripped[:20] in content[:200]:
                    score = len(old_stripped)
                else:
                    continue

                if score > best_score:
                    best_score = score
                    best_match = block_id

            if best_match:
                cursor.execute("""
                    UPDATE thinking_blocks
                    SET content = ?, content_length = ?
                    WHERE block_id = ?
                """, (content, len(content), best_match))
                used_block_ids.add(best_match)
                updated += 1

    conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Backfill thinking block content from claude.ai"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--session-id", type=int, help="Single session to process")
    parser.add_argument("--limit", type=int, default=0, help="Max sessions")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cdp", type=str, default=CDP_ENDPOINT)
    parser.add_argument("--delay", type=float, default=DELAY_BETWEEN_PAGES)
    args = parser.parse_args()

    if not args.db.exists():
        log.error(f"Database not found: {args.db}. Run the extractor first.")
        sys.exit(1)

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys = ON")

    # Find sessions with thinking blocks
    if args.session_id:
        sessions = conn.execute("""
            SELECT s.session_id, s.claude_uuid, s.title, s.thinking_block_count
            FROM sessions s
            WHERE s.session_id = ? AND s.thinking_block_count > 0
        """, (args.session_id,)).fetchall()
    else:
        sessions = conn.execute("""
            SELECT s.session_id, s.claude_uuid, s.title, s.thinking_block_count
            FROM sessions s
            WHERE s.thinking_block_count > 0
            ORDER BY s.thinking_block_count DESC
        """).fetchall()

    if args.limit > 0:
        sessions = sessions[:args.limit]

    log.info(f"Sessions with thinking blocks: {len(sessions)}")

    if args.dry_run:
        total_blocks = 0
        print(f"\n{'#':>3}  {'ID':>4}  {'Blocks':>6}  Title")
        print("-" * 80)
        for i, (sid, uuid, title, count) in enumerate(sessions):
            print(f"{i+1:3d}  {sid:4d}  {count:6d}  {title[:55]}")
            total_blocks += count
        print(f"\nTotal: {len(sessions)} sessions, {total_blocks} thinking blocks")
        return

    with sync_playwright() as p:
        log.info(f"Connecting to Chrome via CDP at {args.cdp}...")
        try:
            browser = p.chromium.connect_over_cdp(args.cdp)
        except Exception as e:
            log.error(f"Could not connect to Chrome CDP: {e}")
            sys.exit(1)

        context = browser.contexts[0]
        page = context.new_page()

        total = len(sessions)
        total_updated = 0
        total_extracted = 0
        sessions_with_updates = 0

        for i, (session_id, uuid, title, block_count) in enumerate(sessions):
            log.info(f"\n[{i+1}/{total}] Session {session_id} ({block_count} blocks)")
            try:
                blocks = extract_thinking_for_session(page, uuid, title)
                total_extracted += len(blocks)

                if blocks:
                    updated = update_thinking_blocks(conn, session_id, blocks)
                    total_updated += updated
                    if updated > 0:
                        sessions_with_updates += 1
                    log.info(f"    Updated {updated}/{block_count} blocks in DB")
                else:
                    log.warning(f"    No thinking blocks found in DOM")

            except Exception as e:
                log.error(f"    Failed: {e}", exc_info=True)

            if i < total - 1:
                time.sleep(args.delay)

        page.close()

    conn.close()
    log.info(f"\nBackfill complete:")
    log.info(f"  Sessions processed: {total}")
    log.info(f"  Sessions with updates: {sessions_with_updates}")
    log.info(f"  Blocks extracted: {total_extracted}")
    log.info(f"  Blocks updated in DB: {total_updated}")


if __name__ == "__main__":
    main()
