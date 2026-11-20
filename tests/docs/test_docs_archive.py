"""ZIPs: unpacked into the store under hashes, names only for display, caps enforced."""
from __future__ import annotations

import hashlib
import io
import struct
import warnings
import zipfile

from app.docs import Announced, StaticDownload, store_document
from app.models import SkipReason
from tests.docs.conftest import PDF, blobs, make_zip, stand_in_judge, temp_files

URL = "https://portal.example/tender/1/all.zip"


def run(store, data: bytes, name: str = "all.zip"):
    dl = StaticDownload(status=200, headers={"Content-Type": "application/zip"}, body=[data])
    return store_document(dl, Announced(source_url=URL, name=name), store=store,
                          judge=stand_in_judge, portal_id="p1", tender_id="T-1", first_position=3)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_plain_zip_entries_replace_the_archive(store):
    data = make_zip([("Lot 1/spec.pdf", PDF), ("terms.txt", b"terms"), ("empty/", b"")])
    res = run(store, data)
    archive, *entries = res.files
    assert archive.is_archive and archive.sha256 == sha(data) and archive.storage_path is None
    assert not archive.deliverable
    assert [e.sha256 for e in entries] == [sha(PDF), sha(b"terms")]
    assert all(e.parent_file_id == archive.file_id and e.deliverable for e in entries)
    assert [(l.file_name, l.position) for l in res.links] == [("spec.pdf", 3), ("terms.txt", 4)]
    assert entries[0].content_type == "application/pdf"
    # Only the entries are on disk: the archive's own bytes are dropped once unpacked.
    assert {p.name for p in blobs(store)} == {sha(PDF), sha(b"terms")}
    assert temp_files(store) == []


def test_nested_zip(store):
    inner = make_zip([("inner.pdf", PDF)])
    res = run(store, make_zip([("a.txt", b"a"), ("docs/inner.zip", inner)]))
    outer, a, inner_rec, pdf = res.files
    assert inner_rec.is_archive and inner_rec.parent_file_id == outer.file_id
    assert pdf.parent_file_id == inner_rec.file_id and pdf.sha256 == sha(PDF)
    assert [l.file_name for l in res.links] == ["a.txt", "inner.pdf"]
    assert {p.name for p in blobs(store)} == {sha(b"a"), sha(PDF)}


def test_depth_cap_keeps_nested_zip_as_a_file(make_store):
    store = make_store(max_depth=1)
    inner = make_zip([("inner.pdf", PDF)])
    res = run(store, make_zip([("inner.zip", inner)]))
    _, rec = res.files
    assert not rec.is_archive and rec.sha256 == sha(inner) and rec.deliverable
    assert [l.file_name for l in res.links] == ["inner.zip"]


def test_traversal_and_absolute_names_are_harmless(store, tmp_path):
    res = run(store, make_zip([("../../etc/passwd", b"evil"), ("/etc/shadow", b"abs"),
                               ("..\\..\\win.ini", b"win")]))
    assert [l.file_name for l in res.links] == ["passwd", "shadow", "win.ini"]
    for rec in res.files[1:]:
        assert store.resolve(rec.storage_path).name == rec.sha256
    # Nothing written outside the data directory.
    assert {p.name for p in tmp_path.iterdir()} == {"data"}
    assert not (tmp_path / "etc").exists()


def test_two_entries_with_the_same_name(store):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns about the duplicate name
        data = make_zip([("a/spec.pdf", b"%PDF-a"), ("b/spec.pdf", b"%PDF-b"),
                         ("x.pdf", b"%PDF-1"), ("x.pdf", b"%PDF-2"), ("same.pdf", PDF), ("copy.pdf", PDF)])
    res = run(store, data)
    assert [l.file_name for l in res.links] == [
        "a - spec.pdf", "b - spec.pdf", "x.pdf", "x (2).pdf", "same.pdf"]
    # The same bytes twice are one file and one link (tender_files' key), first name wins.
    assert len({l.file_id for l in res.links}) == len(res.links)
    assert len({r.file_id for r in res.files}) == len(res.files)


def _set_flag(data: bytes, name: bytes, bit: int) -> bytes:
    """Set a general-purpose flag bit in both the local and the central header of `name`."""
    out = bytearray(data)
    for sig, flag_off, name_off in ((b"PK\x03\x04", 6, 30), (b"PK\x01\x02", 8, 46)):
        start = 0
        while (i := out.find(sig, start)) != -1:
            if out[i + name_off:i + name_off + len(name)] == name:
                (flags,) = struct.unpack_from("<H", out, i + flag_off)
                struct.pack_into("<H", out, i + flag_off, flags | bit)
            start = i + 4
    return bytes(out)


