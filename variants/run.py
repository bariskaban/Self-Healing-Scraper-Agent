"""Run the learner on the made-up portals of `variants/portals.py` and score what its recipe reads.

    OPENAI_API_KEY=... python -m variants.run [name ...] [--out results.json]

A person runs this, on the development key (CLAUDE.md: live model calls only when a person asks).
The portals answer inside this process: no request reaches any portal. For each one the learner
runs once; its recipe is then run over every page of the portal (no model) and compared with the
truth, field by field.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.parse import urljoin

import httpx

from app.agent.learn import learn
from app.agent.repair import repair
from app.agent.runner import OpenAIModel, Runner, StepLog
from app.agent.settings import AgentSettings
from app.checks import Answer
from app.config import ModelSettings, api_key
from app.fetch.interface import Fetched
from app.checks.result import Cause, failed
from app.models import Portal, TenderRecord, url_key
from app.recipe.run import CachedPage, dry_run
from app.recipe.schema import AuthoredRecipe, RecipeBody
from variants.portals import VARIANTS, Variant

FIELDS = ("url", "title", "buyer_name", "publication_date", "submission_deadline", "reference_number", "cpv_codes",
          "procedure_type", "contract_nature")


class VariantFetch:
    """The `fetch` of the network layer on a variant, redirects walked as the real one walks them."""

    def __init__(self, variant: Variant) -> None:
        self.variant = variant

    def fetch(self, portal_id, url, *, method="GET", params=None, data=None, json=None, headers=None,
              page_load=True) -> Fetched:
        asked = address = str(httpx.URL(url, params=params)) if params else url
        hops: list[str] = []
        for _ in range(5):
            status, head, body = self.variant.respond(method, address, data)
            if status not in (301, 302, 303, 307, 308) or "Location" not in head:
                break
            hops.append(address)
            address, method = urljoin(address, head["Location"]), "GET"
        return Fetched(url=asked, final_url=address, status=status, headers=httpx.Headers(head), body=body,
                       answer=Answer(status=status, page_load=page_load), redirects=tuple(hops))


def read_all(recipe, variant: Variant, timezone: str | None, limit: int = 400):
    """The recipe run over the whole portal: pages it asks for are fetched until it asks for no more."""
    fetch, pages = VariantFetch(variant), {}
    while True:
        read = dry_run(recipe, list(pages.values()), url=variant.base_url, timezone=timezone)
        missing = [m[4:] for m in read.missing_pages if m.startswith("GET ") and m[4:] not in pages]
        if not missing or len(pages) >= limit:
            return read
        for address in missing:
            got = fetch.fetch("bench", address)
            pages[address] = CachedPage(url=address, body=got.body, status=got.status or 0,
                                        content_type=got.headers.get("content-type"), final_url=got.final_url)


def score(read, variant: Variant) -> dict:
    truth = {t["id"]: t for t in variant.truth()}
    got = {record.tender_id: record for record in read.records}
    matched = [i for i in truth if i in got]
    out = {"truth": len(truth), "read": len(got), "matched": len(matched), "problems": read.problems[:3], "fields": {}}
    for name in FIELDS:
        wrong = missing = 0
        for i in matched:
            value = getattr(got[i], name)
            if value is None or value == []:
                missing += 1
            elif value != truth[i][name]:
                wrong += 1
        out["fields"][name] = {"right": len(matched) - wrong - missing, "wrong": wrong, "missing": missing}
    out["documents_right"] = sum(1 for i in matched if len(read.documents.get(i, [])) == truth[i]["documents"])
    return out


def run_one(name: str, runner: Runner, settings: AgentSettings, models: ModelSettings) -> dict:
    variant = VARIANTS[name]()
    portal = Portal(id=name, url=variant.base_url, url_key=url_key(variant.base_url))
    steps = StepLog(f"bench-{name}-{int(time.time())}")
    began = time.time()
    result = learn(portal, fetch=VariantFetch(variant), runner=runner, steps=steps, models=models, settings=settings)
    usage = result.usage
    out = {"variant": name, "what": variant.what, "expect": variant.expect, "learned": result.recipe is not None,
           "seconds": round(time.time() - began), "model_calls": result.model_calls, "requests": result.requests,
           "input_tokens": usage.input_tokens, "cached_share": round(usage.cached_input_tokens / usage.input_tokens, 2)
           if usage.input_tokens else None, "output_tokens": usage.output_tokens, "cost_usd": round(usage.cost_usd, 3),
           "reason": result.reason, "refused_proposals": sum(1 for s in steps.steps if s.name in ("propose_recipe", "replace_node")
                                                             and "not accepted" in s.summary),
           "steps": [f"{s.kind.value} {s.name}: {s.summary}" for s in steps.steps if s.kind.value != "llm"]}
    if result.recipe is not None:
        out["recipe"] = result.recipe.model_dump(mode="json")
        out["timezone"] = result.timezone
        out["score"] = score(read_all(result.recipe, variant, result.timezone), variant)
    return out


def repair_one(learned: dict, runner: Runner, settings: AgentSettings, models: ModelSettings,
               face: str = "changed") -> dict:
    """The portal after its redesign or its move (or both), the recipe learned before it, and one repair."""
    name = learned["variant"]
    variant = VARIANTS[name]()
    variant.changed, variant.moved = face in ("changed", "both"), face in ("moved", "both")
    old = AuthoredRecipe.model_validate(learned["recipe"])
    zone = learned.get("timezone")
    before = score(read_all(old, variant, zone), variant)
    portal = Portal(id=name, url=variant.base_url, url_key=url_key(variant.base_url), timezone=zone)
    known = [TenderRecord(portal_id=name, tender_id=t["id"], url=t["url"], title=t["title"], buyer_name=t["buyer_name"],
                          publication_date=t["publication_date"], submission_deadline=t["submission_deadline"],
                          reference_number=t["reference_number"]) for t in variant.truth()]
    rows = [failed("bench", "list_outcome", "The tender list did not arrive: no row was found, and the portal does "
                   "not say the list is empty. A second look found the same.", cause=Cause.breakage)]
    steps = StepLog(f"bench-repair-{name}-{int(time.time())}")
    began = time.time()
    result = repair(portal, RecipeBody.from_authored(old), rows, fetch=VariantFetch(variant), known=known,
                    runner=runner, steps=steps, models=models, settings=settings)
    usage = result.usage
    out = {"variant": name, "what": f"repair, face {face}", "expect": "serve", "learned": result.recipe is not None,
           "seconds": round(time.time() - began), "model_calls": result.model_calls, "requests": result.requests,
           "input_tokens": usage.input_tokens, "cached_share": round(usage.cached_input_tokens / usage.input_tokens, 2)
           if usage.input_tokens else None, "output_tokens": usage.output_tokens, "cost_usd": round(usage.cost_usd, 3),
           "reason": result.reason, "old_recipe_matched_after_change": before["matched"],
           "steps": [f"{s.kind.value} {s.name}: {s.summary}" for s in steps.steps if s.kind.value != "llm"]}
    if result.recipe is not None:
        out["recipe"] = result.recipe.model_dump(mode="json")
        out["nodes_changed"] = [n.id for n in result.recipe.nodes
                                if n not in old.nodes]
        out["score"] = score(read_all(result.recipe, variant, result.timezone or zone), variant)
    return out


def line(out: dict) -> str:
    head = (f"{out['variant']:<13} learned={str(out['learned']):<5} calls={out['model_calls']:<3} "
            f"${out['cost_usd']:<6} cached={out['cached_share']} {out['seconds']}s")
    if "score" not in out:
        return f"{head} | expected {out['expect']} | {out['reason'][:140]}"
    s = out["score"]
    bad = {name: f"{f['wrong']}w/{f['missing']}m" for name, f in s["fields"].items() if f["wrong"] or f["missing"]}
    return (f"{head} | tenders {s['matched']}/{s['truth']} (read {s['read']}) docs {s['documents_right']}/{s['matched']}"
            f" | not right: {bad or 'nothing'}" + (f" | problems {s['problems']}" if s["problems"] else ""))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the learner on the made-up portals and score it.")
    parser.add_argument("names", nargs="*", help=f"which portals (default: all of {', '.join(VARIANTS)})")
    parser.add_argument("--out", help="write every result, with recipe and steps, to this JSON file")
    parser.add_argument("--repair-from", help="a results file of an earlier run: each recipe in it is repaired "
                                              "on its portal after the redesign, instead of learning")
    parser.add_argument("--face", choices=("changed", "moved", "both"), default="changed",
                        help="with --repair-from: a redesign (hooks renamed), a move (every address but the "
                             "domain changed), or both")
    args = parser.parse_args(argv)
    key = api_key()
    if key is None:
        sys.exit("OPENAI_API_KEY is not set: this script makes live model calls on the development key.")
    settings, models = AgentSettings.from_env(), ModelSettings.from_env()
    runner = Runner(OpenAIModel(key, settings), settings)
    results = []
    todo: list = args.names or list(VARIANTS)
    if args.repair_from:
        with open(args.repair_from, encoding="utf-8") as handle:
            todo = [r for r in json.load(handle) if r.get("recipe") and (not args.names or r["variant"] in args.names)]
    for name in todo:
        results.append(repair_one(name, runner, settings, models, args.face) if args.repair_from
                       else run_one(name, runner, settings, models))
        print(line(results[-1]), flush=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(results, handle, indent=1, default=str)
    print(f"total ${sum(r['cost_usd'] for r in results):.2f} for {len(results)} portal(s)")


if __name__ == "__main__":
    main()
