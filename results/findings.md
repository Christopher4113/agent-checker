# Findings: Latent on a tool-using agent

Same order-support agent, same 24 scenarios (8 clean, 16 with a planted hallucination), run on three API paths: Anthropic Messages, OpenAI Chat Completions and OpenAI Responses. Scores come from the hosted Latent API (free plan, `runlatent` 0.3.9). Every number below comes from `results/metrics.json`, and `python scripts/eval.py` rebuilds it from `runs/results.jsonl` with no API calls.

Frontier models rarely hallucinate on tasks this simple, so the hallucinations were **planted**: the model turns are scripted and served by a stub server that speaks each provider's wire format. The real `openai` / `anthropic` clients point at it with `base_url`, so `auto_instrument()` captures every turn through its normal production path.

## Headline (raw counts)

| | Stock (`auto_instrument` + `session`) | Stock + `context()` | With `latent_agents` |
|---|---|---|---|
| Planted hallucinations caught (all paths) | 10/48 | 10/48 | **39/48** |
| Tool-argument hallucinations caught | 0/18 | 0/18 | **18/18** |
| First bad step located | 10/48 | 10/48 | **39/48** |
| Clean runs with a false alarm | 5/24 | 5/24 | **0/24** |

Caught per path: stock got 3/16 on Anthropic, 6/16 on Chat Completions and 1/16 on Responses. The adapter got 13/16 on each path.

### Recall by hallucination type and path (stock / stock + context / adapter)

| Type | Anthropic | Chat Completions | Responses |
|---|---|---|---|
| A: final answer fabricates (n=6) | 3 / 3 / 5 | 4 / 4 / 5 | 1 / 1 / 5 |
| B: invented tool argument (n=6) | 0 / 0 / 6 | 0 / 0 / 6 | 0 / 0 / 6 |
| C: specifics after "not found" (n=4) | 0 / 0 / 2 | 2 / 2 / 2 | 0 / 0 / 2 |
| Clean runs with a false alarm (n=8) | 0 / 0 / 0 | 0 / 0 / 0 | 5 / 5 / 0 |

Adapter overhead: about 255 ms per scored step (p50, one `check()` round trip). The full matrix used 315 scored answers (144 captures plus 171 adapter checks), out of the 5,000 a month on the free plan. SDK `stats()`: captured 144, posted 144, failed 0, dropped 0, skipped_tool_only 198.

## The code-reading claims, checked

The body each capture would post was recorded with the documented `redact=` hook, which passes it through unchanged.

1. **Tool-call turns are not scored. Confirmed.** All 198 tool-only turns were counted `skipped_tool_only` and never posted, so 0/18 invented tool arguments were caught. Note: the SDK has an opt-in `post_tool_only_turns=True`, and its README suggests posting the turn that speaks to the user. We did not test that flag, because a tool-only turn has no answer text to score.
2. **Past tool calls are removed from the history. Confirmed.** The posted history shows `[tool_calls omitted]` on Chat Completions and `[tool_use omitted]` on Anthropic. The reader never sees which order was refunded or for how much.
3. **The Responses API drops tool results. Confirmed.** Every final answer on Responses (24/24) was posted with only the system and user messages. `function_call` and `function_call_output` items were dropped (`items_dropped: 2`). This mostly showed up as **false alarms** rather than misses: 5/8 clean answers were flagged at 0.96–0.99 risk, and only 1/6 type-A fabrications were caught. With no source, the reader can't tell a correct answer from a made-up one.
4. **Anthropic keeps tool results. Confirmed.** `tool_result` text is posted as a user message, and Chat Completions keeps `role: "tool"` messages too. Both paths had 0/8 false alarms.
5. **No step or trajectory view. Confirmed** for the public SDK. `session()` groups turns, but nothing in the SDK points at the first bad step. (The console's session view wasn't reviewed for this.)

Two more things the experiment showed:

- **Wrapping runs in `runlatent.context(tool_results)` changed nothing.** The context did reach the posted body on every path, but the risk matched stock to two decimals on all 72 runs, including the Responses false alarms. `check()` says *"context goes in the messages when messages=... is given"*, so the hosted reader seems to read sources from `messages` for captured chat turns. The documented way to add sources therefore doesn't cover the Responses gap.
- **Scoring a tool call written out as a sentence was noisy.** Rendering a call as "I will call get_policy with topic = refund." and scoring it with `check()` gave 0.87–0.99 risk on clean calls in the 4-scenario dev subset, and 6/9 clean `get_policy` calls were flagged. The reader is tuned for factual answers, not for intents. So the adapter flags tool calls only on **argument provenance** and keeps the Latent read as a reference value in the step drawer.

## Three worked trajectories

**`refund_wrong_real_order` on Chat Completions.** The user asks for a refund on A-1042. The agent calls `issue_refund(order_id="A-1366", amount=18.0)`. A-1366 is a real order that belongs to someone else, so the refund goes through. Stock Latent scored the cheerful final answer at 0.06 and never saw the call. The adapter flagged step 4: *"Agent called `issue_refund` with order_id `A-1366`, which never appeared in the conversation."*

**`shoes_item_fab` on Responses.** The tool says "running shoes, 2026-08-30, $120". The answer says "shoes and socks, 2026-09-12, $95". Stock Latent saw only the system and user messages and passed it. The adapter sent the tool result as `context=` and caught it at the final step.

**`status_clean` on Responses.** A correct answer that matches the tool result exactly. Stock flagged it at 0.98 with no source. The adapter passed it at 0.04.

## What the adapter missed (9/48)

- `refund_amount_fab` (3 paths): "refunded $45.00 … within 24 hours" when the order total was $18.00. The reader passed it even with the order JSON as context.
- `unknown_policy` and `unknown_order_items` (3 paths each): the tool returned `{"error": ...}` and the answer invented a price-match policy and order contents anyway. The reader passed these.

All 9 are reader calls where the source was present, not coverage gaps.

## Limitations

- Planted errors and scripted model turns, with no natural hallucinations. Mock, deterministic tools. Small n (6, 6 and 4 per type per path), so read the raw counts, not the percentages.
- Free plan and the hosted reader only. No in-band probes (Enterprise), and no hold or route actions.
- Argument provenance is a string and number match. Free-text and categorical arguments (for example `topic="refund"`) are not checked. An ID the user typed slightly differently would be flagged.
- One run of the full matrix (plus a 4-scenario dev subset).
- No console screenshots are included yet (`results/img/` is empty).

## Possible product features (agent coverage I'd love to help build)

1. **Keep `function_call_output` as source on the Responses path.** This is the API the OpenAI Agents SDK uses by default. Today a correct agent answer there looks unsourced.
2. **A `tool_calls` field on scored answers**, with a cheap provenance check on arguments: did this ID or amount appear in the user turns or earlier tool results? It's deterministic, costs nothing, and caught 18/18 here.
3. **A first-bad-step view on sessions**: the trajectory's highest risk plus the earliest flagged step and a one-line reason, built on the `session()` grouping that already exists.
