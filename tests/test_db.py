"""Tests for app/db.py: the store on SQLite (G2, Q15). Run: pytest tests/test_db.py"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.db import Database, DbSettings, UnknownPortal, UnknownRecord
from app.docs import Announced, DocsSettings, FileStore, StaticDownload, files_to_remove, store_document
from app.models import (
    AgentStep, Cause, CheckResult, DocsStatus, FileRecord, NetworkEntry, PlaceOfPerformance, Portal,
    PortalSnapshot, PortalState, ProcedureType, ContractNature, Recipe, RecipeStatus, Run, RunKind, RunResult,
    RunStats, RunTrigger, Severity, StepKind, TenderFile, TenderRecord, TenderStatus, TokenUsage, url_key,
)
from tests.docs.conftest import PDF, make_zip, stand_in_judge

UTC = timezone.utc
CET = timezone(timedelta(hours=1))
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "data" / "watchtower.db")
    yield database
    database.close()


def portal(n: int = 1, state: PortalState = PortalState.integrating, at: datetime = T0) -> Portal:
    url = f"https://portal{n}.example/tenders"
    return Portal(id=f"p{n}", url=url, url_key=url_key(url), state=state, created_at=at, updated_at=at)


def serving(db: Database, n: int = 1) -> Portal:
    p, _ = db.add_portal(portal(n))
    p = p.model_copy(update={"state": PortalState.serving, "reason": "Every check passed."})
    assert db.update_portal(p)
    return p


def tender(portal_id: str, tender_id: str, **kw) -> TenderRecord:
    base = dict(portal_id=portal_id, tender_id=tender_id, url=f"https://x.example/t/{tender_id}",
                title=f"Tender {tender_id}", buyer_name="City of Example", publication_date=date(2026, 11, 2),
                submission_deadline=datetime(2026, 12, 15, 10, 0, tzinfo=CET), first_seen_at=T0,
                last_seen_at=T0, last_changed_at=T0, content_hash=f"h-{tender_id}", docs_status=DocsStatus.complete)
    base.update(kw)
    return TenderRecord(**base)


def blob(n: int) -> FileRecord:
    sha = hashlib.sha256(str(n).encode()).hexdigest()
    return FileRecord(file_id=sha[:16], sha256=sha, size_bytes=100 + n, content_type="application/pdf",
                      storage_path=f"files/{sha[:2]}/{sha}", source_url=f"https://x.example/f/{n}",
                      downloaded_at=T0)


def link(portal_id: str, tender_id: str, f: FileRecord, name: str, position: int) -> TenderFile:
    return TenderFile(portal_id=portal_id, tender_id=tender_id, file_id=f.file_id, file_name=name, position=position)


class Docs:
    """A tender's documents in the shape `app.docs.DocumentResult` has."""

    def __init__(self, files, links):
        self.files, self.links = files, links


def run(portal_id: str, kind: RunKind = RunKind.read, trigger: RunTrigger = RunTrigger.attach,
        at: datetime = T0, **kw) -> Run:
    return Run(id=uuid.uuid4().hex, portal_id=portal_id, kind=kind, trigger=trigger, started_at=at,
               state_before=PortalState.integrating, **kw)


# == Portals ==

def test_same_address_twice_gives_one_portal(db):
    first, created = db.add_portal(portal(1))
    again, created_again = db.add_portal(portal(1).model_copy(update={"id": "other-id"}))
    assert created and not created_again
    assert again.id == first.id == "p1"
    assert [p.id for p in db.list_portals()] == ["p1"]


