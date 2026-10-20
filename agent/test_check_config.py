"""
Offline tests for check_config credential detection.

These exercise ONLY the pure env-inspection logic (_check_env) with env vars
toggled in-process. They never touch the network or make real AWS/Box calls,
so they are safe to run in CI and in the offline demo sandbox.

Run:
    python3 agent/lambda/tools/test_check_config.py        # standalone
    python3 -m pytest agent/lambda/tools/test_check_config.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import check_config

# Credential-ish env vars we flip during tests; snapshot + restore around each.
_CRED_KEYS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "BEDROCK_MODEL_ID",
)


def _clear_cred_env():
    for k in _CRED_KEYS:
        os.environ.pop(k, None)


def test_bearer_token_counts_as_credentials():
    saved = {k: os.environ.get(k) for k in _CRED_KEYS}
    try:
        _clear_cred_env()
        # Fake test fixture, not a real secret.
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = "test-bearer-token"  # nosec B105
        env = check_config._check_env()
        assert env["aws_creds_present"] is True, env
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_iam_access_key_still_counts():
    saved = {k: os.environ.get(k) for k in _CRED_KEYS}
    try:
        _clear_cred_env()
        os.environ["AWS_ACCESS_KEY_ID"] = "AKIAEXAMPLE"
        env = check_config._check_env()
        assert env["aws_creds_present"] is True, env
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
