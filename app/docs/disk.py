"""Disk space: whether to fetch, and which stored files to remove first when space runs low (Q12)."""
from __future__ import annotations

import shutil
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from app.docs.settings import DocsSettings
from app.models import FileRecord

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


def free_bytes(path: Path) -> int:
    """Free bytes on the file system holding `path` (its nearest existing parent)."""
    path = Path(path).absolute()
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def room_to_fetch(free: int, settings: DocsSettings, announced_size: int | None = None) -> bool:
    """True when the download fits and still leaves the setting's minimum free."""
    return free - (announced_size or 0) >= settings.min_free_bytes


def has_room(settings: DocsSettings, announced_size: int | None = None) -> bool:
    """room_to_fetch for the data directory as it is now."""
    return room_to_fetch(free_bytes(settings.data_dir), settings, announced_size)


def files_to_remove(uses: Iterable[tuple[FileRecord, bool]], need_bytes: int | None = None) -> list[FileRecord]:
    """Stored files to remove first, from (file, its tender is closed) pairs, one pair per link.

    Only files whose every linking tender is closed; never a file an open tender still links to.
    Largest first, then oldest, so the fewest files free the space. With `need_bytes`, only as
    many as free at least that much.
    """
    files: dict[str, FileRecord] = {}
    still_open: set[str] = set()
    for rec, closed in uses:
        if not closed:
            still_open.add(rec.file_id)
        if rec.storage_path:
            files.setdefault(rec.file_id, rec)
    candidates = sorted(
        (r for fid, r in files.items() if fid not in still_open),
        key=lambda r: (-(r.size_bytes or 0), r.downloaded_at or _OLDEST, r.file_id),
    )
    if need_bytes is None:
        return candidates
    out: list[FileRecord] = []
    freed = 0
    for rec in candidates:
        if freed >= need_bytes:
            break
        out.append(rec)
        freed += rec.size_bytes or 0
    return out
