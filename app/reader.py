"""One read of one portal, from the recipe to what is published (DESIGN.md, "Rules the worker enforces").

`Reader.read` is the whole of a read and holds no rule of its own: the executor reads
(`app/recipe/run.py`), the checks judge (`app/checks`), `decide` gives the state
(`app/state.py`), the scheduler's rules plan what is fetched (`app/scheduler.py`), the
documents module stores files (`app/docs`) and the database keeps the result (`app/db.py`).

It blocks: the loop (`app/loop.py`) calls it in a worker thread. No model is called here; the
learner and the repairer are functions handed in, and a regular read never reaches them.

What a read does, in order:
  1. the list, and at once a second look when a check of the list is suspect (Q10, step 4);
  2. the tenders' own pages: all of them at the attach, afterwards the new and changed ones,
     those whose documents are not in, and the rotation (`plan_incremental_read`);
  3. the content checks, and a look at the own page of every tender that left the list (C4);
  4. `decide`; only a read that passed is published, otherwise the last good tenders stay;
  5. the documents, soonest deadline first, each judged before it is stored.

Known gaps, said plainly: a suspect on lost values (C3) or null rates (C5) is confirmed
without a second fetch of the pages; the canary (C6) is not run, the rotation re-reads known
pages instead; the facts of an incident (when an outage began, repair attempts) are kept in
memory by the loop, because no record has a place for them yet.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.checks import (
    DEFAULT_SETTINGS as DEFAULT_CHECKS, CheckSettings, DetailLook, Effect, ListFacts, block_check, confirm,
    confirm_missing, duplicate_ids, effect_of, files_failed, fingerprint, known_ids_missing,
    known_tenders_reproduce, list_outcome, null_rates, paging_complete, printed_total, robots_check, shape,
    shape_problems, stale, structure, structure_floor, transport_check, without_bad_values,
)
from app.checks.result import Cause, failed, observed_of
from app.db import Database, UnknownPortal
from app.docs import Announced, DocumentResult, FileStore, announced_too_large, outcome_judge, provisional_file_id
from app.docs.names import choose_name
from app.fetch.interface import Fetch, FetchFailed, RobotsForbidden, RobotsUnavailable
from app.models import (
    AgentStep, CheckResult, DocsStatus, FileRecord, Portal, PortalState, Recipe, Run, RunResult, RunStats,
    SkipReason, StepKind, TenderFile, TenderRecord, utcnow,
)
from app.recipe.resolve import FieldRead
from app.recipe.run import DetailRead, Exchange, Item, ListRead, judge_look, known_item, read_detail, read_list, settle
from app.recipe.schema import (
    AuthoredRecipe, Expectations, FieldExpectation, FieldName, NodeRole, RecipeBody, StructureProfile,
)
from app.recipe.settings import DEFAULT_RECIPE_SETTINGS, RecipeSettings
from app.scheduler import (
    DEFAULT_SETTINGS as DEFAULT_SCHEDULE, AttachDecision, AttachProgress, DocumentNeed, KnownTender, ListRow,
    SchedulerSettings, attach_decision, document_order, estimate_document_seconds, plan_incremental_read,
    read_interval,
)
from app.state import Decision, ReadFacts, decide

ROW_HASH = "_row_hash"  # kept in TenderRecord.raw until the record has a field for it
PUBLISH_STEP = "publish"  # the step a read records when it publishes; its args hold `delivered`
HOLD_STEP = "hold"  # the step of an attach whose tenders are read but not delivered yet


@dataclass(frozen=True)
class Learned:
    """What a learner hands back for a portal it has not seen."""

    recipe: AuthoredRecipe
    timezone: str | None = None
    country_code: str | None = None
    fingerprint: str | None = None
    model_calls: int = 0


class Learner(Protocol):
    def __call__(self, portal: Portal, run_id: str) -> Learned | None: ...


class Repairer(Protocol):
    def __call__(self, portal: Portal, recipe: RecipeBody, failed: Sequence[CheckResult], run_id: str
                 ) -> Learned | None: ...


@dataclass
class Incident:
    """What the state machine must remember between reads of one portal (kept in memory for now)."""

    outage_since: datetime | None = None
    outage_retries: int = 0
    broken_since: datetime | None = None
    repair_attempts: int = 0
    repairs_tried: list[str] = field(default_factory=list)
    repairs_today: int = 0
    repairs_day: str | None = None
    given_up_structures: set[str] = field(default_factory=set)
    failed_at: datetime | None = None
    failed_checks: int = 0
    last_check_at: datetime | None = None
    next_try_at: datetime | None = None
    last_full_started_at: datetime | None = None
    list_seconds: float = 0.0
    list_pages: int = 1
    newest_first: bool = False


@dataclass
class ReadOutcome:
    """What one read came to."""

    decision: Decision | None
    state: PortalState
    passed: bool
    gone: bool = False  # the portal was deleted while the read ran


class Reader:
    """Reads portals. One instance for the process; every method blocks."""

    def __init__(self, database: Database, fetch: Fetch, files: Callable[[], FileStore], *,
                 learn: Learner | None = None, repair: Repairer | None = None,
                 checks: CheckSettings = DEFAULT_CHECKS, schedule: SchedulerSettings = DEFAULT_SCHEDULE,
                 recipes: RecipeSettings = DEFAULT_RECIPE_SETTINGS, now: Callable[[], datetime] = utcnow,
                 ignore_robots: bool = False) -> None:
        self.db, self.fetch, self._files = database, fetch, files
        self.learn, self.repair = learn, repair
        self.checks, self.schedule, self.recipes = checks, schedule, recipes
        self.now, self.ignore_robots = now, ignore_robots

    # == One read ==

    def read(self, portal_id: str, run: Run, incident: Incident, *, first_page_only: bool = False,
             cancel: threading.Event | None = None) -> ReadOutcome:
        """Read the portal for this run, write everything, and say what it came to. Never raises
        for what a portal does; a deleted portal ends the read quietly, and once `cancel` is set
        no further request is sent."""
        try:
            return _Read(self, portal_id, run, incident, first_page_only, cancel).go()
        except (UnknownPortal, Cancelled):
            return ReadOutcome(None, PortalState.failed, False, gone=True)


class Cancelled(Exception):
    """The portal was deleted while its read ran."""


class _Stoppable:
    """The network layer for one read: every call is refused once the portal is forgotten."""

    def __init__(self, inner: Fetch, cancel: threading.Event | None) -> None:
        self._inner, self._cancel = inner, cancel

    def __getattr__(self, name: str):
        if self._cancel is not None and self._cancel.is_set():
            raise Cancelled()
        return getattr(self._inner, name)


class _Read:
    """The state of one read while it runs."""

    def __init__(self, reader: Reader, portal_id: str, run: Run, incident: Incident, first_page_only: bool,
                 cancel: threading.Event | None = None) -> None:
        self.r, self.db, self.run, self.incident = reader, reader.db, run, incident
        self.cancel = cancel
        self.fetch: Fetch = _Stoppable(reader.fetch, cancel)  # type: ignore[assignment]
        self.portal_id, self.first_page_only = portal_id, first_page_only
        self.results: dict[str, CheckResult] = {}
        self.exchanges: list[Exchange] = []
        self.seq = 0
        self.stats = RunStats()
        self.model_calls = 0
        self.started = reader.now()

    # -- small helpers --

    def step(self, name: str, summary: str, started: float | None = None, error: str | None = None,
             args: dict | None = None) -> None:
        self.seq += 1
        took = int((time.monotonic() - started) * 1000) if started is not None else None
        self.db.add_step(AgentStep(run_id=self.run.id, seq=self.seq, kind=StepKind.note, name=name,
                                   summary=summary, duration_ms=took, error=error, args=args))

    def add(self, *results: CheckResult | None) -> None:
        for result in results:
            if result is not None:
                self.results[result.name] = result

    def transport(self, exchanges: Sequence[Exchange]) -> CheckResult | None:
        """The transport check of a group of requests: the first that failed, else the last."""
        worst = None
        for exchange in exchanges:
            if exchange.robots_forbidden:
                continue
            row = transport_check(self.run.id, exchange.answer, tries=exchange.tries,
                                  at_slowest_rate=exchange.at_slowest_rate, settings=self.r.checks)
            if worst is None or (worst.passed and not row.passed):
                worst = row
        return worst

    # -- the read --

    def go(self) -> ReadOutcome:
        portal = self.db.get_portal(self.portal_id)
        if portal is None:
            raise UnknownPortal(self.portal_id)
        self.portal = portal
        stored = self.db.active_recipe(portal.id)
        self.attach = stored is None
        learned: Learned | None = None
        if stored is None:
            learned = self._learn()
            if learned is None:
                return self._finish_without_recipe()
            self.body = RecipeBody.from_authored(learned.recipe)
            portal = self.portal = portal.model_copy(update={
                "timezone": learned.timezone or portal.timezone,
                "country_code": learned.country_code or portal.country_code,
                "fingerprint": self._software(learned)})
        else:
            self.body = RecipeBody.model_validate(stored.body)
        self.known = [] if self.attach else self.db.known_tenders(portal.id)
        decision, records, plan_unlisted, details = self._read_and_decide()
        outcome = self._apply(decision, records, plan_unlisted, details, learned)
        return outcome

    def _learn(self) -> Learned | None:
        if self.r.learn is None:
            return None
        began = time.monotonic()
        learned = self.r.learn(self.portal, self.run.id)
        if learned is not None:
            self.model_calls += learned.model_calls
            self.step("learn", f"Learned how to read the portal: {learned.recipe.rationale}", began)
        return learned

    def _finish_without_recipe(self) -> ReadOutcome:
        reason = ("No recipe could be learned for this portal, so nothing can be read. A person is needed."
                  if self.r.learn is not None else
                  "This build has no learner for this portal, so nothing can be read.")
        self.step("learn", reason, error="no recipe")
        self._save_portal(PortalState.failed, reason, Cause.breakage)
        self._save_run(False, PortalState.failed, reason, error="no recipe")
        return ReadOutcome(None, PortalState.failed, False)

    def _list_checks(self, listed: ListRead) -> dict[str, CheckResult]:
        """Steps 1 to 3 of Q10 for the list alone."""
        run_id, out = self.run.id, {}
        signs = self.body.expectations.usual_signs if self.body.expectations else []

        def put(row: CheckResult | None) -> None:
            if row is not None:
                out[row.name] = row

        put(self.transport(listed.exchanges))
        try:
            every = listed.robots_forbidden or self.fetch.robots_forbids_every_path(self.portal.id, self.portal.url)
        except (RobotsUnavailable, RobotsForbidden, LookupError, NotImplementedError):
            every = listed.robots_forbidden
        put(robots_check(run_id, forbids_every_path=bool(every), ignored=self.r.ignore_robots))
        facts = ListFacts(rows=listed.rows, answer=listed.list_answer, printed_total=listed.printed_total,
                          empty_marker=listed.empty_marker, api_empty=listed.api_empty)
        outcome = list_outcome(run_id, facts, usual_signs=signs)
        put(outcome)
        put(block_check(run_id, listed.list_answer, outcome_missing=not outcome.passed, usual_signs=signs))
        if not outcome.passed or listed.first_page_only:
            return out
        put(paging_complete(run_id, reached_end=listed.reached_end, pages=listed.pages))
        put(duplicate_ids(run_id, listed.ids))
        put(printed_total(run_id, extracted=len(listed.items), printed=listed.printed_total))
        profile = self._profile(self._list_node_id())
        if profile is not None and listed.rows:
            put(structure(run_id, listed.structure_paths, profile.paths, floor=profile.floor))
        return out

    def _list_node_id(self) -> str:
        return next(node.id for node in self.body.nodes if node.role is NodeRole.list)

    def _profile(self, node_id: str) -> StructureProfile | None:
        expectations = self.body.expectations
        if expectations is None:
            return None
        return next((p for p in expectations.structures if p.node == node_id), None)

    def _read_list(self) -> tuple[ListRead, dict[str, CheckResult]]:
        began = time.monotonic()
        listed = read_list(self.body, self.fetch, self.portal, first_page_only=self.first_page_only,
                           settings=self.r.recipes)
        first = self._list_checks(listed)
        suspects = [name for name, row in first.items() if effect_of(row) is Effect.suspect]
        self.exchanges += listed.exchanges
        self.step("read_list", f"Read the tender list: {listed.pages} page(s), {listed.rows} row(s), "
                               f"{len(listed.items)} tender(s).", began)
        if not suspects:
            return listed, first
        # The second look: the same part again, at once (Q10, step 4).
        began = time.monotonic()
        again = read_list(self.body, self.fetch, self.portal, first_page_only=self.first_page_only,
                          settings=self.r.recipes)
        second = self._list_checks(again)
        self.exchanges += again.exchanges
        settled = dict(second)
        for name in suspects:
            if name in second:
                settled[name] = confirm(first[name], second[name])
            else:  # the second look did not get as far as this check: it stands as confirmed
                settled[name] = confirm(first[name], first[name])
        self.step("second_look", f"Looked a second time because of: {', '.join(suspects)}. "
                                 f"The list gave {again.rows} row(s).", began)
        return again, settled

    def _read_and_decide(self) -> tuple[Decision, dict[str, TenderRecord], tuple[str, ...], dict[str, DetailRead]]:
        run_id, now = self.run.id, self.r.now()
        listed, list_results = self._read_list()
        self.listed = listed
        self.add(*list_results.values())
        self.stats.pages_fetched = listed.pages
        self.stats.tenders_seen = len(listed.items)
        incident = self.incident
        known_by_id = {record.tender_id: record for record in self.known}
        records: dict[str, TenderRecord] = {}
        details: dict[str, DetailRead] = {}
        unlisted: tuple[str, ...] = ()
        list_arrived = list_results.get("list_outcome") is not None and list_results["list_outcome"].passed
        blocked_or_out = any(effect_of(row) in (Effect.block, Effect.outage) for row in list_results.values())

        if list_arrived and not blocked_or_out:
            items = {item.tender_id: item for item in listed.items}
            interval = read_interval(listed.seconds, self.r.schedule)
            if self.attach or not self.known:
                to_read = list(items)
            else:
                plan = plan_incremental_read(
                    [KnownTender(k.tender_id, k.raw.get(ROW_HASH) or "", k.submission_deadline,
                                 k.detail_fetched_at, k.docs_status is not DocsStatus.pending)
                     for k in self.known],
                    [ListRow(item.tender_id, item.row_hash, item.deadline) for item in listed.items],
                    now, interval, self.r.schedule)
                to_read = list(dict.fromkeys([*plan.fetch, *plan.documents_pending, *plan.rotation]))
                unlisted = plan.unlisted if not listed.first_page_only else ()
            details = self._read_details([items[tender_id] for tender_id in to_read if tender_id in items])
            records = self._records(items, details, known_by_id, now)
            self._content_checks(records, known_by_id, listed, details, unlisted, now)

        last_good = self.portal.last_success_at
        interval = read_interval(listed.seconds, self.r.schedule)
        self.add(stale(run_id, state=self.portal.state, last_good_at=last_good, now=now, read_interval=interval,
                       settings=self.r.checks))
        decision = self._decide(records, known_by_id, unlisted, now)
        if decision.spot_check_needed:
            # No model is wired into the loop yet (stream B): a finding that only the spot check
            # can settle counts as a breakage, so that it is never published unchecked.
            asked = next((row for row in self.results.values() if effect_of(row) is Effect.spot_check), None)
            self.add(failed(run_id, "spot_check", "The values could not be checked against the page: "
                            f"{asked.message if asked else 'a check asked for the model.'}", cause=Cause.breakage))
            decision = self._decide(records, known_by_id, unlisted, now)
        return decision, records, unlisted, details

    def _read_details(self, items: Sequence[Item]) -> dict[str, DetailRead]:
        began = time.monotonic()
        out: dict[str, DetailRead] = {}
        unanswered: list[Exchange] = []
        for item in items:
            if not item.steps:
                continue
            detail = read_detail(self.body, self.fetch, self.portal, item, settings=self.r.recipes)
            out[item.tender_id] = detail
            self.exchanges += detail.exchanges
            unanswered += [e for e in detail.exchanges if not e.answered and not e.robots_forbidden]
            if len(unanswered) >= 3 and len(unanswered) == sum(len(d.exchanges) for d in out.values()):
                break  # nothing answers: this is an outage, not a list of broken pages
        if out:
            self.step("read_details", f"Read the own page of {len(out)} tender(s); "
                                      f"{sum(1 for d in out.values() if not d.complete)} did not arrive whole.", began)
        asked = sum(len(d.exchanges) for d in out.values())
        if unanswered and len(unanswered) * 2 >= asked:
            row = self.transport(unanswered)
            if row is not None and not row.passed and "outage" not in {r.name for r in self.results.values()
                                                                        if not r.passed}:
                self.add(row)
        return out

    def _records(self, items: dict[str, Item], details: dict[str, DetailRead],
                 known: dict[str, TenderRecord], now: datetime) -> dict[str, TenderRecord]:
        """A record for every listed tender: read now where its page was read, as stored otherwise."""
        reads: dict[str, dict[FieldName, FieldRead]] = {}
        urls: dict[str, list[str]] = {}
        addresses: dict[str, str | None] = {}
        for tender_id, item in items.items():
            detail = details.get(tender_id)
            whole = detail is not None and detail.complete
            if tender_id in known and not whole and (detail is not None or item.steps):
                continue  # a known tender whose page was not read (or not whole) keeps its record
            reads[tender_id] = detail.fields if whole else item.fields
            urls[tender_id] = [item.page_url, *(detail.urls if detail else [])]
            addresses[tender_id] = item.address
        fresh = settle(self.portal.id, reads, last_good=None if (self.attach or not known) else known, urls=urls,
                       addresses=addresses, run_id=self.run.id, settings=self.r.recipes)
        problems = shape_problems(list(fresh.values()), id_pattern=self.body.identity.shape)
        self.add(*shape(self.run.id, list(fresh.values()), id_pattern=self.body.identity.shape))
        out: dict[str, TenderRecord] = {}
        for tender_id, item in items.items():
            old = known.get(tender_id)
            record = fresh.get(tender_id)
            if record is not None:
                record = without_bad_values(record, problems)
            if record is None:
                if old is not None:
                    out[tender_id] = old.model_copy(update={"listed": True, "last_seen_at": now})
                continue
            detail = details.get(tender_id)
            whole = detail is not None and detail.complete
            read_whole = whole or not item.steps
            raw = {**record.raw, ROW_HASH: item.row_hash if read_whole else ""}
            update = {"raw": raw, "listed": True, "last_seen_at": now, "last_changed_at": now,
                      "detail_fetched_at": now if read_whole else None}
            if old is not None:
                update |= {"first_seen_at": old.first_seen_at, "docs_status": old.docs_status}
            record = record.model_copy(update=update)
            out[tender_id] = record.model_copy(update={"content_hash": record.compute_hash([])})
        return out

    def _content_checks(self, records: dict[str, TenderRecord], known: dict[str, TenderRecord], listed: ListRead,
                        details: dict[str, DetailRead], unlisted: Sequence[str], now: datetime) -> None:
        run_id, checks = self.run.id, self.r.checks
        if not known:
            return
        last_good = list(known.values())
        reread = [records[t] for t in details if t in records and t in known]
        rows = known_tenders_reproduce(run_id, reread, last_good, settings=checks)
        earlier_nulls = {name: sum(1 for k in last_good if getattr(k, name) is None)
                         for name in ("url", "title", "buyer_name", "publication_date", "submission_deadline")}
        new = [record for tender_id, record in records.items() if tender_id not in known]
        rows += null_rates(run_id, new, earlier_nulls=earlier_nulls, earlier_rows=len(last_good), settings=checks)
        for row in rows:
            # These suspects are settled without a second fetch: the pages were read moments ago.
            self.add(confirm(row, row) if effect_of(row) is Effect.suspect else row)
        if listed.first_page_only:
            return
        since = now - self.portal.last_success_at if self.portal.last_success_at else None
        missing = known_ids_missing(run_id, last_good, [item.tender_id for item in listed.items], now=now,
                                    since_last_good=since, settings=checks)
        if effect_of(missing) is not Effect.suspect:
            self.add(missing)
            return
        looks: list[DetailLook] = []
        self.looked: dict[str, str] = {}
        for tender_id in observed_of(missing).get("look_at", []):
            item = known_item(self.body, self.portal, known[tender_id])
            if item is None:
                outcome = "unclear"
            else:
                detail = read_detail(self.body, self.fetch, self.portal, item, settings=self.r.recipes)
                self.exchanges += detail.exchanges
                outcome = judge_look(self.body, detail, now, self.r.recipes).value
            looks.append(DetailLook(tender_id=tender_id, outcome=outcome))
            self.looked[tender_id] = outcome
        structure_row = self.results.get("structure")
        total = self.results.get("printed_total")
        outcome_row = self.results.get("list_outcome")
        self.add(confirm_missing(
            missing, looks,
            structure_intact=structure_row is not None and structure_row.passed,
            printed_total_agrees=listed.printed_total is not None and total is not None and total.passed,
            proven_empty=outcome_row is not None and bool(observed_of(outcome_row).get("empty"))))
        self.step("missing_tenders", f"{len(looks)} tender(s) left the list; looked at their own pages: "
                                     + ", ".join(f"{t} {o}" for t, o in self.looked.items()) + ".")

    def _decide(self, records: dict[str, TenderRecord], known: dict[str, TenderRecord], unlisted: Sequence[str],
                now: datetime) -> Decision:
        incident = self.incident
        open_now = sum(1 for record in records.values() if record.effective_status(now).value == "open")
        day = now.date().isoformat()
        structure_hash = fingerprint(self.listed.structure_paths) if self.listed.structure_paths else None
        facts = ReadFacts(
            now=now, state_before=self.portal.state, cause_before=self.portal.cause,
            full_read=not self.first_page_only, open_tenders=open_now,
            new_tenders=sum(1 for tender_id in records if tender_id not in known),
            closed_tenders=len(unlisted), last_good_at=self.portal.last_success_at,
            last_good_tenders=sum(1 for k in known.values() if k.effective_status(now).value == "open"),
            outage_since=incident.outage_since, next_try_at=incident.next_try_at,
            broken_since=incident.broken_since, repair_attempts_used=incident.repair_attempts,
            repairs_tried=tuple(incident.repairs_tried),
            repairs_today=incident.repairs_today if incident.repairs_day == day else 0,
            structure_given_up=structure_hash is not None and structure_hash in incident.given_up_structures)
        return decide(list(self.results.values()), facts, self.r.checks)

    # -- writing --

    def _save_portal(self, state: PortalState, reason: str, cause: Cause | None, **more) -> None:
        current = self.db.get_portal(self.portal.id)
        if current is None:
            raise UnknownPortal(self.portal.id)
        update = {"state": state, "reason": reason, "cause": cause, "timezone": self.portal.timezone,
                  "country_code": self.portal.country_code, "fingerprint": self.portal.fingerprint, **more}
        self.portal = current.model_copy(update=update)
        self.db.update_portal(self.portal)

    def _save_run(self, ok: bool, state: PortalState, reason: str, error: str | None = None) -> None:
        self.stats.http_requests = len(self.exchanges)
        self.db.add_checks(self.results.values())
        self.run = self.run.model_copy(update={
            "finished_at": self.r.now(), "result": RunResult.ok if ok else RunResult.failed,
            "state_after": state, "reason_after": reason, "stats": self.stats, "model_calls": self.model_calls,
            "recipe_version": self.portal.recipe_version, "error": error})
        self.db.save_run(self.run)

    def _expectations(self, records: dict[str, TenderRecord], details: dict[str, DetailRead]) -> Expectations:
        """What this read measured, stored with the recipe after a read that passed."""
        names = ("url", "title", "buyer_name", "publication_date", "submission_deadline", "reference_number",
                 "description", "procedure_type", "contract_nature")
        fields = [FieldExpectation(name=FieldName(name), rows=len(records),
                                   filled=sum(1 for r in records.values() if getattr(r, name) is not None))
                  for name in names]
        structures = []
        if self.listed.structure_paths:
            structures.append(StructureProfile(node=self._list_node_id(), paths=sorted(self.listed.structure_paths),
                                               floor=structure_floor([self.listed.structure_paths], self.r.checks)))
        by_node: dict[str, list[frozenset[str]]] = {}
        for detail in details.values():
            for node_id, paths in detail.structure_paths.items():
                if paths and len(by_node.setdefault(node_id, [])) < 10:
                    by_node[node_id].append(paths)
        for node_id, pages in by_node.items():
            union = sorted(set().union(*pages))
            structures.append(StructureProfile(node=node_id, paths=union,
                                               floor=structure_floor(pages, self.r.checks)))
        return Expectations(fields=fields, structures=structures, usual_signs=[], list_pages=self.listed.pages,
                            list_read_seconds=self.listed.seconds)

    def _software(self, learned: Learned) -> str | None:
        """The portal software a learned recipe is for: the family the recipe names, else what
        the learner detected, else what the portal is already known to run.

        The recipe's `family`, the `recipes.fingerprint` column (which reuse candidates are found
        by, `Database.recipes_for_fingerprint`) and `Portal.fingerprint` all hold this one value.
        """
        return learned.recipe.family or learned.fingerprint or self.portal.fingerprint

    def _store_recipe(self, learned: Learned, records, details) -> None:
        """Store the recipe of a read that passed and make it the active one. After a repair it
        names the version it replaces, so that the change can be shown (the dashboard's timeline)."""
        body = self.body.model_copy(update={"expectations": self._expectations(records, details)})
        version = self.db.next_recipe_version(self.portal.id)
        software = self._software(learned)
        self.db.add_recipe(Recipe(portal_id=self.portal.id, version=version,
                                  parent_version=self.portal.recipe_version, body=body.model_dump(mode="json"),
                                  fingerprint=software, created_by_run_id=self.run.id,
                                  rationale=learned.recipe.rationale))
        self.db.activate_recipe(self.portal.id, version)
        self.body = body
        self.portal = self.portal.model_copy(update={"recipe_version": version, "fingerprint": software})

    def _apply(self, decision: Decision, records: dict[str, TenderRecord], unlisted: Sequence[str],
               details: dict[str, DetailRead], learned: Learned | None) -> ReadOutcome:
        now, incident = self.r.now(), self.incident
        if not decision.read_passed:
            if decision.cause is Cause.outage and incident.outage_since is None:
                incident.outage_since = now
            if decision.cause is Cause.breakage and incident.broken_since is None:
                incident.broken_since = now
            if decision.state is PortalState.failed and incident.failed_at is None:
                incident.failed_at = now
                if decision.cause is Cause.breakage and self.listed.structure_paths:
                    incident.given_up_structures.add(fingerprint(self.listed.structure_paths))
            reason = decision.reason
            if decision.start_repair:
                reason = self._repair(decision, reason, now)
                if reason is None:  # the repair worked and its read was published
                    return self.repaired
            state = decision.state
            if state is PortalState.integrating and self.r.learn is not None and decision.cause is Cause.breakage \
                    and self.r.repair is None:
                state = PortalState.failed  # nothing can learn the portal again in this build
            self._save_portal(state, reason, decision.cause)
            self._save_run(False, state, reason)
            return ReadOutcome(decision, state, False)

        # The read passed: publish it.
        if learned is not None:
            self._store_recipe(learned, records, details)
        gone = [t for t in unlisted]
        withdrawn = {t for t, outcome in getattr(self, "looked", {}).items() if outcome == "withdrawn"}
        known = {record.tender_id: record for record in self.known}
        extra = [known[t].model_copy(update={"withdrawn": True, "listed": False, "last_changed_at": now})
                 for t in withdrawn if t in known and t not in records]
        pending = self._pending_documents(records, details)
        self.stats.tenders_new = sum(1 for t in records if t not in known)
        self.stats.tenders_changed = sum(1 for t, r in records.items()
                                         if t in known and known[t].content_hash != r.content_hash)
        self.stats.tenders_unlisted = len(gone)
        self.db.publish_tenders(self.portal.id, [*records.values(), *extra], documents=pending, unlisted=gone, at=now)
        incident.outage_since = incident.broken_since = incident.failed_at = incident.next_try_at = None
        incident.outage_retries = incident.failed_checks = incident.repair_attempts = 0
        incident.repairs_tried.clear()
        if not self.first_page_only:
            incident.last_full_started_at = self.started
            incident.list_seconds, incident.list_pages = self.listed.seconds, max(self.listed.pages, 1)
            facts = next((n.facts for n in self.body.nodes if n.role is NodeRole.list), None)
            incident.newest_first = bool(facts and facts.newest_first)
        # The tenders are stored now, but they are delivered only while the portal is not
        # `integrating` (`Database.list_tenders`). An attach whose documents fit the 10-minute
        # rule stays `integrating` until they are in (Q12, `attach_decision`): its tenders are
        # held back, and the publication is recorded at the moment they are really delivered.
        needs = self._needs(records, pending)
        delivered = len({*known, *records})
        published = f"Published {len(records)} tender(s); {len(gone)} left the list and are closed."
        state, reason = PortalState.serving, decision.reason
        if self.attach and needs:
            first = self._attach_decision(len(records), needs, now, already_serving=False)
            state, reason = first.state, first.reason
        self.held = state is PortalState.integrating
        if self.held:
            self.step(HOLD_STEP, f"Read and checked {len(records)} tender(s). They are held back, and the portal "
                                 f"stays integrating, until the documents of {len(needs)} of them are in.")
        self._save_portal(state, reason, None, last_success_at=now)
        if not self.held:
            self._published(published, delivered)

        def after_tender(done: int) -> None:
            """Say how far the documents of an attach are; deliver the tenders if the rule now says so."""
            if not self.attach or done >= len(needs):
                return
            at = self.r.now()
            current = self._attach_decision(len(records), needs[done:], at, already_serving=not self.held)
            self._save_portal(current.state, current.reason, None, last_success_at=now)
            if self.held and current.state is not PortalState.integrating:
                self.held = False
                self._published(f"The attach time limit passed. {published} "
                                f"The documents of {len(needs) - done} tender(s) follow.", delivered)

        file_rows = self._fetch_documents(needs, pending, after_tender) if needs else []
        if file_rows:
            self.add(files_failed(self.run.id, file_rows, earlier_failed=0, earlier_files=0, retried=True,
                                  settings=self.r.checks))
            decision = self._decide(records, known, unlisted, self.r.now())
        if decision.read_passed:
            self._save_portal(PortalState.serving, decision.reason, None, last_success_at=now)
            if self.held:
                self._published(f"{published} Their documents are in.", delivered)
            self._save_run(True, PortalState.serving, decision.reason)
            return ReadOutcome(decision, PortalState.serving, True)
        if decision.state is PortalState.failed and incident.failed_at is None:
            incident.failed_at = self.r.now()
        self._save_portal(decision.state, decision.reason, decision.cause)
        if self.held and decision.state is not PortalState.integrating:
            # The portal left `integrating` although the read did not pass in the end: the
            # tenders stored above are listed from now on, and the timeline must say so.
            self._published(f"{published} The documents did not pass their check.", delivered)
        self._save_run(False, decision.state, decision.reason)
        return ReadOutcome(decision, decision.state, False)

    def _attach_decision(self, total: int, needs: Sequence[DocumentNeed], now: datetime, *,
                         already_serving: bool) -> AttachDecision:
        """What the scheduler's attach rule says once every record is read and `needs` are the
        tenders whose documents are still to fetch."""
        remaining = estimate_document_seconds(needs, 1.0, self.r.schedule)
        return attach_decision(AttachProgress(
            started_at=self.started, now=now, tenders_total=total, records_done=total,
            documents_done=total - len(needs), documents_remaining_seconds=remaining,
            list_pages_read=self.listed.pages, already_serving=already_serving), self.r.schedule)

    def _published(self, summary: str, delivered: int) -> None:
        """Record a publication. `delivered` is every tender the portal delivers once it is in: a
        publish never removes one. The dashboard draws it per publication (docs/DASHBOARD_API.md)."""
        self.held = False
        self.step(PUBLISH_STEP, summary, args={"delivered": delivered})

    def _repair(self, decision: Decision, reason: str, now: datetime) -> str | None:
        """Start one repair attempt. Returns None when it worked, else the reason to show."""
        incident = self.incident
        day = now.date().isoformat()
        if incident.repairs_day != day:
            incident.repairs_day, incident.repairs_today = day, 0
        incident.repair_attempts += 1
        incident.repairs_today += 1
        if self.r.repair is None:
            incident.repairs_tried.append("no repairer in this build")
            self.step("repair", "A repair is due, but this build has no repairer.", error="no repairer")
            return reason
        began = time.monotonic()
        failed_rows = [row for row in self.results.values() if not row.passed]
        self._save_portal(decision.state, reason, decision.cause)
        fixed = self.r.repair(self.portal, self.body, failed_rows, self.run.id)
        if fixed is None:
            incident.repairs_tried.append("the repairer found no recipe")
            self.step("repair", "The repairer found no recipe that reads the portal.", began, error="no recipe")
            return reason
        self.model_calls += fixed.model_calls
        # Verify the new recipe with a full read of its own before it replaces the old one.
        trial = _Read(self.r, self.portal_id, self.run, incident, False, self.cancel)
        trial.portal, trial.attach, trial.known = self.portal, False, self.known
        trial.body = RecipeBody.from_authored(fixed.recipe)
        trial.seq, trial.model_calls = self.seq, self.model_calls
        trial_decision, records, unlisted, details = trial._read_and_decide()
        self.seq = trial.seq
        if not trial_decision.read_passed:
            incident.repairs_tried.append(f"a new recipe that failed {trial_decision.decided_by or 'its checks'}")
            self.step("repair", f"The repaired recipe did not pass its read: {trial_decision.reason}", began,
                      error="verification failed")
            return reason
        self.step("repair", f"The repaired recipe passed a full read: {fixed.recipe.rationale}", began)
        self.exchanges += trial.exchanges
        trial.exchanges = self.exchanges
        trial.results = {**trial.results}
        trial.seq = self.seq  # the step above was this read's: the trial's steps go on after it
        self.repaired = trial._apply(trial_decision, records, unlisted, details, fixed)
        self.seq = trial.seq
        return None

    # -- documents --

    def _pending_documents(self, records: dict[str, TenderRecord], details: dict[str, DetailRead]
                           ) -> dict[str, DocumentResult]:
        """The documents each page announced, as records without bytes: listed at once, fetched after."""
        out: dict[str, DocumentResult] = {}
        self.announced: dict[str, list[Announced]] = {}
        for tender_id, detail in details.items():
            record = records.get(tender_id)
            if record is None or detail.documents is None or not detail.complete:
                continue
            if record.docs_status is not DocsStatus.pending and self._same_documents(tender_id, detail.documents):
                continue
            result = DocumentResult()
            for position, doc in enumerate(detail.documents):
                file_id = provisional_file_id(self.portal.id, tender_id, doc.source_url)
                result.files.append(FileRecord(file_id=file_id, size_bytes=doc.size_bytes, source_url=doc.source_url))
                result.links.append(TenderFile(portal_id=self.portal.id, tender_id=tender_id, file_id=file_id,
                                               file_name=choose_name(doc.name, None, doc.source_url, None),
                                               position=position))
            out[tender_id] = result
            self.announced[tender_id] = detail.documents
            records[tender_id] = record.model_copy(update={
                "docs_status": DocsStatus.pending if detail.documents else DocsStatus.complete})
        return out

    def _same_documents(self, tender_id: str, announced: Sequence[Announced]) -> bool:
        stored = {record.source_url for _, record in self.db.tender_documents(self.portal.id, tender_id)}
        return bool(stored) and {doc.source_url for doc in announced} <= stored

    def _needs(self, records: dict[str, TenderRecord], pending: dict[str, DocumentResult]) -> list[DocumentNeed]:
        needs = [DocumentNeed(tender_id=tender_id, deadline=records[tender_id].submission_deadline,
                              files=len(self.announced[tender_id]))
                 for tender_id in pending if self.announced.get(tender_id)]
        return document_order(needs, self.r.schedule)

    def _fetch_documents(self, needs: Sequence[DocumentNeed], pending: dict[str, DocumentResult],
                         after_tender: Callable[[int], None] | None = None) -> list[CheckResult]:
        """Fetch and store the documents of each tender in turn. `after_tender` is called with
        the number of tenders done, after each one."""
        began = time.monotonic()
        store = self.r._files()
        rows: list[CheckResult] = []
        fetched = skipped = 0
        for done, need in enumerate(needs, start=1):
            tender_id = need.tender_id
            files: list[FileRecord] = []
            links: list[TenderFile] = []
            reasons: list[SkipReason | None] = []
            for doc in self.announced[tender_id]:
                result = self._one_document(doc, tender_id, len(links), store, rows)
                files += result.files
                links += result.links
                reasons.append(result.skipped)
                self.stats.bytes_downloaded += sum(f.size_bytes or 0 for f in result.files
                                                   if f.sha256 and not f.is_archive)
            got = [reason for reason in reasons if reason is None]
            fetched += len(got)
            skipped += len(reasons) - len(got)
            blocked = any(reason in (SkipReason.login_required, SkipReason.captcha) for reason in reasons)
            status = (DocsStatus.complete if len(got) == len(reasons)
                      else DocsStatus.blocked if blocked and not got else DocsStatus.partial)
            try:
                self.db.set_documents(self.portal.id, tender_id, files, links, docs_status=status,
                                      last_changed_at=self.r.now())
            except LookupError:
                continue
            if after_tender is not None:
                after_tender(done)
        self.stats.files_downloaded, self.stats.files_skipped = fetched, skipped
        self.step("documents", f"Fetched {fetched} document(s) of {len(needs)} tender(s); {skipped} skipped.", began)
        return rows

    def _one_document(self, doc: Announced, tender_id: str, position: int, store: FileStore,
                      rows: list[CheckResult]) -> DocumentResult:
        from app.docs import StaticDownload, store_document

        judge = outcome_judge(self.run.id, rows, usual_signs=self.body.expectations.usual_signs
                              if self.body.expectations else ())
        if announced_too_large(doc, store.settings.max_file_bytes):
            return store_document(StaticDownload(status=200, headers={}), doc, store=store, judge=judge,
                                  portal_id=self.portal.id, tender_id=tender_id, first_position=position)
        try:
            with self.fetch.download(self.portal.id, doc.source_url) as download:
                return store_document(download, doc, store=store, judge=judge, portal_id=self.portal.id,
                                      tender_id=tender_id, first_position=position)
        except (FetchFailed, RobotsForbidden, RobotsUnavailable, LookupError, OSError) as error:
            from app.checks import Answer, DownloadFacts, file_outcome
            name = choose_name(doc.name, None, doc.source_url, None)
            answer = error.answer if isinstance(error, FetchFailed) else Answer(status=None, page_load=False)
            rows.append(file_outcome(self.run.id, DownloadFacts(file_name=name, answer=answer)))
            record = FileRecord(file_id=provisional_file_id(self.portal.id, tender_id, doc.source_url),
                                size_bytes=doc.size_bytes, source_url=doc.source_url, skipped=SkipReason.http_error)
            return DocumentResult(files=[record], links=[TenderFile(
                portal_id=self.portal.id, tender_id=tender_id, file_id=record.file_id, file_name=name,
                position=position)], notes=[f"Skipped '{name}': {error}."])


def new_run(portal: Portal, trigger) -> Run:
    """A read run for a portal, not stored yet."""
    from app.models import RunKind
    return Run(id=uuid.uuid4().hex, portal_id=portal.id, kind=RunKind.read, trigger=trigger,
               state_before=portal.state)


__all__ = ["HOLD_STEP", "Incident", "Learned", "Learner", "PUBLISH_STEP", "ROW_HASH", "ReadOutcome", "Reader", "Repairer", "new_run"]
