"""Watchtower's store on SQLite (G2, Q15): the records of `app/models.py` in the tables of `app/schema.sql`.

What reads it:
  * the API, through the eight methods of `Store` in `app/interfaces.py`;
  * the worker, through the rest: portal state, runs, checks, steps, snapshots, recipes,
    and publishing tenders with their documents.

Threads (Q15). The API makes its store calls on one database thread of its own (`app/main.py`);
the worker calls from its own threads. Four threads reading SQLite in one process measured
130 ms a query against 2.3 ms for one, so the store holds two connections, each behind its
own lock: the reader serves every read and the writer every write. Whatever calls in, at
most two threads touch SQLite at a time, and WAL lets the reader go on while the writer
commits. Every read runs in one read transaction, so it sees one consistent moment; every
write runs in one `BEGIN IMMEDIATE` transaction. The reader's
lock covers only fetching the rows: building records from them (18 ms for 1,000 tenders,
against 3 ms in SQLite) happens after it is released, so a quick read never waits behind
another thread's records.

What the API sees is what the worker published. Tenders reach the table only through
`publish_tenders`, the worker calls it only for a read that passed its checks, and the API
sees none while a portal is `integrating`. So while a portal is `healing` the API still
serves the last good read.

Times. Our own timestamps are stored in UTC, so text order is time order; a tender's
deadline keeps the portal's own offset (CONVENTIONS.md, rule 4). A time without a zone is
refused rather than guessed.

Files. The store never touches the disk. `delete_portal` removes rows; `collect_orphan_files`
removes the file records no tender links to any more and returns them, so the caller can
delete their bytes with `FileStore.remove`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app import logs
from app.models import (
    AgentStep,
    CheckResult,
    DocsStatus,
    FileRecord,
    PlaceOfPerformance,
    Portal,
    PortalSnapshot,
    PortalState,
    Recipe,
    RecipeStatus,
    Run,
    RunKind,
    RunResult,
    RunStats,
    TenderFile,
    TenderRecord,
    TokenUsage,
    utcnow,
)

UTC = timezone.utc
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DB_FILE_NAME = "watchtower.db"

# One published tender with its documents in order: the shape `TenderRecord.to_api` takes.
PublishedTender = tuple[TenderRecord, list[tuple[TenderFile, FileRecord]]]


class UnknownPortal(LookupError):
    """The portal is not in the store, for example because it was deleted meanwhile."""


class UnknownRecord(LookupError):
    """A tender, run or recipe the call refers to is not in the store."""


class Documents(Protocol):
    """A tender's documents as `app.docs` returns them (`DocumentResult` fits).

    `files` holds every record to store, parents before children (an archive before its
    entries); `links` holds the tender's documents in order.
    """

    files: Sequence[FileRecord]
    links: Sequence[TenderFile]


@dataclass(frozen=True)
class DbSettings:
    """Where the database lives and how long a call waits for a lock. Built with `from_env()`."""

    path: Path = Path("/data") / DB_FILE_NAME
    # How long a statement waits when SQLite reports the file busy. Ours: WAL makes it rare
    # (Q15 measured no busy errors), and 5 s is far above any write we make.
    busy_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not self.busy_timeout_seconds > 0:
            raise ValueError("busy_timeout_seconds must be positive")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DbSettings":
        """The file `watchtower.db` under DATA_DIR; DB_BUSY_TIMEOUT_SECONDS overrides the wait."""
        env = os.environ if environ is None else environ
        kw: dict[str, Any] = {}
        if env.get("DATA_DIR"):
            kw["path"] = Path(env["DATA_DIR"]) / DB_FILE_NAME
        if env.get("DB_BUSY_TIMEOUT_SECONDS"):
            kw["busy_timeout_seconds"] = float(env["DB_BUSY_TIMEOUT_SECONDS"])
        return cls(**kw)


@dataclass(frozen=True)
class RunTotals:
    """What all runs of one portal add up to (`Database.run_totals`)."""

    usage: TokenUsage          # tokens and cost of every run, summed
    model_calls: int
    unaccounted_runs: int      # runs that called a model and recorded no tokens: their cost is not known
    reads_since: int           # reads started at or after the moment asked for


# == Values in and out of SQLite ==

def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} has no time zone; the store keeps aware times only")
    return value


def _utc(value: datetime | None, name: str) -> str | None:
    """Our own timestamps: UTC, fixed width, so that text order is time order."""
    if value is None:
        return None
    return _aware(value, name).astimezone(UTC).isoformat(timespec="microseconds")


def _local(value: datetime | None, name: str) -> str | None:
    """A portal's own time (a deadline): kept with the offset it came with."""
    if value is None:
        return None
    return _aware(value, name).isoformat()


