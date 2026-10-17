from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "agent", "lambda", "tools"))
sys.path.insert(0, os.path.join(ROOT, "box"))
sys.path.insert(0, os.path.join(ROOT, "data"))

import envload  # noqa: E402
from minipdf import PdfDoc  # noqa: E402

envload.load_env()
if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK") and os.environ.get("BEDROCK_AGENT_API_KEY"):
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = os.environ["BEDROCK_AGENT_API_KEY"]

RESULTS = ["No risk", "Risk identified", "No source found"]
CATEGORIES = ["Feature availability", "Delivery deadline", "Performance commitment"]
CATEGORY_SEVERITY = {"Feature availability": "High", "Delivery deadline": "High", "Performance commitment": "Medium"}
SEVERITY_ORDER = {"High": 0, "Medium": 1, "None": 2}


def pdf_text(data: bytes) -> str:
    parts = re.findall(rb"\(((?:\\.|[^\\)])*)\) Tj", data)
    lines = [re.sub(rb"\\(.)", rb"\1", p).decode("latin-1") for p in parts]
    return "\n".join(lines)


def last_updated(text: str) -> str:
    m = re.search(r"Last updated:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", text)
    return " ".join(m.group(1).split()) if m else "unknown"


class LocalDocs:
    kind = "local"

    def __init__(self) -> None:
        self.base = os.path.join(ROOT, "docs", "box_upload")
        self.reports = os.path.join(ROOT, "data", "reports")

    def _list(self, sub: str) -> List[Dict[str, str]]:
        folder = os.path.join(self.base, sub)
        return [{"id": os.path.join(folder, n), "name": n, "link": os.path.join(folder, n)}
                for n in sorted(os.listdir(folder)) if n.endswith(".pdf")]

    def contracts(self) -> List[Dict[str, str]]:
        return self._list("contracts")

    def evidence(self) -> List[Dict[str, str]]:
        return self._list("evidence")

    def read(self, file_id: str) -> bytes:
        with open(file_id, "rb") as fh:
            return fh.read()

    def upload_report(self, name: str, data: bytes) -> Dict[str, str]:
        os.makedirs(self.reports, exist_ok=True)
        path = os.path.join(self.reports, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return {"id": path, "link": path}


class BoxDocs:
    kind = "box"

    def __init__(self) -> None:
        from box_client import BoxClient
        self.client = BoxClient()
        self.contracts_folder = os.environ["BOX_CONTRACTS_FOLDER_ID"]
        self.evidence_folder = os.environ["BOX_EVIDENCE_FOLDER_ID"]
        self.reports_folder = os.environ["BOX_REPORTS_FOLDER_ID"]

    def _list(self, folder: str) -> List[Dict[str, str]]:
        return [{"id": f.id, "name": f.name, "link": f"https://app.box.com/file/{f.id}"}
                for f in sorted(self.client.list_files(folder), key=lambda f: f.name)]

    def contracts(self) -> List[Dict[str, str]]:
        return self._list(self.contracts_folder)

    def evidence(self) -> List[Dict[str, str]]:
        return self._list(self.evidence_folder)

    def read(self, file_id: str) -> bytes:
        return self.client.download_bytes(file_id)

    def upload_report(self, name: str, data: bytes) -> Dict[str, str]:
        file_id = self.client.upload_pdf(name, data, folder_id=self.reports_folder)
        return {"id": file_id, "link": f"https://app.box.com/file/{file_id}"}


def get_docs(offline: bool = False):
    has_auth = os.environ.get("BOX_DEVELOPER_TOKEN") or os.environ.get("BOX_ENTERPRISE_ID")
    has_folders = all(os.environ.get(k) for k in
                      ("BOX_CONTRACTS_FOLDER_ID", "BOX_EVIDENCE_FOLDER_ID", "BOX_REPORTS_FOLDER_ID"))
    if not offline and has_auth and has_folders:
        return BoxDocs()
    return LocalDocs()


def bedrock():
    import boto3
    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


REVIEW_SYSTEM = """You review a proposed sales contract before it is shared or signed. You never draft or rewrite contracts.

1. Extract every customer-facing claim about feature availability, delivery deadlines, or performance. Keep the exact wording and contract location (for example "Section 3"). Split statements that contain several commitments. Ignore commercials, signatures, and anything outside those three categories.
2. For each claim, look for relevant evidence in the provided Box documents (B1, B2, ...).
3. Compare the claim with the evidence, including Region, configuration, date, workload, and other conditions. A roadmap Target or Exploratory item does not support a promised feature or date. A benchmark supports only claims within its tested conditions. Burst figures do not support sustained claims.
4. Result rules:
   - No relevant source in the documents: result "No source found". State what evidence was sought.
   - Source matches the claim including its conditions: result "No risk".
   - Source contradicts or does not support the claim: result "Risk identified" with exactly one risk_category.
Use only the provided documents. Quote the supporting passage or data point."""

REVIEW_TOOL = {
    "toolSpec": {
        "name": "submit_review",
        "description": "Submit the claim-by-claim contract review.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "claim": {"type": "string"},
                            "result": {"type": "string", "enum": RESULTS},
                            "risk_category": {"type": "string", "enum": CATEGORIES + ["None"]},
                            "evidence_ref": {"type": "string", "description": "B1, B2, ... or empty when no source"},
                            "evidence_passage": {"type": "string"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["location", "claim", "result", "risk_category",
                                     "evidence_ref", "evidence_passage", "explanation"],
                    },
                }
            },
            "required": ["claims"],
        }},
    }
}


