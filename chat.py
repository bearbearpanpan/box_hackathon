#!/usr/bin/env python3
"""
chat.py — talk to the Reality Check agent in your terminal.

Claude on Bedrock (BEDROCK_MODEL_ID) runs the conversation and calls the same
tools the Lambda action group exposes: check a deal against Box history, save
the risk report + review task to Box, and list the deal history it read.

    python3 chat.py

Box history is read once per session (Box AI extraction per contract), then
reused for every question. Type `quit` to exit.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "agent", "lambda"))

import handler  # noqa: E402  (sets up sys.path + loads .env)
import catalog as C  # noqa: E402

import boto3  # noqa: E402

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
REGION = os.environ.get("AWS_REGION", "us-east-1")

SYSTEM = """You are Reality Check, a deal-intelligence agent for B2B tech-sales reps.
Sales promises. Ops delivers. You make sure they're the same number.

When a rep describes a deal, call check_deal to compare its promised delivery
timeline against the company's past contracts stored in Box. Map what the rep
says onto the tool's allowed values (e.g. "Ashburn" -> "US-East (Ashburn, VA)",
"GPU racks" -> SKU-HW-GPU). If the region, quarter, promised days, or what is
being sold is missing, ask for it before checking.

Answer format: lead with the verdict emoji + risk level and the headline
(e.g. "55 days promised, history says 139"), then the top risks, the comparable
contract ids behind the verdict, and the suggested safer timeline.

Only call save_report when the rep asks to save, file, or send the report to
the deal desk; it writes a PDF to Box and creates a review task.

Rules:
- Never invent delivery numbers. Use only what the tools return. If there is no
  comparable history, say so plainly (risk UNKNOWN) and say more contracts in
  Box would help.
- You supply intelligence; you do not draft contracts.
- Be concise. A rep wants the number and the reason, not a lecture."""

DEAL_SCHEMA = {
    "type": "object",
    "properties": {
        "customer": {"type": "string"},
        "vertical": {"type": "string"},
        "region": {"type": "string", "enum": C.REGIONS},
        "signed_quarter": {"type": "string", "enum": C.QUARTERS},
        "promised_days": {"type": "integer", "description": "Days from signature to go-live the rep is promising."},
        "hw_vendor": {"type": "string", "enum": C.HW_VENDORS, "description": "Only if the deal includes hardware."},
        "sla_tier": {"type": "string", "enum": [s[0] for s in C.SLA_TIERS]},
        "discount_pct": {"type": "number"},
        "line_items": {
            "type": "array",
            "description": "What is being sold. SKUs: " + "; ".join(f"{p[0]} = {p[1]}" for p in C.PRODUCTS),
            "items": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "enum": [p[0] for p in C.PRODUCTS]},
                    "qty": {"type": "integer"},
                },
                "required": ["sku", "qty"],
            },
        },
    },
    "required": ["region", "signed_quarter", "promised_days", "line_items"],
}

TOOLS = [
    {"toolSpec": {
        "name": "check_deal",
        "description": "Check a draft deal against past contracts in Box. Returns verdict, headline, risks, comparable contracts, and a suggested timeline. Read-only.",
        "inputSchema": {"json": DEAL_SCHEMA},
    }},
    {"toolSpec": {
        "name": "save_report",
        "description": "Run the same check, upload the risk report PDF to Box, and create a review task for the deal desk. Writes to Box; use only when the rep asks.",
        "inputSchema": {"json": DEAL_SCHEMA},
    }},
    {"toolSpec": {
        "name": "list_deal_history",
        "description": "List the past contracts read from Box with their key fields.",
        "inputSchema": {"json": {"type": "object", "properties": {}}},
    }},
]

# Read Box once per chat session instead of on every tool call.
_load_history = handler._history
_cache = {}


def _cached_history():
    if "h" not in _cache:
        print("  (reading deal history from Box...)", flush=True)
        _cache["h"] = _load_history()
    return _cache["h"]


handler._history = _cached_history


def run_tool(name: str, args: dict) -> dict:
    if name == "check_deal":
        return handler.run_action("raise-risks", args)
    if name == "save_report":
        out = handler.run_action("analyze-and-report", args)
        out.pop("research", None)  # long add-on brief; not needed in chat
        return out
    if name == "list_deal_history":
        _, records = _cached_history()
        keys = ("contract_id", "customer", "region", "signed_quarter", "hw_vendor",
                "tcv", "promised_days", "actual_days")
        return {"count": len(records), "contracts": [{k: r.get(k) for k in keys} for r in records]}
    raise ValueError(f"unknown tool {name}")


def main():
    client = boto3.client("bedrock-runtime", region_name=REGION)
    messages = []
    print(f"Reality Check agent ({MODEL_ID}). Describe a deal, or type 'quit'.\n")

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() in ("quit", "exit"):
            break
        messages.append({"role": "user", "content": [{"text": user}]})

        # Agent loop: keep going while the model asks for tools.
        while True:
            resp = client.converse(
                modelId=MODEL_ID,
                system=[{"text": SYSTEM}],
                messages=messages,
                toolConfig={"tools": TOOLS},
                inferenceConfig={"maxTokens": 4096},
            )
            msg = resp["output"]["message"]
            messages.append(msg)

            for block in msg["content"]:
                if "text" in block and block["text"].strip():
                    print(f"\nagent> {block['text'].strip()}\n")

            if resp["stopReason"] != "tool_use":
                break

            results = []
            for block in msg["content"]:
                if "toolUse" not in block:
                    continue
                tu = block["toolUse"]
                print(f"  [tool] {tu['name']} {json.dumps(tu['input'])}", flush=True)
                try:
                    out = json.loads(json.dumps(run_tool(tu["name"], tu["input"]), default=str))
                    results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"json": out}]}})
                except Exception as exc:
                    results.append({"toolResult": {"toolUseId": tu["toolUseId"], "status": "error",
                                                   "content": [{"text": f"{type(exc).__name__}: {exc}"}]}})
            messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    main()