def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _day(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(text: str | None) -> Any:
    return json.loads(text) if text is not None else None


# == Rows <-> records ==

_PORTAL_COLUMNS = ("id", "url", "url_key", "state", "reason", "fingerprint", "recipe_version", "list_url",
                   "country_code", "timezone", "cause", "last_success_at", "next_read_at",
                   "consecutive_failures", "created_at", "updated_at")


def _portal_values(p: Portal) -> tuple:
    return (p.id, p.url, p.url_key, p.state.value, p.reason, p.fingerprint, p.recipe_version, p.list_url,
            p.country_code, p.timezone, p.cause.value if p.cause else None,
            _utc(p.last_success_at, "last_success_at"), _utc(p.next_read_at, "next_read_at"),
            p.consecutive_failures, _utc(p.created_at, "created_at"), _utc(p.updated_at, "updated_at"))


def _portal(row: sqlite3.Row) -> Portal:
    return Portal(
        id=row["id"], url=row["url"], url_key=row["url_key"], state=row["state"], reason=row["reason"],
        fingerprint=row["fingerprint"], recipe_version=row["recipe_version"], list_url=row["list_url"],
        country_code=row["country_code"], timezone=row["timezone"], cause=row["cause"],
        last_success_at=_time(row["last_success_at"]), next_read_at=_time(row["next_read_at"]),
        consecutive_failures=row["consecutive_failures"], created_at=_time(row["created_at"]),
        updated_at=_time(row["updated_at"]),
    )


_RUN_COLUMNS = ("id", "portal_id", "kind", "trigger", "started_at", "finished_at", "result", "recipe_version",
                "state_before", "state_after", "reason_after", "stats", "input_tokens", "cached_input_tokens",
                "output_tokens", "reasoning_tokens", "cost_usd", "model_calls", "error")


def _run_values(r: Run) -> tuple:
    u = r.usage
    return (r.id, r.portal_id, r.kind.value, r.trigger.value, _utc(r.started_at, "started_at"),
            _utc(r.finished_at, "finished_at"), r.result.value if r.result else None, r.recipe_version,
            r.state_before.value, r.state_after.value if r.state_after else None, r.reason_after,
            r.stats.model_dump_json(), u.input_tokens, u.cached_input_tokens, u.output_tokens,
            u.reasoning_tokens, u.cost_usd, r.model_calls, r.error)


def _run(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"], portal_id=row["portal_id"], kind=row["kind"], trigger=row["trigger"],
        started_at=_time(row["started_at"]), finished_at=_time(row["finished_at"]), result=row["result"],
        recipe_version=row["recipe_version"], state_before=row["state_before"], state_after=row["state_after"],
        reason_after=row["reason_after"], stats=RunStats.model_validate_json(row["stats"]),
        usage=TokenUsage(input_tokens=row["input_tokens"], cached_input_tokens=row["cached_input_tokens"],
                         output_tokens=row["output_tokens"], reasoning_tokens=row["reasoning_tokens"],
                         cost_usd=row["cost_usd"]),
        model_calls=row["model_calls"], error=row["error"],
    )


_TENDER_COLUMNS = ("portal_id", "tender_id", "url", "title", "buyer_name", "publication_date",
                   "submission_deadline", "reference_number", "description", "procedure_type",
                   "contract_nature", "cpv_codes", "place", "withdrawn", "listed", "first_seen_at",
                   "last_seen_at", "last_changed_at", "content_hash", "detail_fetched_at", "docs_status",
                   "source_run_id", "source_urls", "raw")


def _tender_values(t: TenderRecord) -> tuple:
    return (t.portal_id, t.tender_id, t.url, t.title, t.buyer_name, _day(t.publication_date),
            _local(t.submission_deadline, "submission_deadline"), t.reference_number, t.description,
            t.procedure_type.value if t.procedure_type else None,
            t.contract_nature.value if t.contract_nature else None, _json(t.cpv_codes),
            _json(t.place.model_dump()) if t.place is not None else None, int(t.withdrawn), int(t.listed),
            _utc(t.first_seen_at, "first_seen_at"), _utc(t.last_seen_at, "last_seen_at"),
            _utc(t.last_changed_at, "last_changed_at"), t.content_hash,
            _utc(t.detail_fetched_at, "detail_fetched_at"), t.docs_status.value, t.source_run_id,
            _json(t.source_urls), _json(t.raw))


def _tender(row: sqlite3.Row) -> TenderRecord:
    place = _load(row["place"])
    return TenderRecord(
        portal_id=row["portal_id"], tender_id=row["tender_id"], url=row["url"], title=row["title"],
        buyer_name=row["buyer_name"],
        publication_date=date.fromisoformat(row["publication_date"]) if row["publication_date"] else None,
        submission_deadline=_time(row["submission_deadline"]), reference_number=row["reference_number"],
        description=row["description"], procedure_type=row["procedure_type"],
        contract_nature=row["contract_nature"], cpv_codes=_load(row["cpv_codes"]),
        place=PlaceOfPerformance(**place) if place is not None else None, withdrawn=bool(row["withdrawn"]),
        listed=bool(row["listed"]), first_seen_at=_time(row["first_seen_at"]),
        last_seen_at=_time(row["last_seen_at"]), last_changed_at=_time(row["last_changed_at"]),
        content_hash=row["content_hash"], detail_fetched_at=_time(row["detail_fetched_at"]),
        docs_status=row["docs_status"], source_run_id=row["source_run_id"],
        source_urls=_load(row["source_urls"]), raw=_load(row["raw"]),
    )


_FILE_COLUMNS = ("file_id", "sha256", "size_bytes", "content_type", "storage_path", "source_url",
                 "parent_file_id", "is_archive", "skipped", "downloaded_at")


def _file_values(f: FileRecord) -> tuple:
    return (f.file_id, f.sha256, f.size_bytes, f.content_type, f.storage_path, f.source_url, f.parent_file_id,
            int(f.is_archive), f.skipped.value if f.skipped else None, _utc(f.downloaded_at, "downloaded_at"))


def _file(row: sqlite3.Row, prefix: str = "") -> FileRecord:
    return FileRecord(
        file_id=row[prefix + "file_id"], sha256=row[prefix + "sha256"], size_bytes=row[prefix + "size_bytes"],
        content_type=row[prefix + "content_type"], storage_path=row[prefix + "storage_path"],
        source_url=row[prefix + "source_url"], parent_file_id=row[prefix + "parent_file_id"],
        is_archive=bool(row[prefix + "is_archive"]), skipped=row[prefix + "skipped"],
        downloaded_at=_time(row[prefix + "downloaded_at"]),
    )


_RECIPE_COLUMNS = ("portal_id", "version", "parent_version", "body_format", "body", "fingerprint", "status",
                   "created_by_run_id", "created_at", "validated_at", "rationale")


def _recipe_values(r: Recipe) -> tuple:
    return (r.portal_id, r.version, r.parent_version, r.body_format, _json(r.body), r.fingerprint, r.status.value,
            r.created_by_run_id, _utc(r.created_at, "created_at"), _utc(r.validated_at, "validated_at"),
            r.rationale)


def _recipe(row: sqlite3.Row) -> Recipe:
    return Recipe(
        portal_id=row["portal_id"], version=row["version"], parent_version=row["parent_version"],
        body_format=row["body_format"], body=_load(row["body"]), fingerprint=row["fingerprint"],
        status=row["status"], created_by_run_id=row["created_by_run_id"], created_at=_time(row["created_at"]),
        validated_at=_time(row["validated_at"]), rationale=row["rationale"],
    )


def _step(row: sqlite3.Row) -> AgentStep:
    usage = _load(row["usage"])
    return AgentStep(
        run_id=row["run_id"], seq=row["seq"], at=_time(row["at"]), kind=row["kind"], name=row["name"],
        summary=row["summary"], prompt_id=row["prompt_id"], args=_load(row["args"]), result=row["result"],
        duration_ms=row["duration_ms"], usage=TokenUsage(**usage) if usage is not None else None,
        error=row["error"],
    )


def _check(row: sqlite3.Row) -> CheckResult:
    return CheckResult(run_id=row["run_id"], name=row["name"], passed=bool(row["passed"]),
                       severity=row["severity"], observed=_load(row["observed"]),
                       expected=_load(row["expected"]), message=row["message"])


def _group_documents(portal_id: str, rows: Iterable[sqlite3.Row]) -> dict[str, list[tuple[TenderFile, FileRecord]]]:
    """Rows of `Database._document_rows` as each tender's (link, file) pairs, in order."""
    out: dict[str, list[tuple[TenderFile, FileRecord]]] = {}
    for r in rows:
        link = TenderFile(portal_id=portal_id, tender_id=r["tender_id"], file_id=r["f_file_id"],
                          file_name=r["file_name"], position=r["position"])
        out.setdefault(r["tender_id"], []).append((link, _file(r, "f_")))
    return out


def _insert(table: str, columns: Sequence[str], upsert_key: Sequence[str] | None = None) -> str:
    """INSERT for these columns; with `upsert_key`, a row with the same key is updated instead."""
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
    if upsert_key:
        rest = [c for c in columns if c not in upsert_key]
        sql += f" ON CONFLICT ({', '.join(upsert_key)}) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in rest)
    return sql


# == The store ==

log = logs.get("db")
SLOW_SECONDS = 1.0  # a write transaction or a wait for the writer lock longer than this is logged as a warning


class Database:
    """The store: `app.interfaces.Store` for the API, and every read and write the worker needs."""

    def __init__(self, path: Path | str, busy_timeout_seconds: float = DbSettings.busy_timeout_seconds) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = self._connect(busy_timeout_seconds)
        self._writer.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._reader = self._connect(busy_timeout_seconds)
        # A second reader for answers that take long (the tenders of a big portal): WAL lets it run beside the
        # writer and the first reader, so a 40 MB answer never holds up the dashboard's small reads.
        self._heavy = self._connect(busy_timeout_seconds)
        self._write_lock = threading.Lock()
        self._read_lock = threading.Lock()
        log.debug("database open at %s (busy timeout %ss)", self.path, busy_timeout_seconds)
        self._heavy_lock = threading.Lock()
        self._versions: dict[str, int] = {}  # per portal: moves when what GET /portals/{id}/tenders shows may have
        self._epoch = 0                      # moves when it may have for every portal

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Database":
        settings = DbSettings.from_env(environ)
        return cls(settings.path, settings.busy_timeout_seconds)

    def _connect(self, busy_timeout_seconds: float) -> sqlite3.Connection:
        # isolation_level=None: no implicit transactions; _reading and _writing open them.
        con = sqlite3.connect(self.path, timeout=busy_timeout_seconds, isolation_level=None,
                              check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")  # per connection, not stored in the file
        return con

    def close(self) -> None:
        with self._write_lock, self._read_lock, self._heavy_lock:
            self._reader.close()
            self._heavy.close()
            self._writer.close()

    def tenders_version(self, portal_id: str) -> tuple[int, int]:
        """A token that changes whenever the published tenders, their documents or the portal's state may have."""
        return self._epoch, self._versions.get(portal_id, 0)

    def _bump(self, portal_id: str | None = None) -> None:
        if portal_id is None:
            self._epoch += 1
        else:
            self._versions[portal_id] = self._versions.get(portal_id, 0) + 1

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        """One read transaction on the reader: every statement inside sees the same moment."""
        with self._read_lock:
            self._reader.execute("BEGIN")
            try:
                yield self._reader
            finally:
                self._reader.execute("COMMIT")

    @contextmanager
    def _writing(self) -> Iterator[sqlite3.Connection]:
        """One write transaction on the writer, rolled back if anything inside raises."""
        waited = time.monotonic()
        with self._write_lock:
            began = time.monotonic()
            if began - waited > SLOW_SECONDS:
                log.warning("a write waited %.2fs for the writer lock", began - waited)
            self._writer.execute("BEGIN IMMEDIATE")
            try:
                yield self._writer
                self._writer.execute("COMMIT")
            except BaseException as error:
                if self._writer.in_transaction:  # also when COMMIT itself failed: never leave one open
                    self._writer.execute("ROLLBACK")
                log.warning("write transaction rolled back after %.3fs: %s: %s", time.monotonic() - began,
                            type(error).__name__, logs.clip(error, 160))
                raise
            finally:
                if time.monotonic() - began > SLOW_SECONDS:
                    log.warning("a write transaction took %.2fs", time.monotonic() - began)

    @staticmethod
    def _require_portal(con: sqlite3.Connection, portal_id: str) -> None:
        if con.execute("SELECT 1 FROM portals WHERE id = ?", (portal_id,)).fetchone() is None:
            raise UnknownPortal(portal_id)

    # -- what the API calls (app.interfaces.Store) --

    def add_portal(self, portal: Portal) -> tuple[Portal, bool]:
        """Store a new portal, unless one with the same `url_key` exists. Atomic: one portal per address."""
        with self._writing() as con:
            row = con.execute("SELECT * FROM portals WHERE url_key = ?", (portal.url_key,)).fetchone()
            if row is not None:
                return _portal(row), False
            con.execute(_insert("portals", _PORTAL_COLUMNS), _portal_values(portal))
            log.debug("portal %s added: %s", portal.id, logs.safe_url(portal.url))
            return portal, True

    def get_portal(self, portal_id: str) -> Portal | None:
        with self._reading() as con:
            row = con.execute("SELECT * FROM portals WHERE id = ?", (portal_id,)).fetchone()
            return _portal(row) if row is not None else None

    def list_portals(self) -> list[Portal]:
        """Every portal, oldest first."""
        with self._reading() as con:
            rows = con.execute("SELECT * FROM portals ORDER BY created_at, id").fetchall()
        return [_portal(r) for r in rows]

    def delete_portal(self, portal_id: str) -> bool:
        """Remove a portal with its tenders, links, runs, checks, steps, snapshots and recipes.

        File records stay, since other tenders may share them: `collect_orphan_files` removes
        the ones nothing links to any more.
        """
        with self._writing() as con:
            deleted = con.execute("DELETE FROM portals WHERE id = ?", (portal_id,)).rowcount > 0
            log.debug("portal %s deleted: %s", portal_id, deleted)
        self._bump(portal_id)
        return deleted

    def count_tenders(self, portal_id: str) -> int:
        """How many tenders `list_tenders` returns: closed and withdrawn ones included."""
        with self._reading() as con:
            if not self._published(con, portal_id):
                return 0
            return con.execute("SELECT count(*) FROM tenders WHERE portal_id = ?", (portal_id,)).fetchone()[0]

    def list_tenders(self, portal_id: str) -> list[PublishedTender]:
        """The published tenders of a portal, by id, each with its documents in order.

        Nothing while the portal is `integrating`; while it is `healing`, the last good read,
        because a read that failed its checks is never published.
        """
        with self._reading() as con:
            if not self._published(con, portal_id):
                return []
            rows = con.execute("SELECT * FROM tenders WHERE portal_id = ? ORDER BY tender_id",
                               (portal_id,)).fetchall()
            doc_rows = self._document_rows(con, portal_id)
        docs = _group_documents(portal_id, doc_rows)
        return [(t, docs.get(t.tender_id, [])) for t in map(_tender, rows)]

    # One tender's documents as the API shows them, built by SQLite (json_object) instead of one Python object per
    # file: 248,000 files took 4.5 s as objects and 0.7 s this way, and the work runs without Python's lock.
    # A file is listed when its bytes are in (`FileRecord.deliverable`) or known and still loading (`pending`);
    # a skipped file or an archive is not. `links` counts every link, shown or not: "no links" is told apart
    # from "none shown" by the caller (documents null while pending, [] otherwise).
    _DOCUMENTS_JSON = """
        SELECT tender_id, json_group_array(json(doc)) FILTER (WHERE doc IS NOT NULL)
        FROM (SELECT tf.tender_id AS tender_id,
                     CASE WHEN f.skipped IS NULL AND f.is_archive = 0 AND f.sha256 IS NOT NULL
                          THEN json_object('fileName', tf.file_name, 'sizeBytes', COALESCE(f.size_bytes, 0),
                                           'sha256', f.sha256, 'path', '/files/' || f.file_id)
                          WHEN f.skipped IS NULL AND f.sha256 IS NULL
                          THEN json_object('fileName', tf.file_name, 'sizeBytes', f.size_bytes,
                                           'sha256', NULL, 'path', NULL)
                     END AS doc
              FROM tender_files tf JOIN files f ON f.file_id = tf.file_id
              WHERE tf.portal_id = ?
              ORDER BY tf.tender_id, tf.position, tf.file_name)
        GROUP BY tender_id"""

    def tenders_for_answer(self, portal_id: str) -> tuple[list[TenderRecord], dict[str, str]]:
        """What GET /portals/{id}/tenders needs, without a Python object per file: the tenders by id, and for each
        tender that has any link its documents as a JSON array text. Same rule as `list_tenders` for what is
        delivered (nothing while the portal is `integrating`). Runs on its own connection, beside every other read."""
        with self._heavy_lock:
            con = self._heavy
            con.execute("BEGIN")
            try:
                if not self._published(con, portal_id):
                    return [], {}
                rows = con.execute("SELECT * FROM tenders WHERE portal_id = ? ORDER BY tender_id",
                                   (portal_id,)).fetchall()
                documents = {row[0]: row[1] for row in con.execute(self._DOCUMENTS_JSON, (portal_id,))}
            finally:
                con.execute("COMMIT")
        return [_tender(row) for row in rows], documents

    def list_runs(self, portal_id: str) -> list[Run]:
        """Every read and repair of a portal, oldest first."""
        with self._reading() as con:
            rows = con.execute("SELECT * FROM runs WHERE portal_id = ? ORDER BY started_at, id",
                               (portal_id,)).fetchall()
        return [_run(r) for r in rows]

    def repair_run_ids(self, portal_id: str) -> set[str]:
        """The portal's runs in which a repair took place: the repairer worked in them (its steps
        are there from its first model call on), or they stored a recipe that replaces another.
        The reader repairs inside a read run, so the `runs` row itself says `read`."""
        with self._reading() as con:
            rows = con.execute(
                "SELECT DISTINCT s.run_id FROM agent_steps s JOIN runs r ON r.id = s.run_id"
                " WHERE r.portal_id = ? AND (s.name LIKE 'repair%' OR s.prompt_id LIKE 'repair/%')"
                " UNION SELECT created_by_run_id FROM recipes"
                " WHERE portal_id = ? AND parent_version IS NOT NULL AND created_by_run_id IS NOT NULL",
                (portal_id, portal_id)).fetchall()
            found = {row[0] for row in rows}
            if found:  # the contract: the first attach is a read, whatever happened in it
                found -= {row[0] for row in con.execute(
                    "SELECT id FROM runs WHERE portal_id = ? AND trigger = 'attach'", (portal_id,))}
        return found

    def get_file(self, file_id: str) -> FileRecord | None:
        with self._reading() as con:
            row = con.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()
            return _file(row) if row is not None else None

    @staticmethod
    def _published(con: sqlite3.Connection, portal_id: str) -> bool:
        row = con.execute("SELECT state FROM portals WHERE id = ?", (portal_id,)).fetchone()
        return row is not None and row["state"] != PortalState.integrating.value

    @staticmethod
    def _document_rows(con: sqlite3.Connection, portal_id: str, tender_id: str | None = None) -> list[sqlite3.Row]:
        sql = ("SELECT tf.tender_id, tf.file_name, tf.position, "
               + ", ".join(f"f.{c} AS f_{c}" for c in _FILE_COLUMNS)
               + " FROM tender_files tf JOIN files f ON f.file_id = tf.file_id WHERE tf.portal_id = ?")
        args: tuple = (portal_id,)
        if tender_id is not None:
            sql += " AND tf.tender_id = ?"
            args += (tender_id,)
        return con.execute(sql + " ORDER BY tf.tender_id, tf.position, tf.file_name", args).fetchall()

    # -- portals, for the worker --

    def update_portal(self, portal: Portal) -> bool:
        """Save a portal's state and what the worker learned. False when the portal is gone.

        Never inserts: a portal deleted while a read ran stays deleted. `url`, `url_key` and
        `created_at` are fixed at `add_portal`; `updated_at` is set here.
        """
        values = dict(zip(_PORTAL_COLUMNS, _portal_values(portal)))
        values["updated_at"] = _utc(utcnow(), "updated_at")
        fixed = ("id", "url", "url_key", "created_at")
        sets = [c for c in _PORTAL_COLUMNS if c not in fixed]
        with self._writing() as con:
            cur = con.execute(f"UPDATE portals SET {', '.join(f'{c} = ?' for c in sets)} WHERE id = ?",
                              [values[c] for c in sets] + [portal.id])
            changed = cur.rowcount > 0
        self._bump(portal.id)  # the state decides whether the tenders are delivered at all
        return changed

    # -- runs --

    def start_run(self, run: Run) -> Run:
        """Start a run, unless one is already running for the portal: then return that one.

        One run per portal at a time (DESIGN.md), so a refresh during a read or a repair
        answers with that run's id. Raises UnknownPortal when the portal is gone.
        """
        with self._writing() as con:
            self._require_portal(con, run.portal_id)
            row = con.execute("SELECT * FROM runs WHERE portal_id = ? AND finished_at IS NULL "
                              "ORDER BY started_at DESC, id DESC LIMIT 1", (run.portal_id,)).fetchone()
            if row is not None:
                log.debug("portal %s: run %s is running, so run %s did not start", run.portal_id, row["id"], run.id)
                return _run(row)
            con.execute(_insert("runs", _RUN_COLUMNS), _run_values(run))
            log.debug("portal %s: run %s started (%s, %s)", run.portal_id, run.id, run.kind.value, run.trigger.value)
            return run

    def save_run(self, run: Run) -> bool:
        """Save a run's progress or its end. False when the run is gone (its portal was deleted)."""
        sets = [c for c in _RUN_COLUMNS if c not in ("id", "portal_id", "kind", "trigger", "started_at")]
        values = dict(zip(_RUN_COLUMNS, _run_values(run)))
        with self._writing() as con:
            cur = con.execute(f"UPDATE runs SET {', '.join(f'{c} = ?' for c in sets)} WHERE id = ?",
                              [values[c] for c in sets] + [run.id])
            return cur.rowcount > 0

    def get_run(self, run_id: str) -> Run | None:
        with self._reading() as con:
            row = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            return _run(row) if row is not None else None

    def active_run(self, portal_id: str) -> Run | None:
        """The run going on for a portal, read or repair, if any."""
        with self._reading() as con:
            row = con.execute("SELECT * FROM runs WHERE portal_id = ? AND finished_at IS NULL "
                              "ORDER BY started_at DESC, id DESC LIMIT 1", (portal_id,)).fetchone()
            return _run(row) if row is not None else None

    def recent_runs(self, per_portal: int, *, portal_id: str | None = None,
                    kind: RunKind | None = None) -> dict[str, list[Run]]:
        """The newest `per_portal` runs of every portal (or of one), oldest first, in one query.

        For the dashboard, which shows the last runs of every portal at once; with `kind`,
        only reads or only repairs are counted. A portal without such a run has no key.
        """
        where, args = [], []
        if portal_id is not None:
            where.append("portal_id = ?")
            args.append(portal_id)
        if kind is not None:
            where.append("kind = ?")
            args.append(kind.value)
        sql = ("SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY portal_id ORDER BY started_at DESC, id DESC)"
               " AS newest FROM runs" + (" WHERE " + " AND ".join(where) if where else "") + ")"
               " WHERE newest <= ? ORDER BY portal_id, started_at, id")
        with self._reading() as con:
            rows = con.execute(sql, [*args, per_portal]).fetchall()
        out: dict[str, list[Run]] = {}
        for r in rows:
            out.setdefault(r["portal_id"], []).append(_run(r))
        return out

    def run_totals(self, reads_since: datetime) -> dict[str, RunTotals]:
        """Per portal, over every run it has: tokens, cost, model calls, and the reads started
        since a moment. A portal without a run has no key."""
        with self._reading() as con:
            rows = con.execute(
                "SELECT portal_id, SUM(input_tokens) AS input_tokens, SUM(cached_input_tokens) AS cached_input_tokens,"
                " SUM(output_tokens) AS output_tokens, SUM(reasoning_tokens) AS reasoning_tokens,"
                " SUM(cost_usd) AS cost_usd, SUM(model_calls) AS model_calls,"
                " SUM(model_calls > 0 AND input_tokens = 0 AND output_tokens = 0) AS unaccounted_runs,"
                " SUM(kind = ? AND started_at >= ?) AS reads_since FROM runs GROUP BY portal_id",
                (RunKind.read.value, _utc(reads_since, "reads_since"))).fetchall()
        return {r["portal_id"]: RunTotals(
            usage=TokenUsage(input_tokens=r["input_tokens"], cached_input_tokens=r["cached_input_tokens"],
                             output_tokens=r["output_tokens"], reasoning_tokens=r["reasoning_tokens"],
                             cost_usd=r["cost_usd"]),
            model_calls=r["model_calls"], unaccounted_runs=r["unaccounted_runs"], reads_since=r["reads_since"])
            for r in rows}

    def fail_open_runs(self, error: str = "The run was cut short by a restart.",
                       at: datetime | None = None) -> list[Run]:
        """After a restart: close every run left open as failed, and return them.

        Their portals are the ones to queue again (DESIGN.md, Rules the worker enforces).
        """
        at_text = _utc(at or utcnow(), "at")
        with self._writing() as con:
            ids = [r["id"] for r in con.execute("SELECT id FROM runs WHERE finished_at IS NULL")]
            con.execute("UPDATE runs SET finished_at = ?, result = ?, error = COALESCE(error, ?) "
                        "WHERE finished_at IS NULL", (at_text, RunResult.failed.value, error))
            if ids:
                log.info("%d run(s) left open by a restart were closed as failed", len(ids))
            return [_run(con.execute("SELECT * FROM runs WHERE id = ?", (i,)).fetchone()) for i in ids]

    # -- checks, steps, snapshots --

    def add_checks(self, checks: Iterable[CheckResult]) -> None:
        """Record check results. A check recorded again in the same run replaces the first row:
        a suspect that cleared is one passed row, with the first observation in `observed` (Q10)."""
        sql = _insert("run_checks", ("run_id", "name", "passed", "severity", "observed", "expected", "message"),
                      upsert_key=("run_id", "name"))
        with self._writing() as con:
            for c in checks:
                con.execute(sql, (c.run_id, c.name, int(c.passed), c.severity.value,
                                  _json(c.observed) if c.observed is not None else None,
                                  _json(c.expected) if c.expected is not None else None, c.message))

    def list_checks(self, run_id: str) -> list[CheckResult]:
        """A run's check results, in the order first recorded."""
        with self._reading() as con:
            rows = con.execute("SELECT * FROM run_checks WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
        return [_check(r) for r in rows]

    def add_step(self, step: AgentStep) -> None:
        """Record one step of what the system did; the dashboard reads only these (CONVENTIONS.md, rule 9)."""
        with self._writing() as con:
            con.execute(_insert("agent_steps", ("run_id", "seq", "at", "kind", "name", "summary", "prompt_id",
                                                "args", "result", "duration_ms", "usage", "error")),
                        (step.run_id, step.seq, _utc(step.at, "at"), step.kind.value, step.name, step.summary,
                         step.prompt_id, _json(step.args) if step.args is not None else None, step.result,
                         step.duration_ms, step.usage.model_dump_json() if step.usage is not None else None,
                         step.error))

    def list_steps(self, run_id: str) -> list[AgentStep]:
        with self._reading() as con:
            rows = con.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run_id,)).fetchall()
        return [_step(r) for r in rows]

    def recent_steps(self, name: str, per_portal: int) -> dict[str, list[AgentStep]]:
        """The newest `per_portal` steps with this name of every portal, oldest first, in one query.

        For the dashboard: the last publications of every portal are its `publish` steps.
        """
        with self._reading() as con:
            rows = con.execute(
                "SELECT * FROM (SELECT s.*, r.portal_id AS portal_id, ROW_NUMBER() OVER ("
                "PARTITION BY r.portal_id ORDER BY s.at DESC, s.run_id DESC, s.seq DESC) AS newest "
                "FROM agent_steps s JOIN runs r ON r.id = s.run_id WHERE s.name = ?) "
                "WHERE newest <= ? ORDER BY portal_id, at, run_id, seq", (name, per_portal)).fetchall()
        out: dict[str, list[AgentStep]] = {}
        for r in rows:
            out.setdefault(r["portal_id"], []).append(_step(r))
        return out

    def save_snapshot(self, snapshot: PortalSnapshot) -> None:
        """Store or replace a snapshot handed to a repair; page bodies stay on disk."""
        with self._writing() as con:
            con.execute(_insert("snapshots", ("id", "portal_id", "run_id", "captured_at", "body"), upsert_key=("id",)),
                        (snapshot.id, snapshot.portal_id, snapshot.run_id,
                         _utc(snapshot.captured_at, "captured_at"), snapshot.model_dump_json()))

    def latest_snapshot(self, portal_id: str) -> PortalSnapshot | None:
        with self._reading() as con:
            row = con.execute("SELECT body FROM snapshots WHERE portal_id = ? ORDER BY captured_at DESC, id DESC "
                              "LIMIT 1", (portal_id,)).fetchone()
            return PortalSnapshot.model_validate_json(row["body"]) if row is not None else None

    # -- recipes --

    def next_recipe_version(self, portal_id: str) -> int:
        with self._reading() as con:
            return con.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM recipes WHERE portal_id = ?",
                               (portal_id,)).fetchone()[0]

    def add_recipe(self, recipe: Recipe) -> None:
        """Store a new recipe version. Raises sqlite3.IntegrityError when the version exists,
        and UnknownPortal when the portal is gone. Use `activate_recipe` to make it the one reads use."""
        if recipe.status == RecipeStatus.active:
            raise ValueError("add the recipe as a candidate, then activate_recipe it")
        with self._writing() as con:
            self._require_portal(con, recipe.portal_id)
            con.execute(_insert("recipes", _RECIPE_COLUMNS), _recipe_values(recipe))
            log.debug("portal %s: recipe v%s stored as %s", recipe.portal_id, recipe.version, recipe.status.value)

    def get_recipe(self, portal_id: str, version: int) -> Recipe | None:
        with self._reading() as con:
            row = con.execute("SELECT * FROM recipes WHERE portal_id = ? AND version = ?",
                              (portal_id, version)).fetchone()
            return _recipe(row) if row is not None else None

    def active_recipe(self, portal_id: str) -> Recipe | None:
        """The recipe regular reads use."""
        with self._reading() as con:
            row = con.execute("SELECT * FROM recipes WHERE portal_id = ? AND status = ? ORDER BY version DESC "
                              "LIMIT 1", (portal_id, RecipeStatus.active.value)).fetchone()
            return _recipe(row) if row is not None else None

    def activate_recipe(self, portal_id: str, version: int, at: datetime | None = None) -> Recipe:
        """Make one version the active recipe: the one active before is retired, and the
        portal's `recipe_version` points at the new one, all in one transaction."""
        at_text = _utc(at or utcnow(), "at")
        with self._writing() as con:
            if con.execute("SELECT 1 FROM recipes WHERE portal_id = ? AND version = ?",
                           (portal_id, version)).fetchone() is None:
                raise UnknownRecord(f"recipe {version} of portal {portal_id}")
            con.execute("UPDATE recipes SET status = ? WHERE portal_id = ? AND status = ? AND version != ?",
                        (RecipeStatus.retired.value, portal_id, RecipeStatus.active.value, version))
            con.execute("UPDATE recipes SET status = ?, validated_at = COALESCE(validated_at, ?) "
                        "WHERE portal_id = ? AND version = ?", (RecipeStatus.active.value, at_text, portal_id, version))
            con.execute("UPDATE portals SET recipe_version = ?, updated_at = ? WHERE id = ?",
                        (version, at_text, portal_id))
            log.info("portal %s: recipe v%s is now the active recipe", portal_id, version)
            return _recipe(con.execute("SELECT * FROM recipes WHERE portal_id = ? AND version = ?",
                                       (portal_id, version)).fetchone())

    def reject_recipe(self, portal_id: str, version: int, rationale: str | None = None) -> bool:
        """Mark a candidate that failed validation; it is kept for the trace."""
        with self._writing() as con:
            cur = con.execute("UPDATE recipes SET status = ?, rationale = COALESCE(?, rationale) "
                              "WHERE portal_id = ? AND version = ? AND status = ?",
                              (RecipeStatus.rejected.value, rationale, portal_id, version,
                               RecipeStatus.candidate.value))
            log.info("portal %s: recipe v%s rejected (%s): %s", portal_id, version, cur.rowcount > 0, logs.clip(rationale, 120))
            return cur.rowcount > 0

    def recipes_for_fingerprint(self, fingerprint: str, exclude_portal_id: str | None = None) -> list[Recipe]:
        """Active recipes of other portals running the same software: reuse candidates (Q11)."""
        with self._reading() as con:
            rows = con.execute("SELECT * FROM recipes WHERE fingerprint = ? AND status = ? AND portal_id != ? "
                               "ORDER BY validated_at DESC, portal_id",
                               (fingerprint, RecipeStatus.active.value, exclude_portal_id or "")).fetchall()
        return [_recipe(r) for r in rows]

    # -- tenders and their documents --

    def publish_tenders(self, portal_id: str, records: Iterable[TenderRecord],
                        documents: Mapping[str, Documents] | None = None,
                        unlisted: Iterable[str] = (), at: datetime | None = None) -> int:
        """Publish what one read found, in one transaction. Returns how many records were written.

        Call it only for a read that passed its checks (or the share of an attach the
        scheduler decided to publish). For each record:
          * a tender already stored keeps its `first_seen_at`, and keeps its `lastChangedAt`
            when its `content_hash` is unchanged, so `?changedSince=` reports real changes only;
          * documents given for it in `documents` replace its document list (see `set_documents`).
        Tenders in `unlisted` that were listed become `listed = false` (closed), with
        `last_changed_at` set to `at`: leaving the list is a change the API shows.
        """
        at_text = _utc(at or utcnow(), "at")
        documents = documents or {}
        written = 0
        with self._writing() as con:
            self._require_portal(con, portal_id)
            sql = _insert("tenders", _TENDER_COLUMNS, upsert_key=("portal_id", "tender_id"))
            for record in records:
                if record.portal_id != portal_id:
                    raise ValueError(f"tender {record.tender_id} belongs to {record.portal_id}, not {portal_id}")
                values = dict(zip(_TENDER_COLUMNS, _tender_values(record)))
                old = con.execute("SELECT first_seen_at, last_changed_at, content_hash FROM tenders "
                                  "WHERE portal_id = ? AND tender_id = ?", (portal_id, record.tender_id)).fetchone()
                if old is not None:
                    values["first_seen_at"] = old["first_seen_at"]
                    if record.content_hash and record.content_hash == old["content_hash"]:
                        values["last_changed_at"] = old["last_changed_at"]
                con.execute(sql, [values[c] for c in _TENDER_COLUMNS])
                written += 1
            for tender_id, docs in documents.items():
                self._replace_documents(con, portal_id, tender_id, docs.files, docs.links)
            for tender_id in unlisted:
                con.execute("UPDATE tenders SET listed = 0, last_changed_at = ? "
                            "WHERE portal_id = ? AND tender_id = ? AND listed = 1", (at_text, portal_id, tender_id))
        log.debug("portal %s: published %d tender(s), %d with documents, %d left the list", portal_id, written,
                  len(documents), len(list(unlisted)) if not isinstance(unlisted, Iterator) else 0)
        self._bump(portal_id)
        return written

    def set_documents(self, portal_id: str, tender_id: str, files: Sequence[FileRecord],
                      links: Sequence[TenderFile], docs_status: DocsStatus | None = None,
                      last_changed_at: datetime | None = None) -> None:
        """Replace one published tender's document list, for documents that arrive after the
        tender (Q12). File records are stored or updated first, parents before children.

        A document whose bytes came in gets a new, hash-derived id; its provisional record is
        no longer linked, and `collect_orphan_files` removes it. Pass `last_changed_at` when
        the tender's visible content changed (its documents did).
        """
        with self._writing() as con:
            if con.execute("SELECT 1 FROM tenders WHERE portal_id = ? AND tender_id = ?",
                           (portal_id, tender_id)).fetchone() is None:
                raise UnknownRecord(f"tender {tender_id} of portal {portal_id}")
            self._replace_documents(con, portal_id, tender_id, files, links)
            if docs_status is not None:
                con.execute("UPDATE tenders SET docs_status = ? WHERE portal_id = ? AND tender_id = ?",
                            (docs_status.value, portal_id, tender_id))
            if last_changed_at is not None:
                con.execute("UPDATE tenders SET last_changed_at = ? WHERE portal_id = ? AND tender_id = ?",
                            (_utc(last_changed_at, "last_changed_at"), portal_id, tender_id))
            log.debug("portal %s tender %s: %d document(s) stored, docs_status=%s", portal_id, tender_id, len(files),
                      docs_status.value if docs_status else "unchanged")
        self._bump(portal_id)

    @staticmethod
    def _replace_documents(con: sqlite3.Connection, portal_id: str, tender_id: str,
                           files: Sequence[FileRecord], links: Sequence[TenderFile]) -> None:
        for link in links:
            if (link.portal_id, link.tender_id) != (portal_id, tender_id):
                raise ValueError(f"link to {link.file_id} belongs to {link.portal_id}/{link.tender_id}")
        file_sql = _insert("files", _FILE_COLUMNS, upsert_key=("file_id",))
        for f in files:
            con.execute(file_sql, _file_values(f))
        con.execute("DELETE FROM tender_files WHERE portal_id = ? AND tender_id = ?", (portal_id, tender_id))
        # A tender links a file once (the key is portal, tender, file). Two documents of one tender can hold the
        # same bytes (TenderNed's ZIPs repeat entries), which is one file: the first link, and its name, wins.
        seen: set[str] = set()
        unique = [l for l in links if not (l.file_id in seen or seen.add(l.file_id))]
        con.executemany(_insert("tender_files", ("portal_id", "tender_id", "file_id", "file_name", "position")),
                        [(portal_id, tender_id, l.file_id, l.file_name, l.position) for l in unique])

    def known_tenders(self, portal_id: str) -> list[TenderRecord]:
        """Every tender stored for a portal, whatever its state: the worker's view for planning
        an incremental read and for comparing with the last good read (Q10, Q12)."""
        with self._reading() as con:
            rows = con.execute("SELECT * FROM tenders WHERE portal_id = ? ORDER BY tender_id",
                               (portal_id,)).fetchall()
        return [_tender(r) for r in rows]

    def tender_documents(self, portal_id: str, tender_id: str) -> list[tuple[TenderFile, FileRecord]]:
        """One tender's documents in order, whatever the portal's state."""
        with self._reading() as con:
            rows = self._document_rows(con, portal_id, tender_id)
        return _group_documents(portal_id, rows).get(tender_id, [])

    def file_uses(self, now: datetime | None = None) -> list[tuple[FileRecord, bool]]:
        """Every link as (file, its tender is no longer open): what `app.docs.files_to_remove`
        takes to choose which bytes to drop first when the disk runs low (Q12)."""
        now = _aware(now or utcnow(), "now")
        with self._reading() as con:
            rows = con.execute(
                "SELECT t.withdrawn, t.listed, t.submission_deadline, "
                + ", ".join(f"f.{c} AS f_{c}" for c in _FILE_COLUMNS)
                + " FROM tender_files tf"
                " JOIN tenders t ON t.portal_id = tf.portal_id AND t.tender_id = tf.tender_id"
                " JOIN files f ON f.file_id = tf.file_id"
                " ORDER BY tf.portal_id, tf.tender_id, tf.position").fetchall()
        out: list[tuple[FileRecord, bool]] = []
        for r in rows:
            deadline = _time(r["submission_deadline"])
            gone = bool(r["withdrawn"]) or not r["listed"] or (deadline is not None and deadline <= now)
            out.append((_file(r, "f_"), gone))
        return out

    def collect_orphan_files(self) -> list[FileRecord]:
        """Remove the file records no tender links to, and return them so their bytes can go.

        An archive stays while an entry unpacked from it is still linked; it goes with the
        last of them. Content is shared across tenders and portals, so this runs after a
        delete or a replaced document list, never as part of one.
        """
        removed: list[FileRecord] = []
        with self._writing() as con:
            while True:
                rows = con.execute(
                    "SELECT * FROM files f WHERE NOT EXISTS (SELECT 1 FROM tender_files tf WHERE tf.file_id = f.file_id) "
                    "AND NOT EXISTS (SELECT 1 FROM files c WHERE c.parent_file_id = f.file_id)").fetchall()
                if not rows:
                    if removed:
                        log.debug("%d orphan file record(s) removed", len(removed))
                        self._bump()
                    return removed
                con.executemany("DELETE FROM files WHERE file_id = ?", [(r["file_id"],) for r in rows])
                removed.extend(_file(r) for r in rows)

    # -- costs --

    def portal_costs(self) -> dict[str, dict[str, float]]:
        """Model cost and tokens per portal, for the dashboard and the README (view portal_costs)."""
        with self._reading() as con:
            return {r["portal_id"]: {k: r[k] for k in r.keys() if k != "portal_id"}
                    for r in con.execute("SELECT * FROM portal_costs ORDER BY portal_id")}
