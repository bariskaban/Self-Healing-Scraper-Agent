/* Watchtower SQLite schema (Q7). One table per record in models.py.
   Times are ISO 8601 text with offset. JSON columns are TEXT holding JSON.
   DELETE /portals/{id} deletes the portal row; ON DELETE CASCADE removes the rest
   (workers must re-check that the portal still exists before every request). */

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS portals (
    id                   TEXT PRIMARY KEY,
    url                  TEXT NOT NULL,
    url_key              TEXT NOT NULL UNIQUE,        /* same address twice, same id */
    state                TEXT NOT NULL DEFAULT 'integrating'
                         CHECK (state IN ('integrating','serving','healing','failed')),
    reason               TEXT NOT NULL DEFAULT '',
    fingerprint          TEXT,                         /* portal software (Q11) */
    recipe_version       INTEGER,                      /* active recipe */
    list_url             TEXT,
    country_code         TEXT,
    timezone             TEXT,
    last_success_at      TEXT,
    next_read_at         TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recipes (
    portal_id         TEXT NOT NULL REFERENCES portals(id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    parent_version    INTEGER,
    body_format       TEXT NOT NULL,
    body              TEXT NOT NULL,                   /* JSON, format from Q1 */
    fingerprint       TEXT,
    status            TEXT NOT NULL CHECK (status IN ('candidate','active','retired','rejected')),
    created_by_run_id TEXT,
    created_at        TEXT NOT NULL,
    validated_at      TEXT,
    rationale         TEXT,
    PRIMARY KEY (portal_id, version)
);
CREATE INDEX IF NOT EXISTS recipes_fingerprint ON recipes(fingerprint, status);

CREATE TABLE IF NOT EXISTS runs (
    id             TEXT PRIMARY KEY,
    portal_id      TEXT NOT NULL REFERENCES portals(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('read','repair')),
    trigger        TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    result         TEXT CHECK (result IN ('ok','failed')),
    recipe_version INTEGER,
    state_before   TEXT NOT NULL,
    state_after    TEXT,
    reason_after   TEXT,
    stats          TEXT NOT NULL DEFAULT '{}',          /* RunStats JSON */
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL NOT NULL DEFAULT 0,
    model_calls         INTEGER NOT NULL DEFAULT 0,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS runs_portal ON runs(portal_id, started_at DESC);
/* At most one running read per portal: refresh returns its id. */
CREATE UNIQUE INDEX IF NOT EXISTS runs_one_active_read
    ON runs(portal_id) WHERE kind = 'read' AND finished_at IS NULL;

CREATE TABLE IF NOT EXISTS run_checks (
    run_id   TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    passed   INTEGER NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warn','fail','block')),
    observed TEXT,                                     /* JSON */
    expected TEXT,                                     /* JSON */
    message  TEXT NOT NULL,
    PRIMARY KEY (run_id, name)
);

CREATE TABLE IF NOT EXISTS agent_steps (
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('llm','tool','decision','note')),
    name        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    prompt_id   TEXT,
    args        TEXT,                                  /* JSON, truncated */
    result      TEXT,                                  /* truncated */
    duration_ms INTEGER,
    usage       TEXT,                                  /* TokenUsage JSON, llm steps only */
    error       TEXT,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id         TEXT PRIMARY KEY,
    portal_id  TEXT NOT NULL REFERENCES portals(id) ON DELETE CASCADE,
    run_id     TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    captured_at TEXT NOT NULL,
    body       TEXT NOT NULL                           /* PortalSnapshot JSON; bodies on disk */
);

CREATE TABLE IF NOT EXISTS tenders (
    portal_id           TEXT NOT NULL REFERENCES portals(id) ON DELETE CASCADE,
    tender_id           TEXT NOT NULL,                 /* portal's own id */
    url                 TEXT,
    title               TEXT,
    buyer_name          TEXT,
    publication_date    TEXT,                          /* YYYY-MM-DD */
    submission_deadline TEXT,                          /* with offset */
    reference_number    TEXT,
    description         TEXT,
    procedure_type      TEXT,
    contract_nature     TEXT,
    cpv_codes           TEXT NOT NULL DEFAULT '[]',     /* JSON list */
    place               TEXT,                          /* JSON object */
    withdrawn           INTEGER NOT NULL DEFAULT 0,
    listed              INTEGER NOT NULL DEFAULT 1,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    last_changed_at     TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    detail_fetched_at   TEXT,
    docs_status         TEXT NOT NULL DEFAULT 'pending',
    source_run_id       TEXT,
    source_urls         TEXT NOT NULL DEFAULT '[]',
    raw                 TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (portal_id, tender_id)
);
CREATE INDEX IF NOT EXISTS tenders_changed ON tenders(portal_id, last_changed_at);

CREATE TABLE IF NOT EXISTS files (
    file_id        TEXT PRIMARY KEY,                   /* first 16 hex of sha256 */
    sha256         TEXT,
    size_bytes     INTEGER,
    content_type   TEXT,
    storage_path   TEXT,
    source_url     TEXT NOT NULL,
    parent_file_id TEXT REFERENCES files(file_id),
    is_archive     INTEGER NOT NULL DEFAULT 0,
    skipped        TEXT,
    downloaded_at  TEXT
);

CREATE TABLE IF NOT EXISTS tender_files (
    portal_id TEXT NOT NULL,
    tender_id TEXT NOT NULL,
    file_id   TEXT NOT NULL REFERENCES files(file_id),
    file_name TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (portal_id, tender_id, file_id),
    FOREIGN KEY (portal_id, tender_id) REFERENCES tenders(portal_id, tender_id) ON DELETE CASCADE
);

/* Cost per portal for the README and the dashboard. */
CREATE VIEW IF NOT EXISTS portal_costs AS
SELECT portal_id,
       SUM(CASE WHEN kind = 'read'   THEN cost_usd ELSE 0 END) AS read_cost_usd,
       SUM(CASE WHEN kind = 'repair' THEN cost_usd ELSE 0 END) AS repair_cost_usd,
       SUM(input_tokens) AS input_tokens,
       SUM(output_tokens) AS output_tokens,
       SUM(model_calls) AS model_calls
FROM runs GROUP BY portal_id;