def test_encrypted_entry_is_skipped(store):
    data = _set_flag(make_zip([("secret.pdf", PDF), ("open.pdf", b"%PDF-open")]), b"secret.pdf", 0x1)
    res = run(store, data)
    secret, opened = res.files[1:]
    assert secret.skipped == SkipReason.login_required and secret.sha256 is None
    assert opened.deliverable
    assert {p.name for p in blobs(store)} == {sha(b"%PDF-open")}


def test_non_utf8_name_is_read_as_cp437(store):
    data = make_zip([("XXXXXXXX.pdf", PDF)]).replace(b"XXXXXXXX", "Übersich".encode("cp437"))
    assert zipfile.ZipFile(io.BytesIO(data)).infolist()[0].flag_bits & 0x800 == 0
    assert run(store, data).links[0].file_name == "Übersich.pdf"


def test_utf8_name_without_flag(store):
    raw = "Załącznik.pdf".encode("utf-8")
    data = make_zip([("X" * len(raw), PDF)]).replace(b"X" * len(raw), raw)
    assert run(store, data).links[0].file_name == "Załącznik.pdf"


def test_utf8_flagged_name(store):
    assert run(store, make_zip([("Ośrodek.pdf", PDF)])).links[0].file_name == "Ośrodek.pdf"


def test_empty_zip(store):
    data = make_zip([])
    res = run(store, data)
    assert len(res.files) == 1 and res.files[0].is_archive and res.links == []
    assert blobs(store) == []


def test_corrupt_zip_is_kept_as_a_document(store):
    data = b"PK\x03\x04" + b"\x00garbage" * 20
    res = run(store, data)
    (rec,) = res.files
    assert not rec.is_archive and rec.sha256 == sha(data) and rec.deliverable
    assert res.links[0].file_name == "all.zip"
    assert "not unpacked" in " ".join(res.notes)


def test_zip_over_unpacked_cap_is_kept_whole(make_store):
    store = make_store(max_unpacked_bytes=1000)
    data = make_zip([("a.bin", b"a" * 600), ("b.bin", b"b" * 600)], zipfile.ZIP_STORED)
    res = run(store, data)
    (rec,) = res.files
    assert not rec.is_archive and rec.sha256 == sha(data)
    assert [p.name for p in blobs(store)] == [sha(data)]


def test_zip_over_ratio_cap_is_kept_whole(make_store):
    store = make_store(max_ratio=50, ratio_min_bytes=10_000)
    data = make_zip([("zeros.bin", b"\0" * 200_000)])
    assert len(data) < 2000
    res = run(store, data)
    (rec,) = res.files
    assert not rec.is_archive and [p.name for p in blobs(store)] == [sha(data)]


def test_entry_count_cap(make_store):
    store = make_store(max_entries=2)
    res = run(store, make_zip([("1.txt", b"1"), ("2.txt", b"2"), ("3.txt", b"3")]))
    assert len(res.files) == 1 and not res.files[0].is_archive


def test_entry_over_file_limit_is_skipped(make_store):
    store = make_store(max_file_bytes=5000, ratio_min_bytes=10**9)
    res = run(store, make_zip([("huge.bin", b"\0" * 6000), ("ok.txt", b"ok")]))
    huge, ok = res.files[1:]
    assert huge.skipped == SkipReason.too_large and huge.size_bytes == 6000
    assert ok.deliverable
    assert [l.file_name for l in res.links] == ["huge.bin", "ok.txt"]


def test_office_file_is_not_unpacked(store):
    docx = make_zip([("[Content_Types].xml", b"<Types/>"), ("word/document.xml", b"<w/>")])
    res = run(store, docx, name="Leistungsverzeichnis.docx")
    (rec,) = res.files
    assert not rec.is_archive and res.links[0].file_name == "Leistungsverzeichnis.docx"
    res = run(store, docx, name="download")  # no telling extension: the content says Office
    assert not res.files[0].is_archive


def test_nested_zip_over_remaining_cap_is_kept_as_a_file(make_store):
    store = make_store(max_unpacked_bytes=2000)
    inner = make_zip([("big.bin", b"i" * 1500)], zipfile.ZIP_STORED)
    res = run(store, make_zip([("inner.zip", inner)], zipfile.ZIP_STORED))
    outer, rec = res.files
    assert outer.is_archive and not rec.is_archive and rec.sha256 == sha(inner)
    assert any("'inner.zip' was not unpacked" in n for n in res.notes)
    assert temp_files(store) == []
