"""Tests for app/models.py and app/schema.sql (Q7). Run: pytest tests/test_models.py"""
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import (  # noqa: E402
    FileRecord, PlaceOfPerformance, Portal, PortalState, TenderFile, TenderRecord,
    TenderOut, TenderStatus, REQUIRED_TENDER_FIELDS, normalize_cpv, url_key,
)

CET = timezone(timedelta(hours=1))
UTC = timezone.utc


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.executescript((ROOT / "app" / "schema.sql").read_text())
    return con


def make_tender(**kw) -> TenderRecord:
    base = dict(
        portal_id="p1", tender_id="T-1", title="Road works", buyer_name="Stadt X",
        publication_date=date(2026, 11, 20),
        submission_deadline=datetime(2026, 12, 9, 10, 0, tzinfo=CET),
        last_changed_at=datetime(2026, 11, 20, 9, 0, tzinfo=UTC),
    )
    base.update(kw)
    return TenderRecord(**base)


def pdf_link():
    f = FileRecord(file_id="ab12cd34ab12cd34", sha256="a" * 64, size_bytes=10, source_url="u1")
    return TenderFile(portal_id="p1", tender_id="T-1", file_id=f.file_id, file_name="LV.pdf"), f


NOW = datetime(2026, 11, 21, tzinfo=UTC)


def test_schema_creates_all_tables(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"portals", "recipes", "runs", "run_checks", "agent_steps", "snapshots",
            "tenders", "files", "tender_files", "portal_costs"} <= names


def test_only_one_running_read_per_portal(db):
    db.execute("INSERT INTO portals (id,url,url_key,created_at,updated_at) VALUES ('p1','u','u','t','t')")
    ins = "INSERT INTO runs (id,portal_id,kind,trigger,started_at,state_before) VALUES (?, 'p1','read','refresh','t','serving')"
    db.execute(ins, ("r1",))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(ins, ("r2",))


def test_required_fields_present_even_when_null():
    out = make_tender(url=None).to_api([pdf_link()], now=NOW)
    for k in REQUIRED_TENDER_FIELDS:
        assert k in out
    assert out["url"] is None


def test_optional_fields_left_out_when_missing():
    out = make_tender().to_api([], now=NOW)
    for k in ("referenceNumber", "description", "procedureType", "contractNature",
              "cpvCodes", "placeOfPerformance"):
        assert k not in out


def test_empty_place_is_left_out():
    out = make_tender(place=PlaceOfPerformance()).to_api([], now=NOW)
    assert "placeOfPerformance" not in out


def test_datetimes_have_offset_never_z():
    out = make_tender().to_api([], now=NOW)
    assert out["submissionDeadline"] == "2026-12-09T10:00:00+01:00"
    assert out["lastChangedAt"] == "2026-11-20T09:00:00+00:00"


def test_cpv_check_digit_removed_and_deduplicated():
    out = make_tender(cpv_codes=["45000000-7", "45000000", "72000000"]).to_api([], now=NOW)
    assert out["cpvCodes"] == ["45000000", "72000000"]


@pytest.mark.parametrize("bad", ["4500000", "45000000-77", "abc", ""])
def test_bad_cpv_rejected(bad):
    with pytest.raises(ValueError):
        normalize_cpv(bad)


def test_country_code_uppercased():
    assert PlaceOfPerformance(countryCode="de").countryCode == "DE"
    with pytest.raises(ValueError):
        PlaceOfPerformance(countryCode="DEU")


def test_status_open_then_closed_after_deadline():
    t = make_tender()
    assert t.effective_status(NOW) == TenderStatus.open
    later = datetime(2026, 12, 10, tzinfo=UTC)
    out = t.to_api([], now=later)
    assert out["status"] == "closed"
    assert out["lastChangedAt"] == "2026-12-09T10:00:00+01:00"  # deadline passing counts as a change


def test_unlisted_is_closed_and_withdrawn_wins():
    assert make_tender(listed=False).effective_status(NOW) == TenderStatus.closed
    assert make_tender(withdrawn=True, listed=False).effective_status(NOW) == TenderStatus.withdrawn


def test_archives_and_skipped_files_not_delivered():
    zip_file = FileRecord(file_id="zz", sha256="b" * 64, size_bytes=99, source_url="u2", is_archive=True)
    big = FileRecord(file_id="bb", source_url="u3", skipped="too_large")
    links = [pdf_link(),
             (TenderFile(portal_id="p1", tender_id="T-1", file_id="zz", file_name="all.zip"), zip_file),
             (TenderFile(portal_id="p1", tender_id="T-1", file_id="bb", file_name="big.zip"), big)]
    docs = make_tender().to_api(links, now=NOW)["documents"]
    assert [d["fileName"] for d in docs] == ["LV.pdf"]
    assert docs[0]["path"] == "/files/ab12cd34ab12cd34"


def test_api_tender_rejects_unknown_fields():
    with pytest.raises(ValueError):
        TenderOut(id="x", url=None, title=None, buyerName=None, publicationDate=None,
                  submissionDeadline=None, status="open", lastChangedAt=NOW, foo=1)


def test_content_hash_changes_with_content():
    a = make_tender()
    assert a.compute_hash([]) == make_tender().compute_hash([])
    assert a.compute_hash([]) != make_tender(title="Other").compute_hash([])
    assert a.compute_hash([]) != a.compute_hash(["a" * 64])


def test_same_address_same_key():
    assert url_key("https://X.de/a/?b=2&a=1#top") == url_key("https://x.de:443/a?a=1&b=2")
    assert url_key("https://x.de/a") != url_key("https://x.de/b")


def test_portal_api_shape():
    p = Portal(id="p1", url="https://x.de", url_key=url_key("https://x.de"))
    out = p.to_api(0).model_dump(mode="json")
    assert out == {"id": "p1", "url": "https://x.de", "state": "integrating",
                   "reason": "Attaching: nothing delivered yet.", "tenderCount": 0,
                   "lastSuccessAt": None}
    assert p.state == PortalState.integrating
