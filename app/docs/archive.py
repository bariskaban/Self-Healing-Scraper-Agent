"""Unpacking ZIPs (nested ones too) into the store with the standard library, within our caps.

Every entry is stored under its own hash; the name inside the archive is only a display name.
Archive-wide caps (entry count, unpacked total, ratio, depth) are checked from the central
directory before anything is extracted. An archive over a cap, one with password-protected
entries, or one that cannot be read, is not
unpacked: `Unpacked.refused` says why, and the caller keeps its bytes as one plain file. The bytes
of an archive that was unpacked are not kept. Blocking: run in a thread.
"""
from __future__ import annotations

import mimetypes
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.docs.ids import skipped_entry_id
from app.docs.names import split_path, zip_entry_name
from app.docs.settings import DocsSettings
from app.docs.store import FileStore, FileWriter, TooLarge
from app.models import FileRecord, SkipReason, utcnow

ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")  # local file header; end of central directory (empty ZIP)
# ZIP containers that are documents, not archives: delivered as they are.
DOCUMENT_ZIP_EXTENSIONS = frozenset({
    ".docx", ".docm", ".dotx", ".xlsx", ".xlsm", ".xltx", ".pptx", ".pptm", ".ppsx", ".vsdx",
    ".odt", ".ods", ".odp", ".odg", ".ott", ".epub", ".jar", ".apk", ".xpi", ".kmz", ".3mf",
    ".asice", ".sce", ".bdoc", ".ipa",
})
_ENCRYPTED = 0x1 | 0x40  # traditional and strong encryption flags


def looks_like_archive(name: str | None, first_bytes: bytes, path: Path) -> bool:
    """A ZIP we should unpack: ZIP magic, readable, and not an Office/ODF/EPUB-style package."""
    if not first_bytes.startswith(ZIP_MAGIC):
        return False
    if name and PurePosixPath(name.lower()).suffix in DOCUMENT_ZIP_EXTENSIONS:
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return True  # unpack() will find it unreadable and keep it as a plain document
    names = {i.filename for i in infos}
    if "[Content_Types].xml" in names or (infos and infos[0].filename == "mimetype"):
        return False
    return True


@dataclass
class _Budget:
    bytes_left: int
    entries_left: int


@dataclass
class Unpacked:
    """Records from one archive tree, parents before children, and one-line notes for the log."""

    refused: str | None = None  # set when the archive was not unpacked; records is then empty
    records: list[FileRecord] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)  # file_id -> path inside the archive tree
    notes: list[str] = field(default_factory=list)

    def leaves(self) -> list[FileRecord]:
        """Entries a tender lists in place of the archive (not the nested archives themselves)."""
        return [r for r in self.records if not r.is_archive]


def _refusal(infos: list[zipfile.ZipInfo], archive_size: int, budget: _Budget,
             settings: DocsSettings) -> str | None:
    """Why this archive must not be unpacked, judged from its central directory; None if it may."""
    if any(i.flag_bits & _ENCRYPTED for i in infos):
        # We cannot open these entries. Kept whole, the archive still delivers every byte the
        # portal published; unpacked, the protected entries would be lost.
        return "it has password-protected entries"
    if len(infos) > budget.entries_left:
        return f"{len(infos)} entries, over the cap of {settings.max_entries}"
    wanted = [i for i in infos if i.file_size <= settings.max_file_bytes]
    total = _wanted_total(infos, settings)
    if total > budget.bytes_left:
        return f"unpacks to {total} bytes, over the cap of {settings.max_unpacked_bytes}"
    if total > settings.ratio_min_bytes and total / max(archive_size, 1) > settings.max_ratio:
        return f"unpacks to {total / max(archive_size, 1):.0f} times its size, over {settings.max_ratio:g}"
    for i in wanted:
        if i.file_size > settings.ratio_min_bytes and i.file_size / max(i.compress_size, 1) > settings.max_ratio:
            return f"entry compressed over {settings.max_ratio:g} to 1"
    return None


