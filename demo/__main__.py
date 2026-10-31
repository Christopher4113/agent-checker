"""python -m demo --scenario refund_wrong_real_order --path chat [--live]"""
import argparse
import json
import pathlib
import sys

from rich.console import Console
from rich.table import Table

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
COLOR = {"ok": "green", "flag": "red", "none": "grey50"}
KIND = {"user": "User", "tool_call": "Tool call", "tool_result": "Tool result", "assistant_text": "Final answer"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="refund_wrong_real_order")
    ap.add_argument("--path", default="chat", choices=("anthropic", "chat", "responses"))
    ap.add_argument("--live", action="store_true", help="run against the real Latent API (needs LATENT_API_KEY)")
    a = ap.parse_args()
    if a.live:
        from app.main import _live_run
        run = _live_run(a.scenario, a.path)
    else:
        runs = json.loads((ROOT / "web" / "demo_data" / "demo.json").read_text())["runs"]
        run = runs[f"{a.scenario}|{a.path}"]

    badge = lambda b: f"[{COLOR[b['state']]}]{b['label']}[/]" if b else ""
    t = Table(title=f"{a.scenario} · {a.path}" + (" · live" if a.live else ""), show_lines=True)
    for col in ("#", "step", "Latent (stock)", "with adapter"):
        t.add_column(col)
    for i, s in enumerate(run["steps"]):
        if s["kind"] == "tool_call":
            text = f"{s['name']}(" + ", ".join(f"{k}={json.dumps(v)}" for k, v in s["args"].items()) + ")"
        else:
            text = s["text"]
        if run["first_bad"] == i and s["reason"]:
            text += f"\n[red]{s['reason']}[/]"
        t.add_row(f"[red]{i + 1}[/]" if run["first_bad"] == i else str(i + 1),
                  f"[dim]{KIND[s['kind']]}[/]\n{text}", badge(s["stock"]), badge(s["adapter"]))
    c = Console()
    c.print(t)
    c.print(f"[bold]{run['summary']}[/]")


if __name__ == "__main__":
    main()
