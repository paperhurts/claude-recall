"""
Playwright-based extractor for claude.ai conversations.

Connects to a running Chrome instance via CDP (Chrome DevTools Protocol),
iterates through conversation URLs, and extracts:
  - User turns (via [data-testid="user-message"])
  - Assistant responses (via parent container traversal)
  - Thinking blocks (collapsed summary text — use backfill_thinking for full content)
  - Session metadata (title, model, turn counts)

Prerequisites:
  1. Chrome must be running with remote debugging enabled:
     Windows:  chrome.exe --remote-debugging-port=9222
     Mac:      /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
     Linux:    google-chrome --remote-debugging-port=9222

  2. You must be logged into claude.ai in that Chrome instance.

Usage:
    python -m claude_recall.extractor                    # extract all
    python -m claude_recall.extractor --limit 5          # test with 5
    python -m claude_recall.extractor --url <uuid>       # single conversation
    python -m claude_recall.extractor --dry-run          # list URLs only
"""

import argparse
import logging
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser

from claude_recall.db import init_database, DEFAULT_DB

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CDP_ENDPOINT = "http://localhost:9222"
BASE_URL = "https://claude.ai"
RECENTS_URL = f"{BASE_URL}/recents"
DELAY_BETWEEN_PAGES = 2.0  # seconds
PAGE_LOAD_TIMEOUT = 30_000  # ms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("claude-recall")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Turn:
    turn_index: int
    role: str  # 'user' | 'assistant'
    content: str
    has_code_blocks: bool = False
    has_tool_use: bool = False
    has_artifacts: bool = False
    has_thinking: bool = False
    thinking_blocks: list[str] = field(default_factory=list)


@dataclass
class ConversationData:
    claude_uuid: str
    url: str
    title: str = ""
    model: str = ""
    turns: list[Turn] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Conversation list extraction
# ---------------------------------------------------------------------------
def get_conversation_urls(page: Page) -> list[dict]:
    """Navigate to /recents and extract all conversation URLs + titles.

    Returns list of dicts: [{"uuid": "...", "url": "...", "title": "..."}, ...]
    """
    log.info("Navigating to recents page...")
    page.goto(RECENTS_URL, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
    time.sleep(3)

    # Click "Show more" until all conversations are loaded
    for _ in range(50):
        show_more = page.query_selector('button:has-text("Show more")')
        if not show_more:
            break
        conversations = page.query_selector_all('a[href*="/chat/"]')
        log.info(f"  Loaded {len(conversations)} so far, clicking 'Show more'...")
        show_more.click()
        time.sleep(2)

    # Extract URLs and titles
    results = []
    seen_uuids = set()

    conversations = page.query_selector_all('a[href*="/chat/"]')
    for elem in conversations:
        href = elem.get_attribute("href") or ""
        match = re.search(r'/chat/([a-f0-9-]+)', href)
        if not match:
            continue
        uuid = match.group(1)
        if uuid in seen_uuids:
            continue
        seen_uuids.add(uuid)

        title = elem.inner_text().strip()
        title = title.split('\n')[0].strip()

        results.append({
            "uuid": uuid,
            "url": f"{BASE_URL}/chat/{uuid}",
            "title": title,
        })

    log.info(f"Found {len(results)} unique conversations")
    return results


# ---------------------------------------------------------------------------
# Single conversation extraction
# ---------------------------------------------------------------------------
def extract_conversation(page: Page, conv: dict) -> ConversationData:
    """Extract all turns and thinking blocks from a single conversation."""
    url = conv["url"]
    log.info(f"Extracting: {conv['title'][:60]}...")

    page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)

    # Wait for conversation messages to actually render (SPA loads async)
    for _ in range(30):
        if page.query_selector('[data-testid="user-message"]'):
            break
        time.sleep(1)

    _scroll_to_load_all(page)

    data = ConversationData(
        claude_uuid=conv["uuid"],
        url=url,
        title=conv["title"],
    )

    data.model = _extract_model(page)
    data.turns = _extract_turns(page)

    return data


def _scroll_to_load_all(page: Page):
    """Scroll through the conversation to trigger lazy loading."""
    for _ in range(100):
        old_height = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.5)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == old_height:
            break
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)


def _extract_model(page: Page) -> str:
    """Try to extract the model name from the page."""
    selectors = [
        '[data-testid="model-selector"]',
        'button[aria-label*="model"]',
        '.model-name',
    ]
    for sel in selectors:
        elem = page.query_selector(sel)
        if elem:
            text = elem.inner_text().strip()
            if text:
                return text
    return ""


