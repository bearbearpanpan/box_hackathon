import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_agent as la  # noqa: E402

CANNED = [
    {"location": "Section 1", "claim": "The archive will support encryption at rest in the agreed configuration.",
     "result": "No risk", "risk_category": "None", "evidence_ref": "B1",
     "evidence_passage": "Encryption at rest: supported", "explanation": "B1 confirms encryption at rest for the Archive tier in US-West (Oregon)."},
    {"location": "Section 2", "claim": "The archive will include the proposed Smart Archive Search feature at launch.",
     "result": "Risk identified", "risk_category": "Feature availability", "evidence_ref": "B2",
     "evidence_passage": "Exploratory", "explanation": "Roadmap lists Smart Archive Search as Exploratory with no release date; it cannot ship at launch."},
    {"location": "Section 3", "claim": "The archive migration will be completed within 30 days of signature.",
     "result": "Risk identified", "risk_category": "Delivery deadline", "evidence_ref": "B3",
     "evidence_passage": "58-72 days", "explanation": "Comparable 400-800 TB migrations took 58-72 days; the contract promises 30."},
    {"location": "Section 4", "claim": "The archive will sustain read throughput of 10 GB/s in the agreed configuration.",
     "result": "Risk identified", "risk_category": "Performance commitment", "evidence_ref": "B1",
     "evidence_passage": "5 GB/s", "explanation": "Benchmark validates 5 GB/s sustained; 10 GB/s has not been tested."},
    {"location": "Section 5", "claim": "The archive will support direct import from Northstar's LegacyVault system.",
     "result": "No source found", "risk_category": "None", "evidence_ref": "", "evidence_passage": "",
     "explanation": "No Box document mentions LegacyVault direct import; confirm with the product owner."},
]


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kw):
        self.calls.append(kw)
        return {"output": {"message": {"content": [{"toolUse": {"toolUseId": "t1", "name": "submit_review",
                                                                 "input": {"claims": CANNED}}}]}}}


def test_pdf_text_roundtrip():
    docs = la.LocalDocs()
    b3 = [e for e in docs.evidence() if e["name"].startswith("B3")][0]
    text = la.pdf_text(docs.read(b3["id"]))
    assert "58-72 days" in text
    assert la.last_updated(text) == "September 30, 2026"


def test_review_pipeline():
    fake = FakeBedrock()
    out = la.review_contract(la.LocalDocs(), "Northstar-Archive-Migration-Agreement", fake)
    assert out["contract"] == "Northstar-Archive-Migration-Agreement.pdf"
    prompt = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert "30 days of signature" in prompt and "SOURCE B2" in prompt and "Exploratory" in prompt
    s = out["summary"]
    assert (s["No risk"], s["Risk identified"], s["No source found"]) == (1, 3, 1)
    assert (s["severity_High"], s["severity_Medium"], s["severity_None"]) == (3, 1, 1)
    assert [c["severity"] for c in out["claims"]] == ["High", "High", "High", "Medium", "None"]
    assert os.path.isfile(os.path.join(la.ROOT, out["report_link"]))
    assert out["comments_posted_on_contract"] == 5
    comments = open(os.path.join(la.ROOT, "reports", "Northstar-Archive-Migration-Agreement.comments.txt")).read()
    assert "Section 3: Delivery deadline risk (High)" in comments
    assert "Section 1: No risk" in comments and "Full report:" in comments


def test_match_contract_names():
    cs = [{"name": "Northstar-Archive-Migration-Agreement-v2.pdf"}, {"name": "Northstar-Archive-Migration-Agreement.pdf"}]
    assert la.match_contract(cs, "Northstar Archive Migration Agreement")["name"] == cs[1]["name"]
    assert la.match_contract(cs, "the Northstar agreement")["name"] == cs[1]["name"]
    assert la.match_contract(cs, "Northstar v2")["name"] == cs[0]["name"]
    assert la.match_contract(cs, "Contoso deal") is None


def test_unknown_contract():
    out = la.review_contract(la.LocalDocs(), "nope", FakeBedrock())
    assert "error" in out and len(out["available"]) == 2


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)}/{len(tests)} passed")
