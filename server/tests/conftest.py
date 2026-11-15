"""Shared test setup: the server's SQLite memory goes to a temp file, never server/miguel.db."""

import pytest


@pytest.fixture(autouse=True)
def _memory_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGUEL_DB", str(tmp_path / "miguel.db"))