def _extract_turns(page: Page) -> list[Turn]:
    """Extract all user and assistant turns from the conversation DOM.

    Uses JavaScript to walk the DOM tree in document order within the browser,
    which is more reliable than Python-side traversal.
    """
    turn_data = page.evaluate("""
    () => {
        const results = [];

        // User turns
        const userMessages = document.querySelectorAll('[data-testid="user-message"]');
        userMessages.forEach((el) => {
            results.push({
                type: 'user',
                position: el.getBoundingClientRect().top + window.scrollY,
                content: el.innerText || '',
                hasCodeBlocks: el.querySelectorAll('pre code, .code-block').length > 0,
            });
        });

        // Assistant turns
        const assistantContainers = document.querySelectorAll(
            '[data-testid="assistant-message"], ' +
            '.font-claude-message, ' +
            '[class*="assistant"], ' +
            '[data-is-streaming]'
        );

        let assistantElements = [];
        if (assistantContainers.length === 0) {
            const allMessages = document.querySelectorAll(
                '[data-testid*="message"], .message, [class*="Message"]'
            );
            allMessages.forEach(el => {
                if (el.matches('[data-testid="user-message"]') ||
                    el.closest('[data-testid="user-message"]')) {
                    return;
                }
                const text = el.innerText || '';
                if (text.length > 10) {
                    assistantElements.push(el);
                }
            });
        } else {
            assistantElements = Array.from(assistantContainers);
        }

        assistantElements.forEach(el => {
            const thinkingBlocks = [];
            const thinkingSelectors = [
                'button.group\\\\/status',
                '[class*="thinking"]',
                '[data-testid*="thinking"]',
                'details summary',
            ];

            const parent = el.closest('[class*="group"]') || el.parentElement;
            if (parent) {
                thinkingSelectors.forEach(sel => {
                    try {
                        const thinkingEls = parent.querySelectorAll(sel);
                        thinkingEls.forEach(te => {
                            const content = te.closest('details')?.querySelector(':not(summary)')?.innerText
                                || te.nextElementSibling?.innerText
                                || te.parentElement?.querySelector('[class*="content"]')?.innerText
                                || '';
                            if (content.trim()) {
                                thinkingBlocks.push(content.trim());
                            }
                        });
                    } catch(e) {}
                });
            }

            results.push({
                type: 'assistant',
                position: el.getBoundingClientRect().top + window.scrollY,
                content: el.innerText || '',
                hasCodeBlocks: el.querySelectorAll('pre code, .code-block, [class*="code"]').length > 0,
                hasToolUse: el.querySelectorAll('[class*="tool"], [data-testid*="tool"]').length > 0,
                hasArtifacts: el.querySelectorAll('[class*="artifact"], [data-testid*="artifact"]').length > 0,
                thinkingBlocks: thinkingBlocks,
            });
        });

        results.sort((a, b) => a.position - b.position);
        return results;
    }
    """)

    turns = []
    for idx, td in enumerate(turn_data):
        turn = Turn(
            turn_index=idx,
            role=td["type"],
            content=td["content"],
            has_code_blocks=td.get("hasCodeBlocks", False),
            has_tool_use=td.get("hasToolUse", False),
            has_artifacts=td.get("hasArtifacts", False),
            has_thinking=len(td.get("thinkingBlocks", [])) > 0,
            thinking_blocks=td.get("thinkingBlocks", []),
        )
        turns.append(turn)

    return turns


