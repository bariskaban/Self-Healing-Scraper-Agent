"""The learner and the repairer on the real test portals of `bench/portals.toml`, and on altered clones of them.

    FETCH_MODE=live OPENAI_API_KEY=... python -m variants.real [portal-id ...] --out results.json

READ THIS FIRST. This script sends requests to live portals. CLAUDE.md forbids that for agent
sessions, tests and scripts; Goktug lifted the rule for the benchmark run of 20/21 Nov 2026, on
the condition that nobody else was reading these portals then. Do not run it without a person
saying so. It refuses to start unless FETCH_MODE=live is set by hand, reads one portal per
process at the network layer's pace (1 request a second, robots.txt obeyed), and leaves out the
portals marked `unseen` and those whose robots.txt forbids everything.

What one portal's run does:
  1. learn, live. Every page fetched is kept in a clone on disk (`--clones`, default recordings/clones,
     which git ignores), so the same page is never asked for twice.
  2. baseline: the learned recipe read over two list pages and five tenders (no model).
  3. for each scenario, the clone is served with one node's pages altered (classes, ids and
     data-* hooks renamed; JSON keys renamed), as `variants/portals.py` alters its own:
       list     only the list pages change
       detail   only the tenders' own pages change
     The old recipe is run on it. If it still reads the baseline, the portal's recipe does not
     depend on what changed, and that is the result. If not, one repair runs, and its recipe
     must give the baseline records again; the nodes it changed are compared with the node broken.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

from app.agent.learn import learn
from app.agent.repair import repair
from app.agent.runner import OpenAIModel, Runner, StepLog
from app.agent.settings import AgentSettings
from app.checks import Answer
from app.checks.result import Cause, failed
from app.config import ModelSettings, api_key
from app.fetch import Fetcher, FetchMode, FetchSettings
from app.fetch.interface import Fetched
from app.models import Portal, TenderRecord, url_key
from app.recipe.locate import find_items, parse_page
from app.recipe.run import CachedPage, _address_key, dry_run
from app.recipe.schema import AuthoredRecipe, NodeRole, RecipeBody
from bench.portals import load_portals
from variants.portals import _redesigned

import httpx

COMPARED = ("url", "title", "buyer_name", "publication_date", "submission_deadline", "reference_number")
LIST_PAGES, TENDERS = 2, 5


class Clone:
    """The pages of one portal as they were fetched, kept on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.pages: dict[tuple[str, str], CachedPage] = {}
        if path.is_file():
            for row in json.loads(path.read_text(encoding="utf-8")):
                page = CachedPage(url=row["url"], body=base64.b64decode(row["body"]), status=row["status"],
                                  content_type=row["content_type"], method=row["method"], final_url=row["final_url"])
                self.pages[_address_key(page.method, page.url)] = page

    def add(self, page: CachedPage) -> None:
        self.pages[_address_key(page.method, page.url)] = page
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"url": p.url, "method": p.method, "status": p.status, "content_type": p.content_type,
                 "final_url": p.final_url, "body": base64.b64encode(p.body if isinstance(p.body, bytes)
                                                                   else p.body.encode()).decode()}
                for p in self.pages.values()]
        self.path.write_text(json.dumps(rows), encoding="utf-8")


