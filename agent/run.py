"""One order-support agent loop per API path. Each returns the raw provider conversation plus the
response id of every model turn, so scores can be joined back to steps."""
import json

from agent import stub_server
from agent.tools import TOOLS, call_tool

SYSTEM = "You are an order-support agent. Use the tools; only state facts the tools returned."
PATHS = ("anthropic", "chat", "responses")


def run_chat(client, user):
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    tools = [{"type": "function", "function": t} for t in TOOLS]
    ids = []
    while True:
        r = client.chat.completions.create(model="gpt-4.1-mini", messages=msgs, tools=tools)
        ids.append(r.id)
        m = r.choices[0].message
        if not m.tool_calls:
            msgs.append({"role": "assistant", "content": m.content})
            return msgs, ids
        msgs.append({"role": "assistant", "content": None, "tool_calls": [tc.model_dump() for tc in m.tool_calls]})
        for tc in m.tool_calls:
            out = call_tool(tc.function.name, json.loads(tc.function.arguments))
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})


def run_responses(client, user):
    # Full input list every turn; no previous_response_id (spec 6.1).
    items = [{"role": "user", "content": user}]
    tools = [{"type": "function", **t} for t in TOOLS]
    ids = []
    while True:
        r = client.responses.create(model="gpt-4.1-mini", instructions=SYSTEM, input=items, tools=tools)
        ids.append(r.id)
        calls = [o for o in r.output if o.type == "function_call"]
        if not calls:
            items.append({"role": "assistant", "content": r.output_text})
            return items, ids
        for c in calls:
            items.append({"type": "function_call", "call_id": c.call_id, "name": c.name, "arguments": c.arguments})
            items.append({"type": "function_call_output", "call_id": c.call_id,
                          "output": call_tool(c.name, json.loads(c.arguments))})


def run_anthropic(client, user):
    msgs = [{"role": "user", "content": user}]
    tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in TOOLS]
    ids = []
    while True:
        r = client.messages.create(model="claude-haiku-4-5", max_tokens=512, system=SYSTEM, messages=msgs, tools=tools)
        ids.append(r.id)
        msgs.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in r.content]})
        uses = [b for b in r.content if b.type == "tool_use"]
        if not uses:
            return msgs, ids
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": u.id, "content": call_tool(u.name, u.input)} for u in uses]})


def make_client(path, base_url):
    if path == "anthropic":
        import anthropic
        return anthropic.Anthropic(base_url=base_url.removesuffix("/v1"), api_key="stub")
    import openai
    return openai.OpenAI(base_url=base_url, api_key="stub")


def run(scenario, path, client):
    """Replay one scenario through the real client. Returns (raw messages, response ids)."""
    stub_server.SCRIPT[:] = scenario["turns"]
    fn = {"anthropic": run_anthropic, "chat": run_chat, "responses": run_responses}[path]
    return fn(client, scenario["user"])
