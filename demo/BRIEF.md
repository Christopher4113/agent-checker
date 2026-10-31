# Demo brief

- Audience: Latent's founder and teams running tool-using agents.
- Problem they recognize: per-answer scoring lets agent steps fall through (tool calls, missing tool results).
- One task to show: the "Show me the gap" guided tour, then open the step drawer on the fake-tool-argument run.
- Visible result that proves it worked: each scenario's summary card; the red first-bad-step card; the drawer
  showing what Latent was sent (`skipped_tool_only`, `[tool_calls omitted]`).
- Why the result matters: the adapter adds coverage for agent steps without false alarms on clean runs.
- Destination and length: README GIF and a captioned MP4, about 60–90 s.
- What the viewer should do next: read results/findings.md.

Data: replay mode only, from web/demo_data/demo.json (produced by scripts/eval.py from real Latent runs on
scripted, planted scenarios). No keys, accounts or personal data; nothing to reset. Numbers on screen
come from that file: 10/48 → 39/48 caught, 0/18 → 18/18 tool-call, 21% → 81% first bad step.

From the repo root:

    reshoot preview demo/reshoot.toml
    reshoot run demo/reshoot.toml
