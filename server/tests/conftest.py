"""Shared test setup: the server's SQLite memory and the linked phones go to temp files, never server/."""

import pytest


@pytest.fixture(autouse=True)
def _memory_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGUEL_DB", str(tmp_path / "miguel.db"))
    monkeypatch.setenv("FAMILY_PHONES", str(tmp_path / "family-phones.json"))   # never server/family-phones.json
