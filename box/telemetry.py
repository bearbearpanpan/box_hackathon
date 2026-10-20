"""
telemetry.py — shared, dependency-free observability for Reality Check.

Why this exists
---------------
Before this module the codebase had zero logging: the Lambda router, the Box
client, and the Bedrock call all ran silently, exceptions were swallowed, and
external calls were untimed. This adds structured logs, latency timing, and
CloudWatch-friendly metrics across the three trust boundaries
(Bedrock -> Lambda, Lambda -> Box, Lambda -> Bedrock) and the agentic loop KPIs.

Design constraints (so nothing breaks):
  * Standard library only — works in the offline sandbox and in Lambda with no
    extra dependencies. Safe to import even when boto3/boxsdk are absent.
  * Opt-in verbosity via LOG_LEVEL (default INFO). Set LOG_LEVEL=WARNING to
    quiet it, or DEBUG for full detail. Never changes any function's return
    value or control flow.
  * Logs go to stderr so they never corrupt stdout (the CLI prints JSON results
    to stdout; the demo prints narration). In Lambda, stderr is captured by
    CloudWatch Logs automatically.
  * Secrets are never logged. A redaction helper scrubs known-sensitive keys.

Public surface:
  get_logger(name)                     -> stdlib Logger with JSON formatting
  log_event(logger, event, **fields)   -> one structured log line
  timed(logger, op, **fields)          -> context manager; logs op + duration_ms
  emit_metric(name, value, unit, **d)  -> CloudWatch EMF metric line (metrics=on)
  redact(mapping)                      -> copy with sensitive values masked
  new_request_id()                     -> correlation id for a run
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

# One correlation id per logical request/run. Set once at an entry point and
# every log line emitted anywhere in the call stack is stamped with it
# automatically — so a single request is traceable end-to-end across loggers.
_REQUEST_ID: ContextVar[Optional[str]] = ContextVar("rc_request_id", default=None)

# Keys whose values must never appear in logs (case-insensitive substring match).
_SENSITIVE = (
    "secret", "token", "password", "client_secret", "authorization",
    "api_key", "apikey", "access_key", "session_token", "credential",
)

# CloudWatch EMF namespace for metrics.
_METRIC_NAMESPACE = os.environ.get("TELEMETRY_METRIC_NAMESPACE", "RealityCheck")


def _metrics_enabled() -> bool:
    """EMF metrics are emitted when EMIT_METRICS is truthy. Off by default so
    local/CLI output stays clean; turn on in Lambda to get CloudWatch metrics."""
    return os.environ.get("EMIT_METRICS", "false").strip().lower() in ("1", "true", "yes", "on")


# In-process capture buffer for tests. When not None, every emit_metric() call
# appends a record here regardless of EMIT_METRICS. Production code never
# enables this; only the integration test does, via capture_metrics().
_CAPTURE: Optional[list] = None


class _MetricCapture:
    """Context manager that records metrics emitted inside the block.

        with capture_metrics() as cap:
            run_pipeline()
        assert cap.count("WorkflowRun", status="converged") == 1

    This does not change whether EMF is written to the stream; it only observes,
    so the same code path a Lambda runs is exercised by the test.
    """

    def __init__(self) -> None:
        self.records: list = []

    def __enter__(self) -> "_MetricCapture":
        global _CAPTURE
        self.records = []
        _CAPTURE = self.records
        return self

    def __exit__(self, *exc) -> None:
        global _CAPTURE
        _CAPTURE = None

    def names(self) -> set:
        return {r["name"] for r in self.records}

    def count(self, name: str, **dims: Any) -> int:
        """How many times `name` was emitted with (at least) the given dims."""
        want = {str(k): str(v) for k, v in dims.items()}
        return sum(
            1 for r in self.records
            if r["name"] == name
            and all(r["dimensions"].get(k) == v for k, v in want.items())
        )

    def total(self, name: str, **dims: Any) -> float:
        """Summed value of `name` over matching emissions."""
        want = {str(k): str(v) for k, v in dims.items()}
        return sum(
            r["value"] for r in self.records
            if r["name"] == name
            and all(r["dimensions"].get(k) == v for k, v in want.items())
        )


def capture_metrics() -> _MetricCapture:
    """Return a context manager that records emit_metric() calls for assertions.
    Intended for tests only."""
    return _MetricCapture()


class _JsonFormatter(logging.Formatter):
    """Render each record as a single compact JSON object. Any extra fields
    attached via `extra={"fields": {...}}` are merged into the top level."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_CONFIGURED: Dict[str, logging.Logger] = {}


