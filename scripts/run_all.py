"""Run every scenario x path x condition against the real Latent API. Idempotent: cached in runs/results.jsonl.

    python scripts/run_all.py            # all 24 scenarios
    python scripts/run_all.py --only 4   # first 4 (dev subset)

Conditions: stock = auto_instrument() + session(); stock_ctx = also runlatent.context(tool results);
adapter = latent_agents on the same trajectory. Model turns are scripted (agent/stub_server.py) so the real
openai / anthropic clients and the real SDK capture path are used with no LLM spend.
"""
import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import runlatent  # noqa: E402
import yaml  # noqa: E402

SENT = {}  # request_id -> the exact body auto_instrument posted (via the documented redact hook)


def _record(body):
    SENT[body.get("request_id")] = json.loads(json.dumps(body, default=str))
    return body


runlatent.auto_instrument(redact=_record, enforce=False)  # before clients are created, per the quickstart

from agent import run, stub_server  # noqa: E402
from agent.tools import call_tool  # noqa: E402
from latent_agents import FLAGGED, score_trajectory, to_steps  # noqa: E402

OUT = ROOT / "runs" / "results.jsonl"


def stock_run(scenario, path, base, session_id, ctx=None):
    """Run through the real client with auto-instrumentation; return (steps, per-turn stock result)."""
    client = run.make_client(path, base)
    with runlatent.session(session_id):
        if ctx is not None:
            with runlatent.context(ctx):
                msgs, ids = run.run(scenario, path, client)
        else:
            msgs, ids = run.run(scenario, path, client)
        results = {}
        for turn, rid in enumerate(ids):
            body = SENT.get(rid)
            if body is None:  # tool-only turn: auto_instrument counts it skipped_tool_only, never posts it
                results[turn] = {"scored": False, "label": "not scored", "sent": None}
                continue
            # Pair with the capture by provider response id: adopts its read, nothing is posted twice.
            r = runlatent.check(None, body["output"], messages=body["messages"], request_id=rid)
            has_source = bool(body.get("context")) or any(
                m["role"] in ("tool",) or (m["role"] == "user" and m["content"].lstrip().startswith("{"))
                for m in body["messages"])
            results[turn] = {"scored": r.scored, "status": r.status, "risk": r.risk, "verdict": r.verdict,
                             "flagged": r.verdict in FLAGGED, "no_source": not has_source,
                             "label": f"{r.risk:.2f}" if r.risk is not None else r.verdict,
                             "sent": {"messages": body["messages"], "context": body.get("context"),
                                      "answer": body["output"]}}
    return msgs, ids, results


def run_one(sc, path, base):
    """One scenario on one path, all three conditions. Returns the cached record."""
    tool_results = [call_tool(t["call"]["name"], t["call"]["args"]) for t in sc["turns"] if "call" in t]
    key = f"{sc['id']}-{path}"
    msgs, ids, stock = stock_run(sc, path, base, f"{key}-stock")
    _, _, ctx = stock_run(sc, path, base, f"{key}-stock_ctx", ctx="\n".join(tool_results))
    t0 = time.perf_counter()
    steps = score_trajectory(to_steps(msgs, path), session_id=f"{key}-adapter")
    adapter_ms = (time.perf_counter() - t0) * 1000
    bad_turn = next(i for i, t in enumerate(sc["turns"]) if t.get("bad")) if sc["type"] != "clean" else None
    for s in steps:
        if s["turn"] is not None:
            s["stock"], s["stock_ctx"] = stock[s["turn"]], ctx[s["turn"]]
        s["bad"] = s["turn"] is not None and s["turn"] == bad_turn
    return {"scenario": sc["id"], "type": sc["type"], "path": path, "user": sc["user"],
            "response_ids": ids, "steps": steps, "adapter_ms": round(adapter_ms)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None)
    a = ap.parse_args()
    scenarios = yaml.safe_load((ROOT / "scenarios.yaml").read_text())[: a.only]
    done = {(r["scenario"], r["path"]) for r in map(json.loads, OUT.open())} if OUT.exists() else set()
    base = stub_server.start()
    with OUT.open("a") as f:
        for sc in scenarios:
            for path in run.PATHS:
                if (sc["id"], path) in done:
                    continue
                rec = run_one(sc, path, base)
                f.write(json.dumps(rec) + "\n")
                f.flush()
                flags = "".join("x" if s.get("adapter", {}).get("flagged") else "." for s in rec["steps"])
                print(f"{sc['id'] + '-' + path:40s} {flags}")
                if any(r.get("status") == 429 for s in rec["steps"] for r in (s.get("adapter") or {}, s.get("stock") or {})):
                    sys.exit("429 limit_reached from Latent: stopping (spec section 8)")
    runlatent.flush()
    s = runlatent.stats()
    print("stats:", {k: s.get(k) for k in ("captured", "posted", "failed", "dropped", "skipped_tool_only",
                                             "check_adopted", "check_scored")})
    (ROOT / "runs" / "stats.json").write_text(json.dumps(s, indent=1, default=str))


if __name__ == "__main__":
    main()
