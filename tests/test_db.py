"""Tests for db.py: version check, reset ordering, FTS backfill."""

import sqlite3
import tempfile
from pathlib import Path as TmpPath
from unittest.mock import patch
import pytest
from claude_recall.db import init_database


def test_sqlite_version_sufficient():
    """init_database succeeds when SQLite version is >= 3.29."""
    conn = init_database(":memory:")
    conn.close()


def test_sqlite_version_too_old():
    """init_database raises RuntimeError when SQLite < 3.29."""
    with patch.object(sqlite3, "sqlite_version_info", (3, 28, 0)):
        with pytest.raises(RuntimeError, match="3.29"):
            init_database(":memory:")
