"""Reproduce every number from runs/results.jsonl with no API calls.
Writes results/metrics.json and web/demo_data/demo.json (findings.md is hand-written from metrics.json)."""
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS_FILE = ROOT / "runs" / "results.jsonl"
RUNS = [json.loads(l) for l in RUNS_FILE.open()] if RUNS_FILE.exists() else []
CONDS = ("stock", "stock_ctx", "adapter")
PATHS = ("anthropic", "chat", "responses")
TYPES = ("A", "B", "C")


def flagged(step, cond):
    return bool((step.get(cond) or {}).get("flagged"))


def first_flag(run, cond):
    return next((i for i, s in enumerate(run["steps"]) if flagged(s, cond)), None)


def bad_index(run):
    return next((i for i, s in enumerate(run["steps"]) if s["bad"]), None)


def frac(hits, n):
    return {"hits": hits, "n": n, "pct": round(100 * hits / n) if n else None}


def metrics():
    m = {"recall": {}, "false_flag": {}, "not_scored": {}, "no_source": {}, "first_bad_step": {}}
    for cond in CONDS:
        for path in PATHS:
            rs = [r for r in RUNS if r["path"] == path]
            for t in TYPES:
                bad = [r for r in rs if r["type"] == t]
                m["recall"][f"{t}|{path}|{cond}"] = frac(sum(flagged(r["steps"][bad_index(r)], cond) for r in bad), len(bad))
            clean = [r for r in rs if r["type"] == "clean"]
            m["false_flag"][f"{path}|{cond}"] = frac(sum(first_flag(r, cond) is not None for r in clean), len(clean))
            agent = [s for r in rs for s in r["steps"] if s["kind"] in ("tool_call", "assistant_text")]
            m["not_scored"][f"{path}|{cond}"] = frac(sum(not (s.get(cond) or {}).get("verdict") or
                                                         (s.get(cond) or {}).get("verdict") == "unscored"
                                                         for s in agent), len(agent))
            finals = [r["steps"][-1] for r in rs]
            if cond != "adapter":
                m["no_source"][f"{path}|{cond}"] = frac(sum(bool(s[cond].get("no_source")) for s in finals), len(finals))
            badr = [r for r in rs if r["type"] != "clean"]
            m["first_bad_step"][f"{path}|{cond}"] = frac(sum(first_flag(r, cond) == bad_index(r) for r in badr), len(badr))
    badr = [r for r in RUNS if r["type"] != "clean"]
    b = [r for r in RUNS if r["type"] == "B"]
    clean = [r for r in RUNS if r["type"] == "clean"]
    caught = lambda rs, c: sum(flagged(r["steps"][bad_index(r)], c) for r in rs)
    steps_scored = sum(1 for r in RUNS for s in r["steps"] if s.get("adapter"))
    m["headline"] = {
        "caught": {c: frac(caught(badr, c), len(badr)) for c in CONDS},
        "tool_caught": {c: frac(caught(b, c), len(b)) for c in CONDS},
        "first_bad_step": {c: frac(sum(first_flag(r, c) == bad_index(r) for r in badr), len(badr)) for c in CONDS},
        "clean_false_alarm": {c: frac(sum(first_flag(r, c) is not None for r in clean), len(clean)) for c in CONDS},
    }
    m["adapter_ms_per_step_p50"] = round(statistics.median(r["adapter_ms"] / max(1, sum(1 for s in r["steps"] if s.get("adapter"))) for r in RUNS))
    m["adapter_scores_used"] = steps_scored
    stats = ROOT / "runs" / "stats.json"
    if stats.exists():
        s = json.loads(stats.read_text())
        m["sdk_stats"] = {k: s.get(k) for k in ("captured", "posted", "failed", "dropped", "skipped_tool_only",
                                               "check_adopted", "check_scored")}
    return m


def render_sent(sent):
    """The exact text Latent saw for a call, for the step drawer."""
    if not sent:
        return None
    if "messages" in sent:
        lines = [f"{m['role']}: {m['content']}" for m in sent["messages"]]
        if sent.get("context"):
            lines.append(f"context: {sent['context']}")
        return "\n".join(lines + [f"answer: {sent['answer']}"])
    return f"prompt: {sent['prompt']}\ncontext:\n{sent['context']}\nanswer: {sent['answer']}"


def badge(step, cond):
    r = step.get(cond)
    if r is None:
        return None
    if cond != "adapter" and not r.get("verdict"):
        return {"state": "none", "label": "not scored", "sent": None}
    state = "flag" if r["flagged"] else "ok"
    label = "arg not grounded" if r.get("signal") == "provenance" else (f"{r['risk']:.2f}" if r.get("risk") is not None else r["verdict"])
    if cond != "adapter" and r.get("no_source") and state == "flag":
        label += " · no source"
    out = {"state": state, "label": label, "sent": render_sent(r.get("sent"))}
    if cond == "adapter" and r.get("latent"):
        out["latent_read"] = round(r["latent"]["risk"], 2) if r["latent"].get("risk") is not None else None
    return out


def summary(run, cond, name):
    f, b = first_flag(run, cond), bad_index(run)
    if b is None:
        return f"{name}: clean." if f is None else f"{name}: false alarm at step {f + 1}."
    if f is None:
        return f"{name}: missed."
    return f"{name}: caught at step {f + 1}." if f == b else f"{name}: flagged step {f + 1} (bad step is {b + 1})."


def demo_run(r):
    steps = [{"kind": s["kind"], "text": s.get("text"), "name": s.get("name"), "args": s.get("args"),
              "bad": s["bad"], "stock": badge(s, "stock"), "adapter": badge(s, "adapter"),
              "reason": (s.get("adapter") or {}).get("reason")} for s in r["steps"]]
    return {"scenario": r["scenario"], "type": r["type"], "path": r["path"], "steps": steps,
            "first_bad": first_flag(r, "adapter"), "bad": bad_index(r),
            "summary": summary(r, "stock", "Stock Latent") + " " + summary(r, "adapter", "With adapter")}


def demo_data(m):
    return {"headline": m["headline"], "runs": {f"{r['scenario']}|{r['path']}": demo_run(r) for r in RUNS}}


if __name__ == "__main__":
    m = metrics()
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "metrics.json").write_text(json.dumps(m, indent=1))
    (ROOT / "web" / "demo_data").mkdir(parents=True, exist_ok=True)
    (ROOT / "web" / "demo_data" / "demo.json").write_text(json.dumps(demo_data(m)))
    h = m["headline"]
    for k in h:
        print(k, {c: f"{v['hits']}/{v['n']}" for c, v in h[k].items()})
    for t in TYPES:
        print(t, {f"{p}": " ".join(f"{m['recall'][f'{t}|{p}|{c}']['hits']}/{m['recall'][f'{t}|{p}|{c}']['n']}" for c in CONDS) for p in PATHS})
    print("false_flag", {k: f"{v['hits']}/{v['n']}" for k, v in m["false_flag"].items()})
    print("no_source", {k: f"{v['hits']}/{v['n']}" for k, v in m["no_source"].items()})
    print("ms/step", m["adapter_ms_per_step_p50"], "scores", m["adapter_scores_used"], m.get("sdk_stats"))
