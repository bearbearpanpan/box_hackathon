"""
check_config.py — preflight connectivity + credential check.

Run this on a machine with real credentials BEFORE a demo to confirm Box and
Bedrock are actually reachable, instead of discovering a bad key live. It makes
one tiny real call to each service when configured, and prints a clear report.
Degrades gracefully: if a service isn't configured it says so and the demo can
still run in offline/deterministic mode.

Usage:
    python3 agent/lambda/tools/check_config.py
    (or)  python3 agent/lambda/handler.py check-config
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envload  # noqa: E402

OK = "\u2705"      # white check
WARN = "\u26a0\ufe0f"  # warning
X = "\u274c"       # cross


def _check_env() -> dict:
    envload.load_env()
    box = all(os.environ.get(k) for k in ("BOX_CLIENT_ID", "BOX_CLIENT_SECRET", "BOX_ENTERPRISE_ID"))
    aws_region = os.environ.get("AWS_REGION")
    bedrock_model = os.environ.get("BEDROCK_MODEL_ID")
    aws_creds = bool(
        os.environ.get("AWS_ACCESS_KEY_ID")
        or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        or os.path.exists(os.path.expanduser("~/.aws/credentials"))
    )
    return {
        "box_configured": box,
        "aws_region": aws_region,
        "bedrock_model": bedrock_model,
        "aws_creds_present": aws_creds,
    }


def _check_boto3() -> bool:
    try:
        import boto3  # noqa: F401
        return True
    except Exception:
        return False


def _check_bedrock(region: str, model_id: str) -> tuple[bool, str]:
    try:
        import json
        import boto3
        client = boto3.client("bedrock-runtime", region_name=region)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "ping"}],
        }
        resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
        json.loads(resp["body"].read())
        return True, "model responded"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_box() -> tuple[bool, str]:
    try:
        box_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "box"))
        sys.path.insert(0, box_dir)
        from box_client import BoxClient
        c = BoxClient()
        files = c.list_contracts()
        return True, f"listed {len(files)} file(s) in contracts folder"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def run() -> dict:
    env = _check_env()
    report = {"checks": [], "mode": "offline"}

    def line(status, label, detail=""):
        report["checks"].append({"status": status, "label": label, "detail": detail})

    # --- Box ---
    if env["box_configured"]:
        if _check_boto3() or True:  # box uses boxsdk, checked inside
            ok, detail = _check_box()
            line(OK if ok else X, "Box API", detail)
        report["box"] = env["box_configured"]
    else:
        line(WARN, "Box API", "not configured -> using local manifest.json (offline)")

    # --- Bedrock ---
    if env["aws_region"] and env["bedrock_model"]:
        if not _check_boto3():
            line(X, "AWS Bedrock", "boto3 not installed -> run: pip install boto3")
        elif not env["aws_creds_present"]:
            line(X, "AWS Bedrock",
                 "no AWS credentials found -> set AWS_BEARER_TOKEN_BEDROCK, "
                 "export AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, or run: aws configure")
        else:
            ok, detail = _check_bedrock(env["aws_region"], env["bedrock_model"])
            line(OK if ok else X, "AWS Bedrock", detail)
    else:
        line(WARN, "AWS Bedrock",
             "AWS_REGION/BEDROCK_MODEL_ID not set -> using deterministic fallback (offline)")

    # overall mode
    has_live = any(c["status"] == OK for c in report["checks"])
    report["mode"] = "live" if has_live else "offline (fully functional for demo)"
    return report


def main():
    rep = run()
    print()
    print("  Reality Check — configuration preflight")
    print("  " + "-" * 46)
    for c in rep["checks"]:
        print(f"  {c['status']}  {c['label']:<14} {c['detail']}")
    print("  " + "-" * 46)
    print(f"  Mode: {rep['mode']}")
    print()
    if rep["mode"].startswith("offline"):
        print("  Note: the full demo (python3 demo.py) runs end-to-end in offline")
        print("  mode. Live Box/Bedrock only enrich extraction + narrative text.")
        print()


if __name__ == "__main__":
    main()
