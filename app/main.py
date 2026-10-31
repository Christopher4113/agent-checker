"""Demo server: the static page (replay mode, no keys), /api/live (SSE, needs LATENT_API_KEY), password gate.

    uvicorn app.main:app --reload
"""
import asyncio
import json
import os
import pathlib
import secrets
import sys

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

PASSWORD = os.environ.get("DEMO_PASSWORD")
LIVE = bool(os.environ.get("LATENT_API_KEY"))
basic = HTTPBasic(auto_error=False)


def gate(creds: HTTPBasicCredentials | None = Depends(basic)):
    if PASSWORD and not (creds and secrets.compare_digest(creds.password.encode(), PASSWORD.encode())):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


app = FastAPI(dependencies=[Depends(gate)])


@app.get("/api/config")
def config():
    return {"live": LIVE}


_live = {}


def _live_run(scenario_id, path):
    if not _live:  # lazy: importing run_all calls auto_instrument(), only wanted when live mode is used
        import yaml
        from scripts import eval as ev, run_all
        from agent import stub_server
        _live.update(run_all=run_all, ev=ev, base=stub_server.start(),
                     scenarios={s["id"]: s for s in yaml.safe_load((ROOT / "scenarios.yaml").read_text())})
    sc = _live["scenarios"][scenario_id]
    return _live["ev"].demo_run(_live["run_all"].run_one(sc, path, _live["base"]))


@app.get("/api/live")
async def live(scenario: str, path: str):
    if not LIVE:
        raise HTTPException(400, "live mode needs LATENT_API_KEY")
    if path not in ("anthropic", "chat", "responses"):
        raise HTTPException(400, "bad path")

    async def events():
        # ponytail: the run is scored in full, then streamed step by step; score per step if latency matters
        run = await asyncio.to_thread(_live_run, scenario, path)
        for s in run["steps"]:
            yield f"event: step\ndata: {json.dumps(s)}\n\n"
            await asyncio.sleep(0.4)
        yield f"event: summary\ndata: {json.dumps({'summary': run['summary']})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
