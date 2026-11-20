"""Fixtures for app/docs tests: a store in tmp_path, a stand-in judge, ZIP builders."""
from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from app.docs import DocsSettings, FileFacts, FileStore
from app.models import SkipReason

PDF = b"%PDF-1.7\n" + b"x" * 200


def stand_in_judge(facts: FileFacts) -> SkipReason | None:
    """Trivial stand-in for app/checks' file outcome test (O2)."""
    if not 200 <= facts.status < 300:
        return SkipReason.http_error
    head = facts.first_bytes.lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html")):
        return SkipReason.login_required if b"password" in facts.first_bytes else SkipReason.not_a_file
    if facts.size_bytes == 0:
        return SkipReason.not_a_file
    return None


def make_zip(entries: list[tuple[str, bytes]], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """A ZIP built in memory; names kept exactly as given (traversal and absolute ones too)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in entries:
            zf.writestr(zipfile.ZipInfo(name), data, compress_type=compression)
    return buf.getvalue()


def blobs(store: FileStore) -> list[Path]:
    """Every committed file in the store."""
    return sorted(p for p in store.root.rglob("*") if p.is_file() and store.tmp_dir not in p.parents)


def temp_files(store: FileStore) -> list[Path]:
    """Every half-written file in the store's temp area."""
    return sorted(store.tmp_dir.iterdir())


@pytest.fixture
def settings(tmp_path: Path) -> DocsSettings:
    return DocsSettings(data_dir=tmp_path / "data")


@pytest.fixture
def store(settings: DocsSettings) -> FileStore:
    return FileStore(settings)


@pytest.fixture
def make_store(settings: DocsSettings):
    def _make(**changes) -> FileStore:
        return FileStore(replace(settings, **changes))
    return _make
