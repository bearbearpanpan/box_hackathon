import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_agent as la  # noqa: E402

CANNED = [
    {"location": "Section 1", "claim": "encryption at rest", "result": "No risk", "risk_category": "None",
     "evidence_ref": "B1", "evidence_passage": "Encryption at rest: supported", "explanation": "matches"},
    {"location": "Section 4", "claim": "10 GB/s", "result": "Risk identified", "risk_category": "Performance commitment",
     "evidence_ref": "B1", "evidence_passage": "5 GB/s", "explanation": "exceeds benchmark"},
    {"location": "Section 5", "claim": "LegacyVault", "result": "No source found", "risk_category": "None",
     "evidence_ref": "", "evidence_passage": "", "explanation": "nothing found"},
    {"location": "Section 3", "claim": "30 days", "result": "Risk identified", "risk_category": "Delivery deadline",
     "evidence_ref": "B3", "evidence_passage": "58-72 days", "explanation": "too fast"},
    {"location": "Section 2", "claim": "Smart Archive Search", "result": "Risk identified",
     "risk_category": "Feature availability", "evidence_ref": "B2", "evidence_passage": "Exploratory",
     "explanation": "not available"},
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
    assert os.path.isfile(out["report_link"])


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
