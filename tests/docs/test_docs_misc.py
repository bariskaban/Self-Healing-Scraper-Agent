"""File names, ids, disk room and removal order, settings."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.docs import (
    DocsSettings, choose_name, file_id_for, files_to_remove, has_room, is_hash_id,
    is_provisional_id, name_from_content_disposition, provisional_file_id, room_to_fetch,
)
from app.models import FileRecord


@pytest.mark.parametrize("value, expected", [
    ("attachment; filename*=UTF-8''%E2%82%AC%20rates.pdf; filename=\"rates.pdf\"", "€ rates.pdf"),
    ("attachment; filename=\"rates.pdf\"; filename*=utf-8''Za%C5%82%C4%85cznik%201.pdf", "Załącznik 1.pdf"),
    ("attachment; filename*=iso-8859-1'de'%DCbersicht.pdf", "Übersicht.pdf"),
    ('attachment; filename="a \\"q\\"; b.pdf"', 'a "q"; b.pdf'),
    ("attachment; filename=plain.pdf", "plain.pdf"),
    ('attachment; filename="../../etc/passwd"', "passwd"),
    ('inline; filename="Ã\x9cbersicht.pdf"', "Übersicht.pdf"),  # raw UTF-8 read as Latin-1
    ("attachment", None),
    (None, None),
])
def test_content_disposition(value, expected):
    assert name_from_content_disposition(value) == expected


def test_choose_name_order():
    cd = "attachment; filename=cd.pdf"
    assert choose_name("Portal name.pdf", cd, "https://x/u.pdf") == "Portal name.pdf"
    assert choose_name(None, cd, "https://x/u.pdf") == "cd.pdf"
    assert choose_name(None, None, "https://x/a/Plan%20B.pdf?x=1") == "Plan B.pdf"
    assert choose_name(None, None, "https://x/download", "application/pdf") == "download.pdf"
    assert choose_name(None, None, "https://x/") == "document"


def test_ids():
    sha = "ab" * 32
    assert file_id_for(sha) == "ab" * 8 and is_hash_id(file_id_for(sha))
    pid = provisional_file_id("p1", "T-1", "https://Portal.example/doc?b=2&a=1")
    assert pid == provisional_file_id("p1", "T-1", "https://portal.example/doc?a=1&b=2")
    assert pid != provisional_file_id("p1", "T-2", "https://portal.example/doc?a=1&b=2")
    assert len(pid) == 16 and is_provisional_id(pid) and not is_hash_id(pid)


def test_room_to_fetch():
    s = DocsSettings(min_free_bytes=1000)
    assert room_to_fetch(1500, s)
    assert room_to_fetch(1500, s, announced_size=500)
    assert not room_to_fetch(1500, s, announced_size=501)
    assert not room_to_fetch(999, s)


def test_has_room_reads_the_disk(tmp_path: Path):
    assert has_room(DocsSettings(data_dir=tmp_path / "not-yet", min_free_bytes=1))
    assert not has_room(DocsSettings(data_dir=tmp_path, min_free_bytes=10**18))


def _rec(fid: str, size: int, day: int = 1, stored: bool = True) -> FileRecord:
    return FileRecord(file_id=fid, sha256=fid * 4, size_bytes=size, source_url="u",
                      storage_path=f"files/{fid}" if stored else None,
                      downloaded_at=datetime(2026, 11, day, tzinfo=timezone.utc))


def test_files_to_remove():
    shared, big, small, old, unstored, open_only = (
        _rec("a", 500), _rec("b", 900), _rec("c", 100, 2), _rec("d", 100, 1), _rec("e", 1, stored=False),
        _rec("f", 10_000))
    uses = [(shared, True), (shared, False), (big, True), (small, True), (old, True), (old, True),
            (unstored, True), (open_only, False)]
    assert [r.file_id for r in files_to_remove(uses)] == ["b", "d", "c"]
    assert [r.file_id for r in files_to_remove(uses, need_bytes=950)] == ["b", "d"]
    assert files_to_remove(uses, need_bytes=0) == []


def test_settings_from_env(tmp_path):
    s = DocsSettings.from_env({"DATA_DIR": str(tmp_path), "DOCS_MAX_FILE_BYTES": "123",
                               "DOCS_MAX_RATIO": "7.5"})
    assert s.data_dir == tmp_path and s.max_file_bytes == 123 and s.max_ratio == 7.5
    assert DocsSettings.from_env({}).max_file_bytes == 250_000_000
    with pytest.raises(ValueError):
        DocsSettings(max_depth=0)