def llm_review(client, contract_name: str, contract_text: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks = [f"CONTRACT: {contract_name}\n{contract_text}"]
    for s in sources:
        blocks.append(f"SOURCE {s['ref']}: {s['name']} (last updated {s['last_updated']})\n{s['text']}")
    resp = client.converse(
        modelId=os.environ["BEDROCK_MODEL_ID"],
        system=[{"text": REVIEW_SYSTEM}],
        messages=[{"role": "user", "content": [{"text": "\n\n---\n\n".join(blocks)}]}],
        toolConfig={"tools": [REVIEW_TOOL], "toolChoice": {"tool": {"name": "submit_review"}}},
        inferenceConfig={"maxTokens": 4000},
    )
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]["claims"]
    raise RuntimeError("Model did not return a review.")


def score(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for c in claims:
        c = dict(c)
        if c["result"] == "No risk":
            c["risk_category"], c["severity"] = "None", "None"
        elif c["result"] == "No source found":
            c["risk_category"], c["severity"] = "None", "High"
        else:
            c["severity"] = CATEGORY_SEVERITY.get(c["risk_category"], "High")
        out.append(c)
    return sorted(out, key=lambda c: (SEVERITY_ORDER[c["severity"]], c["result"] == "No risk"))


def summarize(claims: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {r: sum(1 for c in claims if c["result"] == r) for r in RESULTS}
    counts.update({f"severity_{s}": sum(1 for c in claims if c["severity"] == s) for s in SEVERITY_ORDER})
    return counts


def build_report(contract: Dict[str, str], claims: List[Dict[str, Any]], counts: Dict[str, int],
                 sources: List[Dict[str, Any]]) -> bytes:
    doc = PdfDoc()
    doc.add_heading(f"Contract Risk Review: {contract['name'].rsplit('.', 1)[0]}")
    doc.add_paragraph(f"Generated {datetime.now().strftime('%B %d, %Y %H:%M')} by Reality Check. "
                      "This report supports human judgment; it does not approve the contract for signature.")
    doc.add_rule()
    doc.add_subheading(f"{len(claims)} claims reviewed")
    doc.add_paragraph(f"{counts['No risk']} No risk | {counts['Risk identified']} Risk identified | "
                      f"{counts['No source found']} No source found")
    doc.add_paragraph(f"Severity: {counts['severity_High']} High | {counts['severity_Medium']} Medium | "
                      f"{counts['severity_None']} None")
    doc.add_rule()
    refs = {s["ref"]: s for s in sources}
    for i, c in enumerate(claims, 1):
        doc.add_subheading(f"{i}. {c['location']}: {c['result']} | Severity {c['severity']}")
        doc.add_paragraph(f"Claim: \"{c['claim']}\"")
        if c["risk_category"] != "None":
            doc.add_keyvalue("Risk category", c["risk_category"])
        src = refs.get(c.get("evidence_ref", ""))
        if src:
            doc.add_keyvalue("Evidence", f"[{src['ref']}] {src['name']} (updated {src['last_updated']})")
        if c.get("evidence_passage"):
            doc.add_paragraph(f"Passage: {c['evidence_passage']}")
        doc.add_paragraph(f"Why: {c['explanation']}")
        doc.add_spacer(4)
    doc.add_rule()
    doc.add_subheading("Source references")
    for s in sources:
        doc.add_paragraph(f"{s['ref']}: {s['name']} | last updated {s['last_updated']} | {s['link']}")
    return doc.render()


def review_contract(docs, contract_name: str, client=None) -> Dict[str, Any]:
    matches = [c for c in docs.contracts() if contract_name.lower() in c["name"].lower()]
    if not matches:
        return {"error": f"No contract matching '{contract_name}'.",
                "available": [c["name"] for c in docs.contracts()]}
    contract = min(matches, key=lambda c: len(c["name"]))
    contract_text = pdf_text(docs.read(contract["id"]))
    sources = []
    for i, e in enumerate(docs.evidence(), 1):
        text = pdf_text(docs.read(e["id"]))
        sources.append({**e, "ref": f"B{i}", "text": text, "last_updated": last_updated(text)})
    claims = score(llm_review(client or bedrock(), contract["name"], contract_text, sources))
    counts = summarize(claims)
    pdf = build_report(contract, claims, counts, sources)
    name = f"Risk Review - {contract['name'].rsplit('.', 1)[0]} - {datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
    report = docs.upload_report(name, pdf)
    return {
        "contract": contract["name"],
        "contract_link": contract["link"],
        "summary": counts,
        "claims": [{k: c[k] for k in ("location", "claim", "result", "risk_category", "severity",
                                      "evidence_ref", "explanation")} for c in claims],
        "sources": [{k: s[k] for k in ("ref", "name", "last_updated", "link")} for s in sources],
        "report_name": name,
        "report_link": report["link"],
    }


CHAT_SYSTEM = """You are Reality Check, a contract risk review assistant for sales and field teams.
You check a proposed customer contract against approved product documentation, the product roadmap, and delivery reviews stored in Box.
You never draft, rewrite, approve, or negotiate contracts.
Use list_contracts to see contracts in Box and review_contract to review one.
After a review, reply with: the claim counts, then each flagged claim ordered by severity (location, result, category, severity, evidence reference, one-line reason), then the Box link to the report. Keep it short."""

CHAT_TOOLS = [
    {"toolSpec": {"name": "list_contracts", "description": "List contracts available for review in Box.",
                  "inputSchema": {"json": {"type": "object", "properties": {}}}}},
    {"toolSpec": {"name": "review_contract",
                  "description": "Review one contract claim by claim against the Box evidence documents and save the report to Box.",
                  "inputSchema": {"json": {"type": "object",
                                           "properties": {"contract_name": {"type": "string"}},
                                           "required": ["contract_name"]}}}},
]


def run_tool(docs, name: str, args: Dict[str, Any], client) -> Dict[str, Any]:
    try:
        if name == "list_contracts":
            return {"contracts": [c["name"] for c in docs.contracts()]}
        if name == "review_contract":
            return review_contract(docs, args.get("contract_name", ""), client)
        return {"error": f"Unknown tool {name}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def chat(docs, client) -> None:
    print(f"Reality Check agent ({docs.kind} documents, model {os.environ.get('BEDROCK_MODEL_ID')}). Type 'exit' to quit.")
    messages: List[Dict[str, Any]] = []
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in ("exit", "quit"):
            break
        if not user:
            continue
        messages.append({"role": "user", "content": [{"text": user}]})
        while True:
            resp = client.converse(modelId=os.environ["BEDROCK_MODEL_ID"], system=[{"text": CHAT_SYSTEM}],
                                   messages=messages, toolConfig={"tools": CHAT_TOOLS},
                                   inferenceConfig={"maxTokens": 2000})
            msg = resp["output"]["message"]
            messages.append(msg)
            uses = [b["toolUse"] for b in msg["content"] if "toolUse" in b]
            for b in msg["content"]:
                if "text" in b and b["text"].strip():
                    print(f"\nagent> {b['text']}")
            if not uses:
                break
            results = []
            for u in uses:
                print(f"  [tool] {u['name']} {json.dumps(u['input'])}")
                out = run_tool(docs, u["name"], u["input"], client)
                results.append({"toolResult": {"toolUseId": u["toolUseId"], "content": [{"json": out}]}})
            messages.append({"role": "user", "content": results})


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Reality Check local agent (Claude on Amazon Bedrock + Box).")
    ap.add_argument("--offline", action="store_true", help="read docs/box_upload instead of Box")
    ap.add_argument("--review", metavar="CONTRACT", help="review one contract and print the result")
    ap.add_argument("--list", action="store_true", help="list contracts and evidence")
    args = ap.parse_args(argv)
    docs = get_docs(args.offline)
    if args.list:
        print(json.dumps({"source": docs.kind, "contracts": [c["name"] for c in docs.contracts()],
                          "evidence": [e["name"] for e in docs.evidence()]}, indent=2))
        return
    if args.review:
        print(json.dumps(review_contract(docs, args.review), indent=2))
        return
    chat(docs, bedrock())


if __name__ == "__main__":
    main()