class CloneFetch:
    """`fetch` on a clone: a cloned page is served from disk, any other is fetched live once and kept.

    `altered` says which pages are served changed (a function of the page), for the scenarios.
    """

    def __init__(self, clone: Clone, live: Fetcher | None, altered=lambda page: False) -> None:
        self.clone, self.live, self.altered = clone, live, altered
        self.live_requests = 0

    def fetch(self, portal_id, url, *, method="GET", params=None, data=None, json=None, headers=None,
              page_load=True) -> Fetched:
        address = str(httpx.URL(url, params=params)) if params else url
        page = self.clone.pages.get(_address_key(method, address))
        if page is None:
            if self.live is None:
                raise LookupError(f"{method} {address} is not in the clone")
            self.live_requests += 1
            got = self.live.fetch(portal_id, address, method=method, data=data, json=json, headers=headers,
                                  page_load=page_load)
            if got.status is None:
                return got
            page = CachedPage(url=address, body=got.body, status=got.status,
                              content_type=got.headers.get("content-type"), method=method, final_url=got.final_url)
            self.clone.add(page)
        body = page.body if isinstance(page.body, bytes) else page.body.encode()
        if self.altered(page):
            try:
                body = _redesigned(body, page.content_type or "")
            except (UnicodeDecodeError, ValueError):  # a page that is not UTF-8, or not the JSON it says: left as it is
                pass
        head = httpx.Headers({"content-type": page.content_type} if page.content_type else {})
        return Fetched(url=address, final_url=page.final_url or address, status=page.status, headers=head, body=body,
                       answer=Answer(status=page.status, page_load=page_load))