# ---------------------------------------------------------------------------
# Database writing
# ---------------------------------------------------------------------------
def save_to_database(conn: sqlite3.Connection, data: ConversationData):
    """Write extracted conversation data to the database."""
    cursor = conn.cursor()

    user_turns = [t for t in data.turns if t.role == "user"]
    assistant_turns = [t for t in data.turns if t.role == "assistant"]
    thinking_count = sum(len(t.thinking_blocks) for t in data.turns)

    total_user_tokens = sum(len(t.content) // 4 for t in user_turns)
    total_assistant_tokens = sum(len(t.content) // 4 for t in assistant_turns)

    cursor.execute("""
        INSERT OR REPLACE INTO sessions (
            claude_uuid, title, url, model,
            turn_count, user_turn_count, assistant_turn_count,
            thinking_block_count, total_user_tokens, total_assistant_tokens
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.claude_uuid, data.title, data.url, data.model,
        len(data.turns), len(user_turns), len(assistant_turns),
        thinking_count, total_user_tokens, total_assistant_tokens,
    ))

    session_id = cursor.execute(
        "SELECT session_id FROM sessions WHERE claude_uuid = ?",
        (data.claude_uuid,)
    ).fetchone()[0]

    # Explicitly delete artifacts before turns — CASCADE deletes don't fire
    # FTS triggers on all SQLite versions, so we delete artifacts directly
    # to keep FTS in sync
    cursor.execute("""
        DELETE FROM artifacts WHERE turn_id IN (
            SELECT turn_id FROM turns WHERE session_id = ?
        )
    """, (session_id,))

    # Clear existing turns for this session (in case of re-extraction)
    cursor.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))

    for turn in data.turns:
        cursor.execute("""
            INSERT INTO turns (
                session_id, turn_index, role, content, content_length,
                token_estimate, has_code_blocks, has_tool_use,
                has_artifacts, has_thinking
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, turn.turn_index, turn.role, turn.content,
            len(turn.content), len(turn.content) // 4,
            turn.has_code_blocks, turn.has_tool_use,
            turn.has_artifacts, turn.has_thinking,
        ))

        turn_id = cursor.lastrowid

        for block_idx, block_content in enumerate(turn.thinking_blocks):
            cursor.execute("""
                INSERT INTO thinking_blocks (
                    turn_id, block_index, content, content_length
                ) VALUES (?, ?, ?, ?)
            """, (turn_id, block_idx, block_content, len(block_content)))

    conn.commit()
    log.info(
        f"  Saved: {len(data.turns)} turns, "
        f"{thinking_count} thinking blocks -> session_id={session_id}"
    )
    return session_id


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Extract claude.ai conversations via Playwright CDP"
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB,
        help="Database path (default: recall.db)"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max conversations to extract (0 = all)"
    )
    parser.add_argument(
        "--url", type=str, default="",
        help="Single conversation UUID to extract"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List conversation URLs without extracting"
    )
    parser.add_argument(
        "--cdp", type=str, default=CDP_ENDPOINT,
        help=f"Chrome CDP endpoint (default: {CDP_ENDPOINT})"
    )
    parser.add_argument(
        "--delay", type=float, default=DELAY_BETWEEN_PAGES,
        help=f"Delay between page loads in seconds (default: {DELAY_BETWEEN_PAGES})"
    )
    args = parser.parse_args()

    # Initialize or upgrade database (init_database handles both new and existing)
    if not args.dry_run:
        conn = init_database(args.db)

    with sync_playwright() as p:
        log.info(f"Connecting to Chrome via CDP at {args.cdp}...")
        try:
            browser: Browser = p.chromium.connect_over_cdp(args.cdp)
        except Exception as e:
            log.error(
                f"Could not connect to Chrome CDP. Make sure Chrome is running with:\n"
                f"  chrome --remote-debugging-port=9222\n"
                f"Error: {e}"
            )
            sys.exit(1)

        context = browser.contexts[0]
        page = context.new_page()

        if args.url:
            conversations = [{
                "uuid": args.url,
                "url": f"{BASE_URL}/chat/{args.url}",
                "title": "(single extraction)",
            }]
        else:
            conversations = get_conversation_urls(page)

        if args.dry_run:
            print(f"\n{'#':>4}  {'UUID':36s}  Title")
            print("-" * 80)
            for i, conv in enumerate(conversations):
                print(f"{i+1:4d}  {conv['uuid']:36s}  {conv['title'][:40]}")
            print(f"\nTotal: {len(conversations)} conversations")
            return

        if args.limit > 0:
            conversations = conversations[:args.limit]
            log.info(f"Limited to {args.limit} conversations")

        total = len(conversations)
        extracted = 0
        failed = 0

        for i, conv in enumerate(conversations):
            log.info(f"\n[{i+1}/{total}] {conv['uuid']}")
            try:
                data = extract_conversation(page, conv)
                if data.turns:
                    save_to_database(conn, data)
                    extracted += 1
                else:
                    log.warning(f"  No turns extracted -- skipping")
                    failed += 1
            except Exception as e:
                log.error(f"  Failed: {e}")
                failed += 1

            if i < total - 1:
                time.sleep(args.delay)

        page.close()

    log.info(f"\nExtraction complete: {extracted} extracted, {failed} failed")

    if not args.dry_run:
        # Print summary
        cursor = conn.execute(
            "SELECT COUNT(*), SUM(turn_count), SUM(thinking_block_count) FROM sessions"
        )
        sessions, turns, blocks = cursor.fetchone()
        log.info(f"Database totals: {sessions} sessions, {turns} turns, {blocks or 0} thinking blocks")
        conn.close()


if __name__ == "__main__":
    main()
