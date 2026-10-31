"""latent_agents: step-level scoring for tool-using agents, on top of the public runlatent SDK.

    steps = to_steps(messages, "responses")
    scored = score_trajectory(steps, session_id="refund-42")
    print(rollup(scored)["reason"])
"""
import json
import re
import uuid

import runlatent

FLAGGED = ("escalate", "ood")


# ---------- 1. normalise three wire formats into canonical steps ----------

def to_steps(messages, provider):
    """-> [{kind: user|assistant_text|tool_call|tool_result, text?, name?, args?, turn}]
    `turn` is the index of the model response that produced an assistant step (None for others)."""
    steps, names, turn, prev_assistant = [], {}, -1, False

    def add(kind, assistant=False, **kw):
        nonlocal turn, prev_assistant
        if assistant and not prev_assistant:
            turn += 1
        prev_assistant = assistant
        steps.append({"kind": kind, "turn": turn if assistant else None, **kw})

    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            continue
        if provider == "chat":
            if role == "user":
                add("user", text=content)
            elif role == "assistant":
                for tc in m.get("tool_calls") or []:
                    names[tc["id"]] = tc["function"]["name"]
                    add("tool_call", True, name=tc["function"]["name"], args=json.loads(tc["function"]["arguments"]))
                if content:
                    add("assistant_text", True, text=content)
            elif role == "tool":
                add("tool_result", name=names.get(m["tool_call_id"]), text=content)
        elif provider == "responses":
            t = m.get("type")
            if t == "function_call":
                names[m["call_id"]] = m["name"]
                add("tool_call", True, name=m["name"], args=json.loads(m["arguments"]))
            elif t == "function_call_output":
                add("tool_result", name=names.get(m["call_id"]), text=m["output"])
            elif role == "user":
                add("user", text=content)
            elif role == "assistant":
                add("assistant_text", True, text=content)
        elif provider == "anthropic":
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
            for b in blocks:
                if b["type"] == "text" and role == "user":
                    add("user", text=b["text"])
                elif b["type"] == "text":
                    add("assistant_text", True, text=b["text"])
                elif b["type"] == "tool_use":
                    names[b["id"]] = b["name"]
                    add("tool_call", True, name=b["name"], args=b["input"])
                elif b["type"] == "tool_result":
                    c = b["content"]
                    add("tool_result", name=names.get(b["tool_use_id"]),
                        text=c if isinstance(c, str) else " ".join(x.get("text", "") for x in c))
        else:
            raise ValueError(f"unknown provider {provider}")
    return steps


# ---------- 2. render history readably (instead of "[tool_calls omitted]") ----------

def render_call(step):
    return f'→ called {step["name"]}(' + ", ".join(f"{k}={json.dumps(v)}" for k, v in step["args"].items()) + ")"


def render_history(steps):
    out = []
    for s in steps:
        if s["kind"] == "user":
            out.append(f"User: {s['text']}")
        elif s["kind"] == "assistant_text":
            out.append(f"Assistant: {s['text']}")
        elif s["kind"] == "tool_call":
            out.append(render_call(s))
        else:
            out.append(f"← {s['name']} returned: {s['text']}")
    return "\n".join(out)


# ---------- 3a. argument provenance: deterministic, free ----------

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def ungrounded_args(step, prior):
    """Argument values of a tool call that appear nowhere in prior user turns or tool results.
    A numeric `amount` is also grounded when it is <= an order total seen in a prior tool result."""
    sources = [s["text"] for s in prior if s["kind"] in ("user", "tool_result")]
    blob = "\n".join(sources)
    nums = {float(n) for n in _NUM.findall(blob)}
    totals = []
    for s in prior:
        if s["kind"] == "tool_result":
            try:
                totals.append(float(json.loads(s["text"])["total"]))
            except (ValueError, KeyError, TypeError):
                pass
    bad = {}
    for k, v in step["args"].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            ok = float(v) in nums or (k == "amount" and any(0 < v <= t for t in totals))
        elif isinstance(v, str) and any(c.isdigit() for c in v):
            ok = v.lower() in blob.lower()
        else:
            # ponytail: categorical/free-text args (e.g. topic="refund") are not checked; add a per-tool enum map if needed
            ok = True
        if not ok:
            bad[k] = v
    return bad


# ---------- 3b. Latent scores (public check() only) ----------

def _check(prompt, answer, context, session_id):
    r = runlatent.check(prompt, answer, context=context, session_id=session_id, request_id=f"la-{uuid.uuid4().hex}")
    return {"risk": r.risk, "verdict": r.verdict, "request_id": r.request_id, "status": r.status}


def _last_user(prior):
    return next((s["text"] for s in reversed(prior) if s["kind"] == "user"), None)


def score_answer(step, prior, session_id=None):
    """Score an assistant text step with every tool call and result so far as source."""
    ctx = render_history([s for s in prior if s["kind"] != "user"]) or None
    sent = {"prompt": _last_user(prior), "context": ctx, "answer": step["text"]}
    res = _check(sent["prompt"], step["text"], ctx, session_id)
    flagged = res["verdict"] in FLAGGED
    reason = f"Final answer isn't supported by the tool results (risk {res['risk']:.2f})." if flagged else None
    return {**res, "flagged": flagged, "signal": "latent" if flagged else None, "reason": reason, "sent": sent}


def score_tool_call(step, prior, session_id=None):
    """Flag on argument provenance (free, deterministic). The Latent read of the call rendered as a sentence
    is kept as `latent` for the console: in our runs it read 0.87-0.99 risk on clean calls, so it does not flag."""
    bad = ungrounded_args(step, prior)
    answer = f"I will call {step['name']} with " + ", ".join(f"{k} = {v}" for k, v in step["args"].items()) + "."
    ctx = render_history([s for s in prior if s["kind"] in ("user", "tool_result")])
    sent = {"prompt": _last_user(prior), "context": ctx, "answer": answer}
    res = _check(sent["prompt"], answer, ctx, session_id)
    reason = None
    if bad:
        k, v = next(iter(bad.items()))
        reason = f"Agent called `{step['name']}` with {k} `{v}`, which never appeared in the conversation."
    return {"risk": None, "latent": res, "verdict": "escalate" if bad else "pass", "flagged": bool(bad),
            "signal": "provenance" if bad else None, "ungrounded": bad, "reason": reason, "sent": sent,
            "status": res["status"]}


def score_trajectory(steps, session_id=None):
    """Score every assistant step in order. Returns the steps with an `adapter` result attached."""
    out = []
    for i, s in enumerate(steps):
        s = dict(s)
        if s["kind"] == "assistant_text":
            s["adapter"] = score_answer(s, steps[:i], session_id)
        elif s["kind"] == "tool_call":
            s["adapter"] = score_tool_call(s, steps[:i], session_id)
        out.append(s)
    return out


# ---------- 4. trajectory rollup ----------

def rollup(steps, key="adapter"):
    risks = [s[key]["risk"] for s in steps if s.get(key) and s[key].get("risk") is not None]
    first = next((i for i, s in enumerate(steps) if s.get(key) and s[key].get("flagged")), None)
    return {"risk": max(risks, default=None), "first_bad_step": first,
            "reason": steps[first][key]["reason"] if first is not None else None}
