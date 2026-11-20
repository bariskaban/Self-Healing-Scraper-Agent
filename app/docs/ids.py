"""File ids: hash-derived once the bytes are in, provisional before."""
from __future__ import annotations

import hashlib
import re

from app.models import url_key

FILE_ID_LEN = 16
PROVISIONAL_PREFIX = "p"  # not a hex digit, so a provisional id never equals a hash-derived one

_HASH_ID = re.compile(r"^[0-9a-f]{16}$")


def file_id_for(sha256: str) -> str:
    """Public id in /files/{file_id}: the first 16 hex characters of the SHA-256."""
    return sha256[:FILE_ID_LEN]


def is_hash_id(file_id: str) -> bool:
    """True for an id derived from stored bytes."""
    return bool(_HASH_ID.match(file_id))


def is_provisional_id(file_id: str) -> bool:
    """True for an id given to a document whose bytes we do not hold."""
    return file_id.startswith(PROVISIONAL_PREFIX) and len(file_id) == FILE_ID_LEN


def _provisional(*parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return PROVISIONAL_PREFIX + digest[: FILE_ID_LEN - len(PROVISIONAL_PREFIX)]


def provisional_file_id(portal_id: str, tender_id: str, source_url: str) -> str:
    """Stable id for a known document not fetched (or skipped): same inputs, same id, on every read."""
    return _provisional("doc", portal_id, tender_id, url_key(source_url))


def skipped_entry_id(archive_sha256: str, path_in_archive: str) -> str:
    """Stable id for an archive entry we did not unpack (too large, encrypted, unreadable)."""
    return _provisional("entry", archive_sha256, path_in_archive)
