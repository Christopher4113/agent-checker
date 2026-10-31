"""A stub model server that speaks OpenAI Chat Completions, OpenAI Responses and Anthropic Messages.

The real `openai` / `anthropic` clients are pointed at it with `base_url`, so `runlatent.auto_instrument()`
captures every turn exactly as it would in production. It replays the scenario's scripted turns; the turn
index is the number of tool results already in the request, so the server is stateless per request.
"""
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT: list[dict] = []  # the current scenario's turns; set by the runner (one scenario at a time)


def _id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _chat(body):
    n = sum(1 for m in body["messages"] if m.get("role") == "tool")
    t = SCRIPT[n]
    if "call" in t:
        msg = {"role": "assistant", "content": None, "tool_calls": [{
            "id": _id("call"), "type": "function",
            "function": {"name": t["call"]["name"], "arguments": json.dumps(t["call"]["args"])}}]}
        finish = "tool_calls"
    else:
        msg, finish = {"role": "assistant", "content": t["say"]}, "stop"
    return {"id": _id("chatcmpl"), "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "message": msg, "finish_reason": finish, "logprobs": None}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def _responses(body):
    n = sum(1 for i in body["input"] if isinstance(i, dict) and i.get("type") == "function_call_output")
    t = SCRIPT[n]
    if "call" in t:
        out = [{"type": "function_call", "id": _id("fc"), "call_id": _id("call"), "name": t["call"]["name"],
                "arguments": json.dumps(t["call"]["args"]), "status": "completed"}]
    else:
        out = [{"type": "message", "id": _id("msg"), "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": t["say"], "annotations": []}]}]
    return {"id": _id("resp"), "object": "response", "created_at": 0, "model": body["model"], "status": "completed",
            "output": out, "parallel_tool_calls": True, "tool_choice": "auto", "tools": body.get("tools", []),
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}


def _anthropic(body):
    n = sum(1 for m in body["messages"] if isinstance(m.get("content"), list)
            for b in m["content"] if b.get("type") == "tool_result")
    t = SCRIPT[n]
    if "call" in t:
        content = [{"type": "tool_use", "id": _id("toolu"), "name": t["call"]["name"], "input": t["call"]["args"]}]
        stop = "tool_use"
    else:
        content, stop = [{"type": "text", "text": t["say"]}], "end_turn"
    return {"id": _id("msg"), "type": "message", "role": "assistant", "model": body["model"], "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


ROUTES = {"/v1/chat/completions": _chat, "/v1/responses": _responses, "/v1/messages": _anthropic}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        out = json.dumps(ROUTES[self.path.split("?")[0]](body)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def start() -> str:
    """Start the stub on a free port in a daemon thread; return its base URL (…/v1)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/v1"
