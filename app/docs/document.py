"""One document end to end: from what the network layer hands over to the records the caller stores.

Makes no network request: the bytes arrive through a `Download` the caller passes in. Blocking:
run `store_document` in a thread (asyncio.to_thread). The judgement "is this a file at all"
(Q10, rule O2) belongs to app/checks and is passed in as `judge`.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.docs.archive import looks_like_archive, unpack
from app.docs.ids import provisional_file_id
from app.docs.names import choose_name, unique_names
from app.docs.store import FileStore, TooLarge
from app.models import FileRecord, SkipReason, TenderFile, utcnow


class Download(Protocol):
    """What the network layer hands over for one download. The caller closes the response."""

    status: int
    headers: Mapping[str, str]  # looked up without case
    final_url: str | None  # address after redirects, if known

    def chunks(self) -> Iterable[bytes]:
        """The body, chunk by chunk. Not called when the file is skipped before its body."""
        ...


@dataclass(frozen=True)
class StaticDownload:
    """A Download held in memory or from any iterable: for tests and simple callers."""

    status: int
    headers: Mapping[str, str]
    body: Iterable[bytes] = ()
    final_url: str | None = None

    def chunks(self) -> Iterable[bytes]:
        """The body as given."""
        return self.body


@dataclass(frozen=True)
class Announced:
    """What the portal said about a document before we fetched it."""

    source_url: str
    name: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class FileFacts:
    """Everything the file outcome test (O2) may look at, once the body is in."""

    status: int
    content_type: str | None  # Content-Type header, without parameters
    first_bytes: bytes  # up to settings.sniff_bytes
    size_bytes: int  # bytes received
    content_length: int | None
    announced_size: int | None
    announced_type: str | None
    announced_name: str | None
    file_name: str  # the name we chose
    source_url: str
    final_url: str | None


# None accepts the file; a SkipReason rejects it (not_a_file, login_required, captcha, http_error).
Judge = Callable[[FileFacts], SkipReason | None]


@dataclass
class DocumentResult:
    """Records to store, parents before children, and the tender's links in order."""

    files: list[FileRecord] = field(default_factory=list)
    links: list[TenderFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # one line each, for the run's log

    @property
    def skipped(self) -> SkipReason | None:
        """The skip reason when the whole document was skipped."""
        return self.files[0].skipped if len(self.files) == 1 else None


def header(headers: Mapping[str, str], name: str) -> str | None:
    """Header value by name, ignoring case."""
    want = name.lower()
    for k, v in headers.items():
        if k.lower() == want:
            return v
    return None


def _int_or_none(value: str | None) -> int | None:
    try:
        n = int(value.strip()) if value is not None else None
    except ValueError:
        return None
    return n if n is not None and n >= 0 else None


def announced_too_large(announced: Announced, limit: int) -> bool:
    """True when the portal's announced size is over the limit: no request needed at all."""
    return announced.size_bytes is not None and announced.size_bytes > limit


def store_document(download: Download, announced: Announced, *, store: FileStore, judge: Judge,
                   portal_id: str, tender_id: str, first_position: int = 0) -> DocumentResult:
    """Stream, judge, hash, unpack and store one document; return its records and links."""
    settings = store.settings
    limit = settings.max_file_bytes
    headers = download.headers
    content_type = (header(headers, "content-type") or "").split(";")[0].strip().lower() or None
    content_length = _int_or_none(header(headers, "content-length"))
    name = choose_name(announced.name, header(headers, "content-disposition"),
                       download.final_url or announced.source_url, content_type or announced.content_type)
    result = DocumentResult()

    def skip(reason: SkipReason, note: str, size: int | None = None) -> DocumentResult:
        rec = FileRecord(file_id=provisional_file_id(portal_id, tender_id, announced.source_url),
                         size_bytes=size, content_type=content_type, source_url=announced.source_url,
                         skipped=reason)
        result.files.append(rec)
        result.links.append(TenderFile(portal_id=portal_id, tender_id=tender_id, file_id=rec.file_id,
                                       file_name=name, position=first_position))
        result.notes.append(f"Skipped '{name}': {note}.")
        return result

    if announced_too_large(announced, limit):
        return skip(SkipReason.too_large, f"announced {announced.size_bytes} bytes, over {limit}",
                    announced.size_bytes)
    if 200 <= download.status < 300 and content_length is not None and content_length > limit:
        return skip(SkipReason.too_large, f"Content-Length {content_length}, over {limit}", content_length)

    with store.writer(limit) as writer:
        try:
            for chunk in download.chunks():
                if chunk:
                    writer.write(chunk)
        except TooLarge:
            return skip(SkipReason.too_large, f"passed {limit} bytes while downloading")
        writer.close()
        facts = FileFacts(
            status=download.status, content_type=content_type, first_bytes=writer.first_bytes,
            size_bytes=writer.size, content_length=content_length,
            announced_size=announced.size_bytes, announced_type=announced.content_type,
            announced_name=announced.name, file_name=name, source_url=announced.source_url,
            final_url=download.final_url)
        verdict = judge(facts)
        if verdict is not None:
            return skip(verdict, f"the file check said {verdict.value} (HTTP {download.status}, "
                                 f"{content_type or 'no type'}, {writer.size} bytes)")
        sha = writer.sha256 or writer.close()
        if looks_like_archive(name, writer.first_bytes, writer.temp_path):
            unpacked = unpack(store, writer.temp_path, archive_sha256=sha, archive_file_id=sha[:16],
                              source_url=announced.source_url, settings=settings)
            result.notes.extend(unpacked.notes)
            if not unpacked.refused:
                result.files.append(FileRecord(
                    file_id=sha[:16], sha256=sha, size_bytes=writer.size,
                    content_type=content_type or "application/zip", storage_path=None,
                    source_url=announced.source_url, is_archive=True, downloaded_at=utcnow()))
                known = {sha[:16]}
                result.files.extend(r for r in unpacked.records
                                    if not (r.file_id in known or known.add(r.file_id)))
                _link_entries(result, unpacked.leaves(), unpacked.paths, portal_id, tender_id,
                              first_position)
                result.notes.append(f"Unpacked '{name}': {len(unpacked.leaves())} entries.")
                return result  # writer exits and drops the archive's own bytes
        blob = writer.commit()
    result.files.append(FileRecord(
        file_id=blob.file_id, sha256=blob.sha256, size_bytes=blob.size_bytes,
        content_type=content_type or announced.content_type, storage_path=blob.storage_path,
        source_url=announced.source_url, downloaded_at=utcnow()))
    result.links.append(TenderFile(portal_id=portal_id, tender_id=tender_id, file_id=blob.file_id,
                                   file_name=name, position=first_position))
    return result


def _link_entries(result: DocumentResult, leaves: list[FileRecord], paths: dict[str, str],
                  portal_id: str, tender_id: str, first_position: int) -> None:
    """One link per distinct file, in archive order; the first name wins for repeated bytes."""
    seen: set[str] = set()
    unique = [r for r in leaves if not (r.file_id in seen or seen.add(r.file_id))]
    names = unique_names(paths[r.file_id] for r in unique)
    for i, (rec, fname) in enumerate(zip(unique, names)):
        result.links.append(TenderFile(portal_id=portal_id, tender_id=tender_id, file_id=rec.file_id,
                                       file_name=fname, position=first_position + i))