def unpack(store: FileStore, zip_path: Path, *, archive_sha256: str, archive_file_id: str,
           source_url: str, settings: DocsSettings, depth: int = 1, prefix: str = "",
           budget: _Budget | None = None) -> Unpacked:
    """Store every entry of the ZIP at zip_path; `refused` is set when it is unreadable or over a cap."""
    budget = budget or _Budget(settings.max_unpacked_bytes, settings.max_entries)
    out = Unpacked()
    label = f"'{prefix}'" if prefix else "The archive"
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as e:
        out.refused = f"unreadable as a ZIP ({e})"
    else:
        with zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            out.refused = _refusal(infos, zip_path.stat().st_size, budget, settings)
            if not out.refused:
                budget.entries_left -= len(infos)
                budget.bytes_left -= _wanted_total(infos, settings)
                for info in infos:
                    parts = [*([prefix] if prefix else []), *split_path(zip_entry_name(info))]
                    _unpack_entry(zf, info, "/".join(parts) or "file", out, store=store,
                                  archive_sha256=archive_sha256, archive_file_id=archive_file_id,
                                  source_url=source_url, settings=settings, depth=depth, budget=budget)
    if out.refused:
        out.notes.append(f"{label} was not unpacked: {out.refused}; kept as one file.")
    return out


def _wanted_total(infos: list[zipfile.ZipInfo], settings: DocsSettings) -> int:
    """Declared bytes of the entries we would extract (those not over the file limit)."""
    return sum(i.file_size for i in infos if i.file_size <= settings.max_file_bytes)


def _skip(out: Unpacked, path: str, reason: SkipReason, note: str, *, archive_sha256: str,
          archive_file_id: str, source_url: str, size: int | None) -> None:
    rec = FileRecord(file_id=skipped_entry_id(archive_sha256, path), size_bytes=size,
                     source_url=source_url, parent_file_id=archive_file_id, skipped=reason)
    out.records.append(rec)
    out.paths.setdefault(rec.file_id, path)
    out.notes.append(f"Skipped '{path}' in the archive: {note}.")


def _unpack_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo, path: str, out: Unpacked, *,
                  store: FileStore, archive_sha256: str, archive_file_id: str, source_url: str,
                  settings: DocsSettings, depth: int, budget: _Budget) -> None:
    ctx = dict(archive_sha256=archive_sha256, archive_file_id=archive_file_id, source_url=source_url)
    if info.file_size > settings.max_file_bytes:
        _skip(out, path, SkipReason.too_large, f"{info.file_size} bytes, over the limit",
              size=info.file_size, **ctx)
        return
    writer = store.writer(info.file_size)  # zipfile never yields more than the declared size
    with writer:
        try:
            with zf.open(info) as src:
                while chunk := src.read(settings.chunk_bytes):
                    writer.write(chunk)
        except TooLarge:
            _skip(out, path, SkipReason.too_large, "over the limit while unpacking", size=None, **ctx)
            return
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, OSError) as e:
            # No SkipReason fits a damaged entry; not_a_file is the closest.
            _skip(out, path, SkipReason.not_a_file, f"unreadable ({e})", size=info.file_size, **ctx)
            return
        sha = writer.close()
        _store_entry(writer, path, sha, out, store=store, source_url=source_url,
                     archive_file_id=archive_file_id, settings=settings, depth=depth, budget=budget)


def _store_entry(writer: FileWriter, path: str, sha: str, out: Unpacked, *, store: FileStore,
                 source_url: str, archive_file_id: str, settings: DocsSettings, depth: int,
                 budget: _Budget) -> None:
    name = path.rsplit("/", 1)[-1]
    file_id = sha[:16]
    if looks_like_archive(name, writer.first_bytes, writer.temp_path):
        if depth >= settings.max_depth:
            out.notes.append(f"'{path}' is an archive deeper than {settings.max_depth} levels; kept as one file.")
        else:
            nested = unpack(store, writer.temp_path, archive_sha256=sha, archive_file_id=file_id,
                            source_url=source_url, settings=settings, depth=depth + 1,
                            prefix=path, budget=budget)
            out.notes.extend(nested.notes)
            if not nested.refused:
                out.records.append(FileRecord(
                    file_id=file_id, sha256=sha, size_bytes=writer.size, content_type="application/zip",
                    source_url=source_url, parent_file_id=archive_file_id, is_archive=True,
                    downloaded_at=utcnow()))
                out.paths.setdefault(file_id, path)
                out.records.extend(nested.records)
                for fid, p in nested.paths.items():
                    out.paths.setdefault(fid, p)
                return  # nested archive bytes are not kept: only its entries are delivered
    blob = writer.commit()
    out.records.append(FileRecord(
        file_id=blob.file_id, sha256=blob.sha256, size_bytes=blob.size_bytes,
        content_type=mimetypes.guess_type(name)[0], storage_path=blob.storage_path,
        source_url=source_url, parent_file_id=archive_file_id, downloaded_at=utcnow()))
    out.paths.setdefault(blob.file_id, path)
