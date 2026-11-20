# Q7. Schemas for every internal record

Owner: teammate who took Q5, Q7 and Q8 · Status: **open, no answer in the repo yet**

## Question

Draft the schemas for every internal record, so workstreams can build in parallel.

Records
- Recipe (depends on Q1).
- Portal: state, reason, software fingerprint, current recipe version.
- Run: kind, times, result, check results, tokens and cost, errors.
- Tender: the output contract, plus an internal content hash and where it came from.
- File.
- Agent step trace (what the dashboard shows as "what the system did").
- Portal snapshot handed to a repair: pages and network log.
- Validator check result.

Also check OCDS and eForms field definitions, so our tender record maps cleanly onto them.

Deliverable: Pydantic models with one-line field descriptions, and the SQLite tables they map to.

## Answer

None yet. When it is written, it follows the answer standard in [README.md](README.md).
