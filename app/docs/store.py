"""Content-addressed file store under DATA_DIR/files: streamed in, hashed, committed atomically.

Blobs live at files/<sha[0:2]>/<sha[2:4]>/<sha256>. Writes go to files/.tmp/*.part first and are
moved into place with one os.replace, so a reader never sees a half-written file. All calls are
blocking: run them in a thread (asyncio.to_thread), never on the event loop.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.docs.ids import file_id_for
from app.docs.settings import DocsSettings

FILES_DIR = "files"
TMP_DIR = ".tmp"
_TMP_SUFFIX = ".part"


class TooLarge(Exception):
    """Raised by FileWriter.write the moment the bytes pass the writer's limit."""


@dataclass(frozen=True)
class StoredBlob:
    """A committed file: its hash, size and path relative to the data directory."""

    sha256: str
    size_bytes: int
    storage_path: str
    existed: bool  # the same bytes were already stored

    @property
    def file_id(self) -> str:
        """Public id derived from the hash."""
        return file_id_for(self.sha256)


class FileWriter:
    """Takes bytes chunk by chunk into a temp file, hashing as they arrive. Use as a context manager."""

    def __init__(self, store: "FileStore", limit: int, sniff_bytes: int) -> None:
        self._store = store
        self._limit = limit
        self._sniff = sniff_bytes
        self._hash = hashlib.sha256()
        fd, name = tempfile.mkstemp(dir=store.tmp_dir, suffix=_TMP_SUFFIX)
        self.temp_path = Path(name)
        self._fh: BinaryIO | None = os.fdopen(fd, "wb")
        self.size = 0
        self.first_bytes = b""
        self.sha256: str | None = None
        self._done = False

    def write(self, chunk: bytes) -> None:
        """Append a chunk; discard everything and raise TooLarge once past the limit."""
        if self._fh is None:
            raise ValueError("writer is closed")
        if self.size + len(chunk) > self._limit:
            self.discard()
            raise TooLarge(f"passed {self._limit} bytes")
        if len(self.first_bytes) < self._sniff:
            self.first_bytes += chunk[: self._sniff - len(self.first_bytes)]
        self._fh.write(chunk)
        self._hash.update(chunk)
        self.size += len(chunk)

    def close(self) -> str:
        """Finish writing (flushed to disk) and return the SHA-256; the file stays in the temp area."""
        if self._fh is not None:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
            self._fh = None
            self.sha256 = self._hash.hexdigest()
        if self.sha256 is None:
            raise ValueError("writer was discarded")
        return self.sha256

    def commit(self) -> StoredBlob:
        """Move the finished file to its hash path in one atomic step; same bytes are stored once."""
        sha = self.close()
        target = self._store.path_for(sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        if existed:
            self.temp_path.unlink(missing_ok=True)
        else:
            os.replace(self.temp_path, target)
        self._done = True
        return StoredBlob(sha, self.size, self._store.storage_path_for(sha), existed)

    def discard(self) -> None:
        """Drop the bytes written so far. Safe to call twice."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if not self._done:
            self.temp_path.unlink(missing_ok=True)
            self._done = True

    def __enter__(self) -> "FileWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.discard()


class FileStore:
    """Files kept under their SHA-256 below `<data_dir>/files`."""

    def __init__(self, settings: DocsSettings) -> None:
        self.settings = settings
        self.data_dir = Path(settings.data_dir).resolve()
        self.root = self.data_dir / FILES_DIR
        self.tmp_dir = self.root / TMP_DIR
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def writer(self, limit: int | None = None) -> FileWriter:
        """A new writer; `limit` defaults to the 250 MB setting."""
        return FileWriter(self, limit if limit is not None else self.settings.max_file_bytes,
                          self.settings.sniff_bytes)

    def storage_path_for(self, sha256: str) -> str:
        """Path relative to the data directory, as kept in FileRecord.storage_path."""
        return f"{FILES_DIR}/{sha256[0:2]}/{sha256[2:4]}/{sha256}"

    def path_for(self, sha256: str) -> Path:
        """Absolute path of a blob."""
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("not a sha256 hex digest")
        return self.data_dir / self.storage_path_for(sha256)

    def resolve(self, storage_path: str) -> Path:
        """Absolute path of a stored file; refuses anything outside the store."""
        path = (self.data_dir / storage_path).resolve()
        if not path.is_relative_to(self.root) or path.is_relative_to(self.tmp_dir):
            raise ValueError(f"not a stored file: {storage_path!r}")
        return path

    def exists(self, storage_path: str) -> bool:
        """True when the stored file is on disk."""
        return self.resolve(storage_path).is_file()

    def open(self, storage_path: str) -> BinaryIO:
        """Open a stored file for reading, e.g. for GET /files/{file_id}."""
        return open(self.resolve(storage_path), "rb")

    def remove(self, storage_path: str) -> bool:
        """Delete a stored file; False when it was not there."""
        path = self.resolve(storage_path)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def clean_temp(self) -> int:
        """Remove leftovers of interrupted writes (call at startup, before any writer runs)."""
        count = 0
        for p in self.tmp_dir.glob(f"*{_TMP_SUFFIX}"):
            p.unlink(missing_ok=True)
            count += 1
        return count
