"""Documents: bytes from a download link to content-addressed files on disk (DESIGN.md, Modules).

No network request here: the network layer (app/fetch) hands over a `Download`. All functions
block; call them in a thread, off the event loop. `outcome_judge` is the file test of app/checks
(Q10, rule O2) in the shape `store_document` takes.
"""
from app.docs.archive import Unpacked, looks_like_archive, unpack
from app.docs.disk import files_to_remove, free_bytes, has_room, room_to_fetch
from app.docs.document import (
    Announced, Download, DocumentResult, FileFacts, Judge, StaticDownload, announced_too_large,
    store_document,
)
from app.docs.ids import file_id_for, is_hash_id, is_provisional_id, provisional_file_id
from app.docs.judge import outcome_judge, plain_answer
from app.docs.names import choose_name, name_from_content_disposition
from app.docs.settings import DocsSettings
from app.docs.store import FileStore, FileWriter, StoredBlob, TooLarge

__all__ = [
    "Announced", "DocsSettings", "DocumentResult", "Download", "FileFacts", "FileStore",
    "FileWriter", "Judge", "StaticDownload", "StoredBlob", "TooLarge", "Unpacked",
    "announced_too_large", "choose_name", "file_id_for", "files_to_remove", "free_bytes",
    "has_room", "is_hash_id", "is_provisional_id", "looks_like_archive",
    "name_from_content_disposition", "outcome_judge", "plain_answer", "provisional_file_id",
    "room_to_fetch", "store_document", "unpack",
]
