# claude-recall

Back up your Claude conversations when Anthropic's export feature isn't available.

## What this does

`claude-recall` connects to a running Chrome instance where you're logged into [claude.ai](https://claude.ai), iterates through your conversations, and extracts everything into a local SQLite database:

- **User messages** and **assistant responses** (full text)
- **Extended thinking blocks** (Claude's internal reasoning, with full content recovery)
- **Session metadata** (titles, models, turn counts, timestamps)

## Why

Anthropic's built-in data export feature is sometimes unavailable or broken for certain accounts. If you've had months of conversations and can't export them, this tool gives you a local backup.

## Limitations

- **claude.ai web only.** This tool scrapes the claude.ai web interface. It cannot extract conversations from Claude Desktop, Cowork mode, the API, or any other interface.
- **DOM-dependent.** The extraction relies on claude.ai's current DOM structure (as of February 2026). If Anthropic redesigns the interface, selectors may need updating.
- **Not real-time.** This is a batch backup tool, not a sync service.
- **Thinking blocks require two passes.** The initial extraction captures collapsed summary text. Run `backfill_thinking` afterward to expand and capture the full extended thinking content.

## Setup

### 1. Install

```bash
pip install claude-recall
```

Or from source:

```bash
git clone https://github.com/paperhurts/claude-recall.git
cd claude-recall
pip install -e .
```

### 2. Install Playwright browsers

```bash
playwright install chromium
```

### 3. Launch Chrome with remote debugging

You need Chrome running with the DevTools Protocol enabled. This lets claude-recall connect to your existing browser session (with your claude.ai login) without handling credentials.

**Windows:**
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

**Mac:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

**Linux:**
```bash
google-chrome --remote-debugging-port=9222
```

Make sure you're logged into claude.ai in that Chrome instance.

## Usage

### Extract all conversations

```bash
claude-recall
```

This creates `recall.db` in your current directory with all your conversations.

### Test with a few conversations first

```bash
claude-recall --limit 5
```

### Extract a single conversation

```bash
claude-recall --url <conversation-uuid>
```

The UUID is the last part of a claude.ai conversation URL:
`https://claude.ai/chat/abc123-def456-...` → `abc123-def456-...`

### List conversations without extracting

```bash
claude-recall --dry-run
```

### Backfill full thinking block content

After the initial extraction, thinking blocks contain only their collapsed summary (~60 chars). To get the full extended thinking text (often 1000+ chars):

```bash
claude-recall-backfill
```

This revisits each conversation, clicks to expand each thinking block in the DOM, and reads the full content.

### Options

| Flag | Description |
|------|-------------|
| `--db PATH` | Database path (default: `recall.db`) |
| `--limit N` | Max conversations to extract |
| `--url UUID` | Single conversation UUID |
| `--dry-run` | List conversations without extracting |
| `--cdp URL` | Chrome CDP endpoint (default: `http://localhost:9222`) |
| `--delay N` | Seconds between page loads (default: 2.0) |

## Database schema

Three tables:

- **sessions** — One row per conversation (UUID, title, model, turn counts)
- **turns** — Each message (role, content, code/tool/artifact/thinking flags)
- **thinking_blocks** — Extended thinking content linked to assistant turns

Query your data:

```sql
-- All conversations
SELECT title, turn_count, thinking_block_count FROM sessions;

-- Full conversation text
SELECT role, content FROM turns WHERE session_id = 1 ORDER BY turn_index;

-- Thinking blocks for a conversation
SELECT tb.content
FROM thinking_blocks tb
JOIN turns t ON tb.turn_id = t.turn_id
WHERE t.session_id = 1
ORDER BY t.turn_index, tb.block_index;
```

## How it works

1. Connects to Chrome via the [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/) (CDP), preserving your existing authentication
2. Navigates to claude.ai/recents and discovers all conversation URLs
3. For each conversation: scrolls to load all lazy content, then executes JavaScript in the page to extract turns and thinking blocks from the DOM
4. Stores everything in SQLite with foreign key relationships

The backfill step re-visits conversations and clicks each collapsed thinking block toggle to expand it, then reads the full content from the expanded DOM element.

## Origin

This tool was built as part of a research project studying LLM behavioral consistency. When Anthropic's export feature didn't work for the researcher's account during a 3-month study period, this extraction pipeline was the solution. It's been tested against 120+ conversations totaling 3,500+ turns and 1,400+ thinking blocks.

## License

MIT
