-- claude-recall: Claude Conversation Backup Tool
-- SQLite Schema
--
-- Stores conversations extracted from claude.ai when the built-in
-- export feature is unavailable or insufficient.

PRAGMA foreign_keys = ON;

-- ============================================================
-- SESSIONS: One row per claude.ai conversation
-- ============================================================
CREATE TABLE IF NOT EXISTS sessions (
    session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    claude_uuid     TEXT UNIQUE NOT NULL,          -- UUID from claude.ai URL
    title           TEXT,                           -- conversation title from UI
    url             TEXT NOT NULL,                  -- full claude.ai URL
    created_at      TEXT,                           -- ISO 8601, from UI if available
    extracted_at    TEXT NOT NULL DEFAULT (datetime('now')),
    model           TEXT,                           -- e.g. 'claude-sonnet-4-5-20250929'

    -- Session-level counts
    turn_count      INTEGER DEFAULT 0,
    user_turn_count INTEGER DEFAULT 0,
    assistant_turn_count INTEGER DEFAULT 0,
    thinking_block_count INTEGER DEFAULT 0,
    total_user_tokens INTEGER DEFAULT 0,
    total_assistant_tokens INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);


-- ============================================================
-- TURNS: Each user or assistant message within a session
-- ============================================================
CREATE TABLE IF NOT EXISTS turns (
    turn_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,              -- 0-based position in conversation
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,                  -- raw text content
    content_length  INTEGER NOT NULL,
    token_estimate  INTEGER,                       -- chars / 4 approximation

    has_code_blocks BOOLEAN DEFAULT 0,
    has_tool_use    BOOLEAN DEFAULT 0,
    has_artifacts   BOOLEAN DEFAULT 0,
    has_thinking    BOOLEAN DEFAULT 0,

    extracted_at    TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(session_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_role ON turns(role);


-- ============================================================
-- THINKING_BLOCKS: Extended thinking content from assistant turns
-- ============================================================
CREATE TABLE IF NOT EXISTS thinking_blocks (
    block_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id         INTEGER NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
    block_index     INTEGER NOT NULL DEFAULT 0,
    content         TEXT NOT NULL,
    content_length  INTEGER NOT NULL,

    extracted_at    TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(turn_id, block_index)
);

CREATE INDEX IF NOT EXISTS idx_thinking_turn ON thinking_blocks(turn_id);


-- ============================================================
-- ARTIFACTS: Code, text, and other artifacts from assistant turns
-- ============================================================
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id         INTEGER NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
    artifact_index  INTEGER NOT NULL DEFAULT 0,
    title           TEXT,
    artifact_type   TEXT,
    language        TEXT,
    content         TEXT NOT NULL,
    content_length  INTEGER NOT NULL,
    extracted_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(turn_id, artifact_index)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_turn ON artifacts(turn_id);


-- ============================================================
-- EMAILS: Gmail messages ingested by label
-- ============================================================
CREATE TABLE IF NOT EXISTS emails (
    email_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id        TEXT UNIQUE NOT NULL,
    thread_id       TEXT,
    subject         TEXT,
    sender          TEXT,
    recipients      TEXT,
    date            TEXT,
    body_text       TEXT,
    body_html       TEXT,
    labels          TEXT,
    has_attachments BOOLEAN DEFAULT 0,
    content_length  INTEGER NOT NULL,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);


-- ============================================================
-- FTS5: Full-text search indexes (standalone mode)
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    content,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
    title,
    content,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    subject,
    body_text,
    tokenize='porter unicode61'
);


-- ============================================================
-- TRIGGERS: Keep FTS indexes in sync with source tables
-- ============================================================

-- Turns triggers
CREATE TRIGGER IF NOT EXISTS turns_fts_insert AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, content) VALUES (new.turn_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS turns_fts_update AFTER UPDATE OF content ON turns BEGIN
    DELETE FROM turns_fts WHERE rowid = old.turn_id;
    INSERT INTO turns_fts(rowid, content) VALUES (new.turn_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS turns_fts_delete AFTER DELETE ON turns BEGIN
    DELETE FROM turns_fts WHERE rowid = old.turn_id;
END;

-- Artifacts triggers
CREATE TRIGGER IF NOT EXISTS artifacts_fts_insert AFTER INSERT ON artifacts BEGIN
    INSERT INTO artifacts_fts(rowid, title, content)
    VALUES (new.artifact_id, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS artifacts_fts_update AFTER UPDATE OF title, content ON artifacts BEGIN
    DELETE FROM artifacts_fts WHERE rowid = old.artifact_id;
    INSERT INTO artifacts_fts(rowid, title, content)
    VALUES (new.artifact_id, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS artifacts_fts_delete AFTER DELETE ON artifacts BEGIN
    DELETE FROM artifacts_fts WHERE rowid = old.artifact_id;
END;

-- Emails triggers
CREATE TRIGGER IF NOT EXISTS emails_fts_insert AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(rowid, subject, body_text)
    VALUES (new.email_id, new.subject, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS emails_fts_update AFTER UPDATE OF subject, body_text ON emails BEGIN
    DELETE FROM emails_fts WHERE rowid = old.email_id;
    INSERT INTO emails_fts(rowid, subject, body_text)
    VALUES (new.email_id, new.subject, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS emails_fts_delete AFTER DELETE ON emails BEGIN
    DELETE FROM emails_fts WHERE rowid = old.email_id;
END;


-- ============================================================
-- VIEW: Session overview
-- ============================================================
CREATE VIEW IF NOT EXISTS v_session_overview AS
SELECT
    s.session_id,
    s.claude_uuid,
    s.title,
    s.created_at,
    s.model,
    s.turn_count,
    s.user_turn_count,
    s.assistant_turn_count,
    s.thinking_block_count,
    s.total_user_tokens,
    s.total_assistant_tokens
FROM sessions s
ORDER BY s.extracted_at DESC;
