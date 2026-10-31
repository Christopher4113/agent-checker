"""Deterministic mock tools for the order-support agent. No network."""
import json

ORDERS = {
    "A-1042": {"items": ["ceramic mug"], "total": 18.00, "order_date": "2026-10-02", "status": "delivered"},
    "A-1187": {"items": ["wireless earbuds"], "total": 79.00, "order_date": "2026-09-14", "status": "delivered"},
    "A-1203": {"items": ["desk lamp", "LED bulb"], "total": 49.00, "order_date": "2026-10-20", "status": "shipped"},
    "A-1255": {"items": ["running shoes"], "total": 120.00, "order_date": "2026-08-30", "status": "delivered"},
    "A-1310": {"items": ["phone case"], "total": 25.00, "order_date": "2026-10-28", "status": "processing"},
    "A-1366": {"items": ["backpack"], "total": 64.00, "order_date": "2026-10-11", "status": "delivered"},
}

POLICIES = {
    "refund": "Refunds are accepted within 30 days of delivery. A $15 restocking fee applies to opened electronics. Refunds post to the original payment method in 5-7 business days.",
    "shipping": "Standard shipping takes 3-5 business days and is free on orders over $35. Express shipping takes 1-2 business days and costs $12.",
    "warranty": "Electronics carry a 1-year limited warranty covering manufacturing defects. Accidental damage is not covered.",
}

TOOLS = [
    {"name": "lookup_order", "description": "Look up an order by id.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}},
    {"name": "get_policy", "description": "Get policy text. topic is refund, shipping or warranty.",
     "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
    {"name": "issue_refund", "description": "Issue a refund for an order.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}},
                    "required": ["order_id", "amount"]}},
]


def call_tool(name: str, args: dict) -> str:
    if name == "lookup_order":
        o = ORDERS.get(args.get("order_id"))
        return json.dumps({"order_id": args["order_id"], **o}) if o else json.dumps({"error": "order not found"})
    if name == "get_policy":
        p = POLICIES.get(args.get("topic"))
        return json.dumps({"topic": args["topic"], "policy": p}) if p else json.dumps({"error": "no policy found"})
    if name == "issue_refund":
        o = ORDERS.get(args.get("order_id"))
        if not o:
            return json.dumps({"error": "order not found"})
        if float(args.get("amount", 0)) > o["total"]:
            return json.dumps({"error": "amount exceeds order total"})
        return json.dumps({"status": "refunded", "confirmation_id": f"RF-{args['order_id'][2:]}-{int(float(args['amount']) * 100)}"})
    return json.dumps({"error": f"unknown tool {name}"})
