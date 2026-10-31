"""python -m pytest -q  (or python test_latent_agents.py). No network: the stub model server only."""
import yaml

from agent import run, stub_server
from latent_agents import rollup, to_steps, ungrounded_args

S = {s["id"]: s for s in yaml.safe_load(open("scenarios.yaml"))}
BASE = stub_server.start()


def test_normalisers_agree_across_paths():
    for sid in ("refund_clean", "warranty_fab", "refund_fake_id"):
        shapes = []
        for p in run.PATHS:
            msgs, ids = run.run(S[sid], p, run.make_client(p, BASE))
            steps = to_steps(msgs, p)
            shapes.append([(s["kind"], s.get("name"), s.get("args"), s.get("turn")) for s in steps])
            assert max(s["turn"] for s in steps if s["turn"] is not None) == len(ids) - 1
        assert shapes[0] == shapes[1] == shapes[2], sid
        assert [k for k, *_ in shapes[0]][0] == "user" and shapes[0][-1][0] == "assistant_text"


def test_provenance():
    prior = [{"kind": "user", "text": "Refund order A-1042 please"},
             {"kind": "tool_result", "text": '{"order_id": "A-1042", "total": 18.0}'}]
    call = lambda **a: {"kind": "tool_call", "name": "issue_refund", "args": a}
    assert ungrounded_args(call(order_id="A-1042", amount=18.0), prior) == {}
    assert ungrounded_args(call(order_id="A-1042", amount=10.0), prior) == {}        # derivable: <= total
    assert ungrounded_args(call(order_id="A-1042", amount=94.0), prior) == {"amount": 94.0}
    assert ungrounded_args(call(order_id="A-7731", amount=18.0), prior) == {"order_id": "A-7731"}
    assert ungrounded_args({"kind": "tool_call", "name": "get_policy", "args": {"topic": "refund"}}, []) == {}


def test_rollup():
    steps = [{"kind": "user"},
             {"kind": "tool_call", "adapter": {"risk": 0.1, "flagged": False, "reason": None}},
             {"kind": "tool_call", "adapter": {"risk": 0.4, "flagged": True, "reason": "bad arg"}},
             {"kind": "assistant_text", "adapter": {"risk": 0.9, "flagged": True, "reason": "bad text"}}]
    assert rollup(steps) == {"risk": 0.9, "first_bad_step": 2, "reason": "bad arg"}
    assert rollup(steps[:2])["first_bad_step"] is None


if __name__ == "__main__":
    test_normalisers_agree_across_paths(); test_provenance(); test_rollup(); print("ok")