def live_fetcher() -> Fetcher:
    """The network layer, live. Behind an HTTPS proxy (HTTPS_PROXY, as in a cloud session) its own
    transport would connect directly and fail to resolve hosts, so it is handed one that uses the proxy."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return Fetcher.from_env()
    import ssl

    from app.checks import CheckSettings

    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    return Fetcher(FetchSettings.from_env(), CheckSettings.from_env(),
                   transport=httpx.HTTPTransport(proxy=proxy, verify=context))


def capped(recipe: AuthoredRecipe) -> AuthoredRecipe:
    nodes = [node.model_copy(update={"paging": node.paging.model_copy(update={"max_pages": LIST_PAGES})})
             if node.role is NodeRole.list and node.paging is not None else node for node in recipe.nodes]
    return recipe.model_copy(update={"nodes": nodes})


def sample(recipe: AuthoredRecipe, portal: Portal, fetch: CloneFetch, limit: int = 40):
    """The recipe read over two list pages and five tenders, through `fetch`. No model."""
    seen: dict[str, CachedPage] = {}
    asked: set[str] = set()
    while True:
        read = dry_run(capped(recipe), list(seen.values()), url=portal.url, timezone=portal.timezone,
                       max_details=TENDERS)
        missing = [m[4:] for m in read.missing_pages if m.startswith("GET ") and m[4:] not in asked]
        if not missing or len(asked) >= limit:
            return read
        for address in missing:
            asked.add(address)
            try:
                got = fetch.fetch(portal.id, address)
            except Exception:  # robots, no answer: the read says so itself on the next round
                continue
            if got.status is not None:
                seen[address] = CachedPage(url=address, body=got.body, status=got.status,
                                           content_type=got.headers.get("content-type"), final_url=got.final_url)


def values(read) -> dict[str, dict]:
    """The first tenders of a read, the ones whose own page was read, as plain values to compare."""
    out = {}
    for record in read.records[:TENDERS]:
        out[record.tender_id] = {name: (str(v) if (v := getattr(record, name)) is not None else None)
                                 for name in COMPARED}
        out[record.tender_id]["documents"] = len(read.documents.get(record.tender_id, []))
    return out


def is_list_page(recipe: AuthoredRecipe, page: CachedPage) -> bool:
    node = next(n for n in recipe.nodes if n.role is NodeRole.list)
    try:
        doc = parse_page(page.body, node.kind, page.final_url or page.url, page.content_type)
        return bool(node.items is not None and find_items(node.items, doc))
    except Exception:
        return False


def usage_of(result) -> dict:
    u = result.usage
    return {"model_calls": result.model_calls, "cost_usd": round(u.cost_usd, 3), "input_tokens": u.input_tokens,
            "cached_share": round(u.cached_input_tokens / u.input_tokens, 2) if u.input_tokens else None,
            "output_tokens": u.output_tokens}


def run_portal(spec, runner: Runner, settings: AgentSettings, models: ModelSettings, clones: Path,
               scenarios: list[str], earlier: dict | None = None) -> dict:
    portal = Portal(id=spec.id, url=spec.url, url_key=url_key(spec.url))
    clone = Clone(clones / f"{spec.id}.json")
    live = live_fetcher()
    out: dict = {"portal": spec.id, "url": spec.url, "kind": str(getattr(spec.kind, "value", spec.kind)),
                 "expect": str(getattr(spec.expect, "value", spec.expect))}
    try:
        fetch = CloneFetch(clone, live)
        steps = StepLog(f"real-{spec.id}-{int(time.time())}")
        began = time.time()
        if earlier and earlier.get("recipe"):  # learned in an earlier run: only the scenarios run again
            from app.agent.learn import AgentResult
            learned = AgentResult(recipe=AuthoredRecipe.model_validate(earlier["recipe"]),
                                  timezone=earlier.get("timezone"))
            out["learn"] = earlier["learn"]
        else:
            learned = learn(portal, fetch=fetch, runner=runner, steps=steps, models=models, settings=settings)
        if "learn" not in out:
            out["learn"] = {"learned": learned.recipe is not None, "seconds": round(time.time() - began),
                        "requests": learned.requests, "live_requests": fetch.live_requests, "reason": learned.reason,
                        **usage_of(learned),
                        "refused": sum(1 for s in steps.steps if "not accepted" in s.summary),
                            "steps": [f"{s.kind.value} {s.name}: {s.summary}" for s in steps.steps
                                      if s.kind.value != "llm"]}
        if learned.recipe is None:
            return out
        recipe = learned.recipe
        portal = portal.model_copy(update={"timezone": learned.timezone})
        out["recipe"], out["timezone"] = recipe.model_dump(mode="json"), learned.timezone
        base_read = sample(recipe, portal, fetch)
        baseline = values(base_read)
        total = len(base_read.records)
        out["baseline"] = {"records_on_two_pages": total, "printed_total": base_read.printed_total,
                           "problems": base_read.problems[:3], "tenders": baseline,
                           "filled": {k: f"{v} of {total}" for k, v in sorted(base_read.filled.items())}}
        if not baseline:
            return out
        list_urls = {key for key, page in clone.pages.items() if is_list_page(recipe, page)}
        known = [TenderRecord(portal_id=portal.id, tender_id=r.tender_id, url=r.url, title=r.title,
                              buyer_name=r.buyer_name, publication_date=r.publication_date,
                              submission_deadline=r.submission_deadline, reference_number=r.reference_number)
                 for r in base_read.records[:TENDERS]]
        out["scenarios"] = {}
        for scenario in scenarios:
            def altered(page: CachedPage, scenario=scenario) -> bool:
                listed = _address_key(page.method, page.url) in list_urls or is_list_page(recipe, page)
                return listed if scenario == "list" else not listed
            changed = CloneFetch(clone, live, altered)
            after = sample(recipe, portal, changed)
            still = values(after)
            lost = sorted({name for tid, want in baseline.items() for name, value in want.items()
                           if still.get(tid, {}).get(name) != value})
            result: dict = {"old_recipe_still_reads": still == baseline, "fields_lost": lost,
                            "old_recipe_records": len(after.records)}
            out["scenarios"][scenario] = result
            if still == baseline:
                continue
            message = ("The tender list did not arrive: no row was found, and the portal does not say the list is "
                       "empty. A second look found the same." if not after.records else
                       f"Known tenders no longer give the values of the last good read: {', '.join(lost)}.")
            rows = [failed("real", "list_outcome" if not after.records else "known_tenders_reproduce", message,
                           cause=Cause.breakage)]
            steps = StepLog(f"real-{spec.id}-{scenario}-{int(time.time())}")
            began = time.time()
            fixed = repair(portal, RecipeBody.from_authored(recipe), rows, fetch=changed, known=known, runner=runner,
                           steps=steps, models=models, settings=settings)
            result.update({"repaired": fixed.recipe is not None, "seconds": round(time.time() - began),
                           "reason": fixed.reason, **usage_of(fixed),
                           "steps": [f"{s.kind.value} {s.name}: {s.summary}" for s in steps.steps
                                     if s.kind.value != "llm"]})
            if fixed.recipe is not None:
                again = values(sample(fixed.recipe, portal, changed))
                result["reads_baseline_again"] = again == baseline
                result["still_wrong"] = sorted({f"{tid}.{name}" for tid, want in baseline.items()
                                                for name, value in want.items()
                                                if again.get(tid, {}).get(name) != value})[:8]
                old_nodes = {node.id: node for node in recipe.nodes}
                result["nodes_changed"] = [f"{node.id} ({node.role.value})" for node in fixed.recipe.nodes
                                           if old_nodes.get(node.id) != node]
                result["recipe"] = fixed.recipe.model_dump(mode="json")
        return out
    except Exception as error:  # one portal's fault must not end the others' runs
        out["error"] = f"{type(error).__name__}: {error}"
        return out
    finally:
        out["pages_cloned"] = len(clone.pages)
        live.close()


def line(out: dict) -> str:
    if "error" in out:
        return f"{out['portal']:<22} ERROR {out['error'][:200]}"
    learn_ = out.get("learn", {})
    head = (f"{out['portal']:<22} learned={str(learn_.get('learned')):<5} calls={learn_.get('model_calls')} "
            f"${learn_.get('cost_usd')} cached={learn_.get('cached_share')} {learn_.get('seconds')}s "
            f"req={learn_.get('live_requests')}")
    if "baseline" not in out:
        return f"{head} | {str(learn_.get('reason'))[:160]}"
    base = out["baseline"]
    text = f"{head} | 2 pages: {base['records_on_two_pages']} tenders (portal says {base['printed_total']})"
    for name, s in out.get("scenarios", {}).items():
        if s["old_recipe_still_reads"]:
            text += f" | {name}: old recipe unaffected"
        else:
            text += (f" | {name}: repaired={s.get('repaired')} same_values={s.get('reads_baseline_again')} "
                     f"changed={s.get('nodes_changed')} ${s.get('cost_usd')}")
    return text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Learn real test portals live, clone them, break a node, repair.")
    parser.add_argument("ids", nargs="*", help="portal ids from bench/portals.toml (default: every one not held back)")
    parser.add_argument("--out", required=True, help="JSON file for the results (recipes and steps included)")
    parser.add_argument("--clones", default="recordings/clones", help="where the fetched pages are kept")
    parser.add_argument("--scenarios", default="list,detail")
    parser.add_argument("--resume", action="append", default=[],
                        help="a results file of an earlier run: a portal learned there is not learned again")
    args = parser.parse_args(argv)
    if os.environ.get("FETCH_MODE", "").strip().lower() != "live":
        sys.exit("This script reads live portals. Set FETCH_MODE=live by hand, and only when a person said so "
                 "(CLAUDE.md, 'Network: no live portals').")
    key = api_key()
    if key is None:
        sys.exit("OPENAI_API_KEY is not set.")
    assert FetchSettings.from_env().mode is FetchMode.live
    specs = {p.id: p for p in load_portals() if p.url and not p.unseen}
    unknown = [i for i in args.ids if i not in specs]
    if unknown:
        sys.exit(f"Not in bench/portals.toml, held back, or forbidden by robots.txt: {', '.join(unknown)}")
    settings, models = AgentSettings.from_env(), ModelSettings.from_env()
    runner = Runner(OpenAIModel(key, settings), settings)
    earlier = {r["portal"]: r for path in args.resume for r in json.loads(Path(path).read_text(encoding="utf-8"))}
    results = []
    for portal_id in args.ids or list(specs):
        results.append(run_portal(specs[portal_id], runner, settings, models, Path(args.clones),
                                  [s for s in args.scenarios.split(",") if s], earlier.get(portal_id)))
        print(line(results[-1]), flush=True)
        Path(args.out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