def get_logger(name: str = "reality_check") -> logging.Logger:
    """Return a process-wide logger that writes JSON to stderr. Idempotent:
    repeated calls reuse the same handler so logs aren't duplicated."""
    if name in _CONFIGURED:
        return _CONFIGURED[name]

    logger = logging.getLogger(name)
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))

    # Avoid adding duplicate handlers if the root/Lambda runtime already added
    # one, and keep our records from propagating into a differently-formatted
    # root handler.
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_rc_telemetry", False)
               for h in logger.handlers):
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(_JsonFormatter())
        handler._rc_telemetry = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = False

    _CONFIGURED[name] = logger
    return logger


def redact(mapping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a shallow copy with sensitive values masked. Non-dict input and
    None are handled gracefully so callers never need a guard."""
    if not isinstance(mapping, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in mapping.items():
        key_l = str(k).lower()
        if any(s in key_l for s in _SENSITIVE):
            out[k] = "***redacted***"
        elif isinstance(v, dict):
            out[k] = redact(v)
        else:
            out[k] = v
    return out


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO,
              **fields: Any) -> None:
    """Emit one structured line. `event` is the message; `fields` become JSON
    keys. Sensitive values are redacted. The current correlation id (if set) is
    stamped as `request_id` on every line unless the caller passed its own."""
    merged = dict(fields)
    rid = _REQUEST_ID.get()
    if rid and "request_id" not in merged:
        merged["request_id"] = rid
    logger.log(level, event, extra={"fields": redact(merged)})


def new_request_id() -> str:
    """A short correlation id to thread through one logical run."""
    return f"rc-{uuid.uuid4().hex[:12]}"


def set_request_id(request_id: Optional[str] = None) -> str:
    """Bind a correlation id to the current context (and everything it calls).
    Call once at an entry point; downstream log_event() lines pick it up
    automatically. Pass None to generate a fresh id. Returns the id."""
    rid = request_id or new_request_id()
    _REQUEST_ID.set(rid)
    return rid


def get_request_id() -> Optional[str]:
    """The correlation id bound to the current context, if any."""
    return _REQUEST_ID.get()


@contextmanager
def timed(logger: logging.Logger, op: str, level: int = logging.INFO,
          **fields: Any) -> Iterator[Dict[str, Any]]:
    """Context manager that times a block and logs start/finish with
    duration_ms. On exception it logs the failure (with duration) and re-raises
    so behavior is unchanged. Yields a dict you can add fields to before exit.

        with timed(log, "box.ai_ask", file_id=fid) as span:
            answer = do_call()
            span["answer_len"] = len(answer)
    """
    extra: Dict[str, Any] = {}
    start = time.perf_counter()
    log_event(logger, f"{op}.start", level=level, **fields)
    try:
        yield extra
    except Exception as exc:  # log then re-raise — we never swallow here
        dur = round((time.perf_counter() - start) * 1000, 1)
        log_event(logger, f"{op}.error", level=logging.ERROR,
                  duration_ms=dur, error=str(exc), error_type=type(exc).__name__,
                  **fields, **extra)
        raise
    else:
        dur = round((time.perf_counter() - start) * 1000, 1)
        log_event(logger, f"{op}.ok", level=level, duration_ms=dur, **fields, **extra)


def _in_lambda() -> bool:
    """True when running inside AWS Lambda (the runtime sets this env var)."""
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _metric_stream():
    """Where EMF lines go.

    In Lambda, CloudWatch Logs parses EMF from *stdout* — so metrics must go
    there to be auto-extracted. Locally (CLI/demo) stdout carries the JSON
    result the user reads, so we send EMF to stderr instead to avoid corrupting
    it. Either way the metric is still a structured line you can grep.
    """
    return sys.stdout if _in_lambda() else sys.stderr


def emit_metric(name: str, value: float, unit: str = "Count",
                **dimensions: Any) -> None:
    """Emit a CloudWatch EMF metric line when EMIT_METRICS is on. EMF lets
    CloudWatch Logs auto-extract metrics with no extra API calls. No-op
    otherwise, so it's safe to sprinkle liberally.

    Stream selection (stdout in Lambda, stderr locally) keeps CloudWatch metric
    extraction working without polluting local CLI JSON output.
    """
    dims = {str(k): str(v) for k, v in dimensions.items()}

    # Test observability hook: record the emission regardless of EMIT_METRICS so
    # integration tests can assert on it without parsing streams. No-op in prod.
    if _CAPTURE is not None:
        _CAPTURE.append({"name": name, "value": value, "unit": unit,
                         "dimensions": dims})

    if not _metrics_enabled():
        return
    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": _METRIC_NAMESPACE,
                "Dimensions": [list(dims.keys())] if dims else [[]],
                "Metrics": [{"Name": name, "Unit": unit}],
            }],
        },
        name: value,
        **dims,
    }
    _metric_stream().write(json.dumps(emf, default=str) + "\n")