def test_add_portal_is_atomic_when_posted_at_the_same_moment(db):
    barrier = threading.Barrier(16)
    results: list[bool] = []

    def post(i: int) -> None:
        barrier.wait()
        results.append(db.add_portal(portal(1).model_copy(update={"id": f"id{i}"}))[1])

    threads = [threading.Thread(target=post, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    assert len(db.list_portals()) == 1


def test_portals_come_back_as_stored_oldest_first(db):
    db.add_portal(portal(2, at=T0 + timedelta(minutes=5)))
    db.add_portal(portal(1, at=T0))
    assert [p.id for p in db.list_portals()] == ["p1", "p2"]
    got = db.get_portal("p2")
    assert got == portal(2, at=T0 + timedelta(minutes=5))
    assert db.get_portal("nope") is None


def test_update_portal_saves_state_and_never_brings_a_deleted_portal_back(db):
    p, _ = db.add_portal(portal(1))
    changed = p.model_copy(update={"state": PortalState.healing, "cause": Cause.outage, "reason": "Not answering.",
                                   "last_success_at": T0, "timezone": "Europe/Berlin", "recipe_version": None})
    assert db.update_portal(changed)
    got = db.get_portal("p1")
    assert (got.state, got.cause, got.reason, got.timezone) == (PortalState.healing, Cause.outage,
                                                                "Not answering.", "Europe/Berlin")
    assert got.last_success_at == T0
    assert got.updated_at > T0

    assert db.delete_portal("p1")
    assert not db.update_portal(changed)
    assert db.get_portal("p1") is None


def test_a_time_without_a_zone_is_refused(db):
    p = portal(1).model_copy(update={"created_at": datetime(2026, 11, 20, 12, 0)})
    with pytest.raises(ValueError, match="no time zone"):
        db.add_portal(p)
    assert db.list_portals() == []


def test_delete_unknown_portal_is_false(db):
    assert db.delete_portal("nope") is False


# == Tenders: what the API sees ==

def test_nothing_is_visible_while_integrating(db):
    db.add_portal(portal(1))
    db.publish_tenders("p1", [tender("p1", "A"), tender("p1", "B")])
    assert db.list_tenders("p1") == []
    assert db.count_tenders("p1") == 0
    assert [t.tender_id for t in db.known_tenders("p1")] == ["A", "B"]

    p = db.get_portal("p1").model_copy(update={"state": PortalState.serving})
    db.update_portal(p)
    assert [t.tender_id for t, _ in db.list_tenders("p1")] == ["A", "B"]
    assert db.count_tenders("p1") == 2


def test_a_healing_portal_still_serves_the_last_good_read(db):
    p = serving(db)
    db.publish_tenders("p1", [tender("p1", "A")])
    db.update_portal(p.model_copy(update={"state": PortalState.healing, "cause": Cause.breakage}))
    assert [t.tender_id for t, _ in db.list_tenders("p1")] == ["A"]


def test_unknown_portal_has_no_tenders(db):
    assert db.list_tenders("nope") == []
    assert db.count_tenders("nope") == 0


def test_every_tender_field_comes_back_and_the_deadline_keeps_its_offset(db):
    serving(db)
    record = tender("p1", "A-17", reference_number="VgV-2026-17", description="Roof repairs",
                    procedure_type=ProcedureType.open, contract_nature=ContractNature.works,
                    cpv_codes=["45261000-4", "45000000"], withdrawn=False, listed=True,
                    place=PlaceOfPerformance(postalCode="10115", city="Berlin", countryCode="de"),
                    detail_fetched_at=T0, source_run_id="r1", source_urls=["https://x.example/t/A-17"],
                    raw={"deadline": "15.12.2026 10:00", "title": None})
    db.publish_tenders("p1", [record])
    (got, docs), = db.list_tenders("p1")
    assert got == record
    assert got.submission_deadline.utcoffset() == timedelta(hours=1)
    assert got.cpv_codes == ["45261000", "45000000"]
    assert got.place.countryCode == "DE"
    assert docs == []


def test_publishing_again_keeps_last_changed_when_the_content_is_the_same(db):
    serving(db)
    db.publish_tenders("p1", [tender("p1", "A", content_hash="h1", last_changed_at=T0, first_seen_at=T0)])
    later = T0 + timedelta(hours=2)
    db.publish_tenders("p1", [tender("p1", "A", content_hash="h1", last_changed_at=later, last_seen_at=later,
                                     first_seen_at=later)])
    (same, _), = db.list_tenders("p1")
    assert same.last_changed_at == T0
    assert same.first_seen_at == T0
    assert same.last_seen_at == later

    db.publish_tenders("p1", [tender("p1", "A", content_hash="h2", title="New title", last_changed_at=later,
                                     first_seen_at=later)])
    (changed, _), = db.list_tenders("p1")
    assert changed.last_changed_at == later
    assert changed.first_seen_at == T0
    assert changed.title == "New title"


def test_a_tender_that_leaves_the_list_is_closed_and_counts_as_changed(db):
    serving(db)
    db.publish_tenders("p1", [tender("p1", "A"), tender("p1", "B")])
    gone_at = T0 + timedelta(hours=1)
    db.publish_tenders("p1", [tender("p1", "A")], unlisted=["B"], at=gone_at)
    records = {t.tender_id: t for t, _ in db.list_tenders("p1")}
    assert records["B"].listed is False
    assert records["B"].effective_status(T0) == TenderStatus.closed
    assert records["B"].last_changed_at == gone_at
    assert records["A"].listed is True


def test_a_publish_is_all_or_nothing(db):
    serving(db)
    serving(db, 2)
    with pytest.raises(ValueError, match="belongs to p2"):
        db.publish_tenders("p1", [tender("p1", "A"), tender("p2", "B")])
    assert db.known_tenders("p1") == []
    with pytest.raises(UnknownPortal):
        db.publish_tenders("nope", [tender("nope", "A")])


# == Documents ==

def test_documents_come_back_in_order_and_serve_the_api_answer(db):
    serving(db)
    first, second = blob(1), blob(2)
    docs = Docs([second, first], [link("p1", "A", first, "a.pdf", 0), link("p1", "A", second, "b.pdf", 1)])
    db.publish_tenders("p1", [tender("p1", "A")], documents={"A": docs})
    (record, files), = db.list_tenders("p1")
    assert [(l.file_name, f.file_id) for l, f in files] == [("a.pdf", first.file_id), ("b.pdf", second.file_id)]
    answer = record.to_api(files, now=T0)
    assert [d["fileName"] for d in answer["documents"]] == ["a.pdf", "b.pdf"]
    assert answer["documents"][0]["path"] == f"/files/{first.file_id}"
    assert db.get_file(first.file_id) == first
    assert db.get_file("nope") is None


def test_a_document_listed_while_loading_is_replaced_when_its_bytes_arrive(db):
    serving(db)
    pending = FileRecord(file_id="p" + "0" * 15, size_bytes=5000, source_url="https://x.example/f/9")
    db.publish_tenders("p1", [tender("p1", "A", docs_status=DocsStatus.pending)],
                       documents={"A": Docs([pending], [link("p1", "A", pending, "spec.pdf", 0)])})
    (record, files), = db.list_tenders("p1")
    assert record.to_api(files, now=T0)["documents"] == [
        {"fileName": "spec.pdf", "sizeBytes": 5000, "sha256": None, "path": None}]

    fetched = blob(9)
    later = T0 + timedelta(minutes=3)
    db.set_documents("p1", "A", [fetched], [link("p1", "A", fetched, "spec.pdf", 0)],
                     docs_status=DocsStatus.complete, last_changed_at=later)
    (record, files), = db.list_tenders("p1")
    assert record.docs_status == DocsStatus.complete
    assert record.last_changed_at == later
    assert record.to_api(files, now=T0)["documents"][0]["sha256"] == fetched.sha256
    assert [f.file_id for f in db.collect_orphan_files()] == [pending.file_id]
    assert db.collect_orphan_files() == []


def test_documents_for_an_unknown_tender_are_refused(db):
    serving(db)
    with pytest.raises(UnknownRecord):
        db.set_documents("p1", "missing", [blob(1)], [link("p1", "missing", blob(1), "a.pdf", 0)])


def test_records_made_by_app_docs_store_as_they_are(db, tmp_path):
    """A ZIP from app/docs: the archive, its entries and the links go in as one tender's documents."""
    serving(db)
    files = FileStore(DocsSettings(data_dir=tmp_path / "docs"))
    archive = make_zip([("Leistungsverzeichnis.pdf", PDF), ("Pläne/Lageplan.pdf", PDF + b"2")])
    result = store_document(StaticDownload(200, {"content-type": "application/zip"}, [archive]),
                            Announced(source_url="https://x.example/f/all.zip", name="all.zip"),
                            store=files, judge=stand_in_judge, portal_id="p1", tender_id="A")
    assert any(f.is_archive for f in result.files) and len(result.links) == 2
    db.publish_tenders("p1", [tender("p1", "A")], documents={"A": result})

    (record, linked), = db.list_tenders("p1")
    names = [d["fileName"] for d in record.to_api(linked, now=T0)["documents"]]
    assert len(names) == 2 and all(n.endswith(".pdf") for n in names)
    assert all(f.deliverable for _, f in linked)

    # Deleting the portal leaves the content; the cleanup takes entries first, then the archive.
    assert db.delete_portal("p1")
    removed = db.collect_orphan_files()
    assert len(removed) == len(result.files)
    assert removed[-1].is_archive


def test_file_uses_feed_the_disk_cleanup_of_app_docs(db):
    serving(db)
    open_file, closed_file, shared = blob(1), blob(2), blob(3)
    db.publish_tenders("p1", [tender("p1", "OPEN"), tender("p1", "PAST", submission_deadline=T0 - timedelta(days=1))],
                       documents={"OPEN": Docs([open_file, shared], [link("p1", "OPEN", open_file, "o.pdf", 0),
                                                                      link("p1", "OPEN", shared, "s.pdf", 1)]),
                                  "PAST": Docs([closed_file, shared], [link("p1", "PAST", closed_file, "c.pdf", 0),
                                                                        link("p1", "PAST", shared, "s.pdf", 1)])})
    uses = db.file_uses(now=T0)
    assert len(uses) == 4
    assert [f.file_id for f in files_to_remove(uses)] == [closed_file.file_id]


# == Deleting a portal ==

def test_delete_removes_the_portal_and_everything_it_owns_but_not_shared_files(db):
    for n in (1, 2):
        serving(db, n)
    shared, own = blob(1), blob(2)
    db.publish_tenders("p1", [tender("p1", "A")],
                       documents={"A": Docs([shared, own], [link("p1", "A", shared, "s.pdf", 0),
                                                            link("p1", "A", own, "o.pdf", 1)])})
    db.publish_tenders("p2", [tender("p2", "A")], documents={"A": Docs([shared], [link("p2", "A", shared, "s.pdf", 0)])})
    r = db.start_run(run("p1"))
    db.add_checks([CheckResult(run_id=r.id, name="paging_complete", passed=True, severity=Severity.fail, message="ok")])
    db.add_step(AgentStep(run_id=r.id, seq=1, at=T0, kind=StepKind.note, name="start", summary="Started"))
    db.save_snapshot(PortalSnapshot(id="s1", portal_id="p1", run_id=r.id, captured_at=T0))
    db.add_recipe(Recipe(portal_id="p1", version=1, body={"nodes": [], "edges": []}, created_at=T0))

    assert db.delete_portal("p1")
    assert db.get_portal("p1") is None
    assert (db.known_tenders("p1"), db.list_runs("p1"), db.list_checks(r.id), db.list_steps(r.id)) == ([], [], [], [])
    assert db.latest_snapshot("p1") is None and db.get_recipe("p1", 1) is None
    assert [f.file_id for f in db.collect_orphan_files()] == [own.file_id]
    assert db.get_file(shared.file_id) == shared
    assert len(db.list_tenders("p2")[0][1]) == 1


# == Runs ==

def test_one_run_per_portal_and_a_refresh_gets_the_running_one(db):
    db.add_portal(portal(1))
    attach = db.start_run(run("p1"))
    assert db.start_run(run("p1", trigger=RunTrigger.refresh)).id == attach.id
    assert db.start_run(run("p1", kind=RunKind.repair, trigger=RunTrigger.heal)).id == attach.id
    assert db.active_run("p1").id == attach.id

    done = attach.model_copy(update={"finished_at": T0 + timedelta(minutes=1), "result": RunResult.ok,
                                     "state_after": PortalState.serving})
    assert db.save_run(done)
    assert db.active_run("p1") is None
    second = db.start_run(run("p1", trigger=RunTrigger.refresh, at=T0 + timedelta(minutes=2)))
    assert second.id != attach.id
    assert [r.id for r in db.list_runs("p1")] == [attach.id, second.id]
    assert db.list_runs("p1")[0].to_api().result == RunResult.ok


def test_the_schema_also_refuses_two_running_reads(db):
    db.add_portal(portal(1))
    db.start_run(run("p1"))
    with pytest.raises(sqlite3.IntegrityError):
        with db._writing() as con:  # bypassing start_run: the partial unique index still holds
            con.execute("INSERT INTO runs (id, portal_id, kind, trigger, started_at, state_before) "
                        "VALUES ('x', 'p1', 'read', 'refresh', ?, 'serving')", (T0.isoformat(),))


def test_a_run_for_a_deleted_portal_is_refused(db):
    with pytest.raises(UnknownPortal):
        db.start_run(run("gone"))
    assert not db.save_run(run("gone"))


def test_run_stats_and_usage_come_back(db):
    db.add_portal(portal(1))
    r = db.start_run(run("p1", kind=RunKind.repair, trigger=RunTrigger.heal))
    finished = r.model_copy(update={
        "finished_at": T0 + timedelta(minutes=4), "result": RunResult.failed, "recipe_version": 2,
        "state_after": PortalState.failed, "reason_after": "Three repairs failed.", "model_calls": 3,
        "stats": RunStats(http_requests=40, pages_fetched=12, tenders_seen=9),
        "usage": TokenUsage(input_tokens=90_000, cached_input_tokens=30_000, output_tokens=8_000,
                            reasoning_tokens=5_000, cost_usd=0.41),
        "error": "list locator found nothing"})
    db.save_run(finished)
    assert db.get_run(r.id) == finished
    assert db.get_run("nope") is None
    costs = db.portal_costs()["p1"]
    assert costs["repair_cost_usd"] == pytest.approx(0.41) and costs["model_calls"] == 3


def test_runs_left_open_by_a_restart_are_closed_as_failed(db):
    for n in (1, 2):
        db.add_portal(portal(n))
    open_run = db.start_run(run("p1"))
    closed = db.start_run(run("p2"))
    db.save_run(closed.model_copy(update={"finished_at": T0, "result": RunResult.ok}))
    restarted = T0 + timedelta(hours=1)
    failed = db.fail_open_runs(at=restarted)
    assert [r.id for r in failed] == [open_run.id]
    assert failed[0].result == RunResult.failed and failed[0].finished_at == restarted
    assert db.get_run(closed.id).result == RunResult.ok
    assert db.active_run("p1") is None


# == Checks, steps, snapshots ==

def test_a_check_recorded_again_in_the_same_run_replaces_the_first_row(db):
    db.add_portal(portal(1))
    r = db.start_run(run("p1"))
    db.add_checks([
        CheckResult(run_id=r.id, name="known_ids_missing", passed=False, severity=Severity.fail,
                    observed={"missing": ["A"]}, message="A known tender is missing."),
        CheckResult(run_id=r.id, name="printed_total", passed=True, severity=Severity.fail, observed=23,
                    expected=23, message="23 tenders, as printed."),
    ])
    db.add_checks([CheckResult(run_id=r.id, name="known_ids_missing", passed=True, severity=Severity.info,
                               observed={"first": {"missing": ["A"]}},
                               message="First read missed A; the second read found it.")])
    checks = db.list_checks(r.id)
    assert [c.name for c in checks] == ["known_ids_missing", "printed_total"]
    assert checks[0].passed and checks[0].severity == Severity.info
    assert checks[0].observed == {"first": {"missing": ["A"]}}
    assert checks[1].observed == 23


def test_steps_and_snapshots_come_back(db):
    db.add_portal(portal(1))
    r = db.start_run(run("p1"))
    steps = [AgentStep(run_id=r.id, seq=2, at=T0, kind=StepKind.llm, name="gpt-6.2-sol", summary="Wrote the list node",
                       prompt_id="learn/system@3", usage=TokenUsage(input_tokens=30_000, output_tokens=2_000)),
             AgentStep(run_id=r.id, seq=1, at=T0, kind=StepKind.tool, name="open", summary="Opened the entry page",
                       args={"url": "https://portal1.example/"}, result="200, 3 JSON calls", duration_ms=1200)]
    for s in steps:
        db.add_step(s)
    assert db.list_steps(r.id) == sorted(steps, key=lambda s: s.seq)

    older = PortalSnapshot(id="s1", portal_id="p1", run_id=r.id, captured_at=T0, last_good_tender_ids=["A"])
    newer = PortalSnapshot(id="s2", portal_id="p1", run_id=r.id, captured_at=T0 + timedelta(minutes=1),
                           network=[NetworkEntry(url="https://portal1.example/api/list", looks_like_tender_list=True)])
    db.save_snapshot(older)
    db.save_snapshot(newer)
    assert db.latest_snapshot("p1") == newer


def test_the_dashboard_reads_every_portals_last_runs_totals_and_publications_at_once(db):
    for n in (1, 2, 3):
        db.add_portal(portal(n))

    def ended(portal_id: str, minute: int, **kw) -> Run:
        r = db.start_run(run(portal_id, at=T0 + timedelta(minutes=minute), **kw))
        r = r.model_copy(update={"finished_at": r.started_at + timedelta(seconds=30), "result": RunResult.ok})
        assert db.save_run(r)
        return r

    reads = [ended("p1", m, usage=TokenUsage(input_tokens=100, cached_input_tokens=40, output_tokens=10,
                                              reasoning_tokens=4, cost_usd=0.25), model_calls=1) for m in range(5)]
    repair = ended("p1", 5, kind=RunKind.repair, trigger=RunTrigger.heal, model_calls=2)  # no tokens recorded
    other = ended("p2", 1)

    assert db.recent_runs(2) == {"p1": [reads[4], repair], "p2": [other]}  # p3 has no run and no key
    assert db.recent_runs(3, kind=RunKind.read) == {"p1": reads[2:], "p2": [other]}
    assert db.recent_runs(10, portal_id="p2") == {"p2": [other]}
    assert db.recent_runs(10, portal_id="p3") == {}

    totals = db.run_totals(T0 + timedelta(minutes=3))
    assert set(totals) == {"p1", "p2"}
    assert totals["p1"].usage == TokenUsage(input_tokens=500, cached_input_tokens=200, output_tokens=50,
                                            reasoning_tokens=20, cost_usd=1.25)
    assert (totals["p1"].model_calls, totals["p1"].unaccounted_runs, totals["p1"].reads_since) == (7, 1, 2)
    assert (totals["p2"].usage, totals["p2"].unaccounted_runs, totals["p2"].reads_since) == (TokenUsage(), 0, 0)

    for i, r in enumerate(reads):
        db.add_step(AgentStep(run_id=r.id, seq=1, at=r.started_at, kind=StepKind.note, name="read_list", summary="."))
        db.add_step(AgentStep(run_id=r.id, seq=2, at=r.started_at + timedelta(seconds=9), kind=StepKind.note,
                              name="publish", summary=".", args={"delivered": 40 + i}))
    published = db.recent_steps("publish", 3)
    assert list(published) == ["p1"]
    assert [step.args for step in published["p1"]] == [{"delivered": n} for n in (42, 43, 44)]
    assert db.recent_steps("nothing", 3) == {}


# == Recipes ==

def test_activating_a_recipe_retires_the_one_before_and_points_the_portal_at_it(db):
    db.add_portal(portal(1))
    body = {"format": "recipe/v1", "nodes": [{"id": "list", "kind": "http_json"}], "edges": []}
    assert db.next_recipe_version("p1") == 1
    db.add_recipe(Recipe(portal_id="p1", version=1, body=body, fingerprint="netserver", created_at=T0))
    db.activate_recipe("p1", 1, at=T0)
    db.add_recipe(Recipe(portal_id="p1", version=2, parent_version=1, body=body, fingerprint="netserver",
                         created_at=T0))
    active = db.activate_recipe("p1", 2, at=T0)

    assert active.status == RecipeStatus.active and active.body == body
    assert db.get_recipe("p1", 1).status == RecipeStatus.retired
    assert db.active_recipe("p1").version == 2
    assert db.get_portal("p1").recipe_version == 2
    assert db.next_recipe_version("p1") == 3


def test_recipe_rules(db):
    db.add_portal(portal(1))
    db.add_portal(portal(2))
    body = {"nodes": [], "edges": []}
    with pytest.raises(ValueError):
        db.add_recipe(Recipe(portal_id="p1", version=1, body=body, status=RecipeStatus.active))
    with pytest.raises(UnknownPortal):
        db.add_recipe(Recipe(portal_id="gone", version=1, body=body))
    db.add_recipe(Recipe(portal_id="p1", version=1, body=body, fingerprint="cosinex"))
    with pytest.raises(sqlite3.IntegrityError):
        db.add_recipe(Recipe(portal_id="p1", version=1, body=body))
    with pytest.raises(UnknownRecord):
        db.activate_recipe("p1", 9)

    assert db.reject_recipe("p1", 1, rationale="List locator found nothing")
    assert db.get_recipe("p1", 1).status == RecipeStatus.rejected
    assert db.active_recipe("p1") is None

    db.add_recipe(Recipe(portal_id="p2", version=1, body=body, fingerprint="cosinex"))
    db.activate_recipe("p2", 1)
    assert [(r.portal_id, r.version) for r in db.recipes_for_fingerprint("cosinex", exclude_portal_id="p1")] == [("p2", 1)]
    assert db.recipes_for_fingerprint("cosinex", exclude_portal_id="p2") == []


# == Threads, restarts, settings ==

def test_reads_from_many_threads_see_whole_publishes_only(db):
    serving(db)
    ids = [f"T{i:03d}" for i in range(50)]
    db.publish_tenders("p1", [tender("p1", i, title="v0", content_hash="v0") for i in ids])
    stop = threading.Event()
    errors: list[BaseException] = []

    def write() -> None:
        n = 0
        while not stop.is_set():
            n += 1
            db.publish_tenders("p1", [tender("p1", i, title=f"v{n}", content_hash=f"v{n}") for i in ids])

    def read() -> None:
        try:
            for _ in range(40):
                rows = db.list_tenders("p1")
                assert len(rows) == len(ids) == db.count_tenders("p1")
                assert len({t.title for t, _ in rows}) == 1  # one publish, never half of two
        except BaseException as e:  # noqa: BLE001 - reported below
            errors.append(e)

    writer = threading.Thread(target=write)
    readers = [threading.Thread(target=read) for _ in range(8)]
    writer.start()
    for t in readers:
        t.start()
    for t in readers:
        t.join()
    stop.set()
    writer.join()
    assert errors == []


def test_everything_is_still_there_after_a_restart(tmp_path):
    path = tmp_path / "w.db"
    first = Database(path)
    serving(first)
    first.publish_tenders("p1", [tender("p1", "A")])
    first.close()

    again = Database(path)
    try:
        assert again.get_portal("p1").state == PortalState.serving
        assert [t.tender_id for t, _ in again.list_tenders("p1")] == ["A"]
    finally:
        again.close()


def test_settings_from_the_environment(tmp_path):
    settings = DbSettings.from_env({"DATA_DIR": str(tmp_path), "DB_BUSY_TIMEOUT_SECONDS": "2.5"})
    assert settings.path == tmp_path / "watchtower.db"
    assert settings.busy_timeout_seconds == 2.5
    assert DbSettings.from_env({}).path.name == "watchtower.db"
    with pytest.raises(ValueError):
        DbSettings(busy_timeout_seconds=0)
    database = Database.from_env({"DATA_DIR": str(tmp_path / "nested")})
    try:
        assert database.path == tmp_path / "nested" / "watchtower.db" and database.path.exists()
    finally:
        database.close()


def test_the_store_provides_what_the_api_calls():
    """The eight methods of `Store`; checked against app/interfaces.py once that file is on main."""
    names = ["add_portal", "get_portal", "list_portals", "delete_portal", "count_tenders", "list_tenders",
             "list_runs", "get_file"]
    assert all(callable(getattr(Database, n)) for n in names)
    try:
        from app.interfaces import Store
    except ImportError:
        return
    wanted = {n for n in vars(Store) if not n.startswith("_")}
    assert wanted <= set(dir(Database))


# == The API on this store ==

class RunsOnlyWorker:
    """`app.interfaces.Worker` on the database: records runs, reads nothing. The scheduler's loop replaces it."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def attach(self, portal: Portal) -> None:
        self.db.start_run(run(portal.id, at=datetime.now(UTC)))

    def refresh(self, portal: Portal) -> str:
        return self.db.start_run(run(portal.id, trigger=RunTrigger.refresh, at=datetime.now(UTC))).id

    def forget(self, portal_id: str) -> None:
        return None


def test_the_api_runs_on_this_store(db, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app, portal_id_for
    from tests.contract.schema import check_portal, check_run, check_tender

    files = FileStore(DocsSettings(data_dir=tmp_path / "docs"))
    with TestClient(create_app(db, RunsOnlyWorker(db), files=lambda: files)) as client:
        url = "https://vergabe.example/tenders"
        first = client.post("/portals", json={"url": url})
        assert first.status_code == 201 and first.json() == {"id": portal_id_for(url)}
        pid = first.json()["id"]
        assert client.post("/portals", json={"url": url + "/"}).json() == {"id": pid}
        assert [p["id"] for p in client.get("/portals").json()] == [pid]

        # Integrating: the attach's run is there, nothing is delivered, a refresh gets the running read.
        attach_run = client.get(f"/portals/{pid}/runs").json()
        assert len(attach_run) == 1 and attach_run[0]["kind"] == "read" and attach_run[0]["result"] is None
        check_run(attach_run[0])
        assert client.post(f"/portals/{pid}/refresh").json() == {"runId": attach_run[0]["id"]}
        db.publish_tenders(pid, [tender(pid, "A")])
        assert client.get(f"/portals/{pid}/tenders").json() == []
        assert client.get(f"/portals/{pid}").json()["tenderCount"] == 0

        # The worker publishes a document and the portal serves.
        with files.writer() as writer:
            writer.write(PDF)
            stored = writer.commit()
        record = FileRecord(file_id=stored.file_id, sha256=stored.sha256, size_bytes=stored.size_bytes,
                            content_type="application/pdf", storage_path=stored.storage_path,
                            source_url=f"{url}/A/lv.pdf", downloaded_at=T0)
        db.set_documents(pid, "A", [record], [link(pid, "A", record, "lv.pdf", 0)])
        db.update_portal(db.get_portal(pid).model_copy(update={"state": PortalState.serving,
                                                               "reason": "Every check passed.",
                                                               "last_success_at": T0}))
        portal_answer = client.get(f"/portals/{pid}").json()
        check_portal(portal_answer)
        assert (portal_answer["state"], portal_answer["tenderCount"]) == ("serving", 1)
        tenders = client.get(f"/portals/{pid}/tenders").json()
        assert len(tenders) == 1
        check_tender(tenders[0])
        document = tenders[0]["documents"][0]
        assert client.get(document["path"]).content == PDF
        since = (T0 + timedelta(hours=1)).isoformat()
        assert client.get(f"/portals/{pid}/tenders", params={"changedSince": since}).json() == []

        assert client.delete(f"/portals/{pid}").status_code == 204
        assert client.get(f"/portals/{pid}").status_code == 404
        assert client.get("/portals").json() == []
