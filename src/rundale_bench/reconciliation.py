"""Append-only, evidence-bound billing reconciliation for one published DNF."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .storage import safe_id


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _aware_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a timezone-aware timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a timezone-aware timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp")
    return result


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON evidence file: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def _append_json_once(path: Path, record: dict, *, under: Path) -> dict:
    """Create without replacement; accept only an identical concurrent/existing record."""
    encoded = json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        existing = _read_json(_regular_file(path, under=under))
        expected = dict(record, recorded_at=existing.get("recorded_at"))
        if existing != expected:
            raise ValueError("Billing reconciliation is append-only; conflicting record already exists")
        return existing
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(encoded)
        out.flush()
        os.fsync(out.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return record


def _regular_file(path: Path, *, under: Path | None = None) -> Path:
    if path.is_symlink():
        raise ValueError("Symlink evidence paths are not allowed")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Evidence path does not exist") from exc
    if not resolved.is_file():
        raise ValueError("Evidence path must be a regular file")
    if under is not None and not resolved.is_relative_to(under.resolve(strict=True)):
        raise ValueError("Run and ledger evidence must be inside the results directory")
    return resolved


def _validate_monitoring_evidence(evidence: dict, run_id: str, completed_at: str) -> None:
    if evidence.get("schema_version") != 1 or evidence.get("run_id") != run_id:
        raise ValueError("Monitoring evidence schema or run ID does not match")
    queries = evidence.get("queries")
    if not isinstance(queries, dict):
        raise ValueError("Provider monitoring queries are missing")
    finished = _aware_datetime(completed_at, "Published run completion time")
    earliest_possible_request = finished.timestamp() - 180
    query_end_times = []
    expected_filters = {
        "request_count": 'metric.type="serviceruntime.googleapis.com/api/request_count" AND resource.labels.service="generativelanguage.googleapis.com"',
        "output_tokens": 'metric.type="generativelanguage.googleapis.com/generate_content_usage_output_token_count"',
    }
    parsed_queries = {}
    for name, expected_filter in expected_filters.items():
        query = queries.get(name)
        if not isinstance(query, dict) or query.get("http_status") != 200 or query.get("pagination_complete") is not True:
            raise ValueError(f"{name} monitoring evidence is incomplete")
        params = query.get("parameters")
        if not isinstance(params, dict) or params.get("filter") != expected_filter or params.get("view") != "FULL":
            raise ValueError(f"{name} monitoring query is malformed")
        if not isinstance(params.get("pageSize"), int) or params["pageSize"] <= 0:
            raise ValueError(f"{name} monitoring query page size is invalid")
        start = _aware_datetime(params.get("interval.startTime"), f"{name} query start")
        end = _aware_datetime(params.get("interval.endTime"), f"{name} query end")
        if start >= end or start.timestamp() > earliest_possible_request or end < finished:
            raise ValueError(f"{name} query does not cover the inferred failure window")
        pages = query.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError(f"{name} monitoring pages are missing")
        for page in pages:
            if not isinstance(page, dict) or page.get("nextPageToken"):
                raise ValueError(f"{name} monitoring pagination is incomplete")
            if not isinstance(page.get("timeSeries", []), list):
                raise ValueError(f"{name} monitoring response is malformed")
        parsed_queries[name] = (query, start, end)
        query_end_times.append(end)

    if any(page.get("timeSeries") for page in parsed_queries["output_tokens"][0]["pages"]):
        raise ValueError("Output-token monitoring contradicts the not-billed conclusion")

    request, query_start, request_end = parsed_queries["request_count"]
    identity = evidence.get("identity_binding")
    if not isinstance(identity, dict) or identity.get("checked_locally") is not True or identity.get("independently_verified") is not False:
        raise ValueError("Monitoring identity limitations are missing")
    if identity.get("digest_scheme") != "hmac-sha256-over-identifier-sha256-private-key":
        raise ValueError("Monitoring identity tags require a private-key HMAC scheme")
    for key in ("key_resource_hmac_sha256", "described_project_id_hmac_sha256", "described_project_number_hmac_sha256"):
        value = identity.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("Monitoring identity hash binding is malformed")
    if identity.get("lookup_project_number_hmac_sha256") != identity.get("described_project_number_hmac_sha256"):
        raise ValueError("Monitoring project identity binding does not match")
    pages = request.get("pages")
    series_count = 0
    for page in pages:
        for series in page.get("timeSeries", []):
            series_count += 1
            if not isinstance(series, dict):
                raise ValueError("Request-count monitoring series is malformed")
            metric = series.get("metric", {})
            resource = series.get("resource", {})
            if not isinstance(metric, dict) or not isinstance(resource, dict):
                raise ValueError("Request-count monitoring series is malformed")
            if metric.get("type") != "serviceruntime.googleapis.com/api/request_count":
                raise ValueError("Unexpected metric in request-count evidence")
            resource_labels = resource.get("labels", {})
            metric_labels = metric.get("labels", {})
            if not isinstance(resource_labels, dict) or not isinstance(metric_labels, dict):
                raise ValueError("Request-count monitoring labels are malformed")
            if resource_labels.get("service") != "generativelanguage.googleapis.com":
                raise ValueError("Unexpected provider in request-count evidence")
            method = resource_labels.get("method")
            if method != "google.ai.generativelanguage.v1beta.ModelService.GetModel":
                raise ValueError("Monitoring evidence contains a generation request")
            if (resource_labels.get("credential_id") != f"hmac-sha256:{identity.get('key_resource_hmac_sha256')}"
                    or resource_labels.get("project_id") != f"hmac-sha256:{identity.get('described_project_id_hmac_sha256')}"):
                raise ValueError("Monitoring positive control is not bound to the checked key and project")
            points = series.get("points", [])
            if (not isinstance(points, list) or len(points) != 1 or metric_labels.get("response_code") != "200"
                    or metric_labels.get("grpc_status_code") != "0"):
                raise ValueError("Monitoring evidence lacks its successful positive control")
            point = points[0]
            if not isinstance(point, dict) or not isinstance(point.get("value"), dict):
                raise ValueError("Monitoring positive-control point is malformed")
            point_interval = point.get("interval")
            if not isinstance(point_interval, dict):
                raise ValueError("Monitoring positive-control interval is missing")
            point_start = _aware_datetime(point_interval.get("startTime"), "Positive-control start")
            point_end = _aware_datetime(point_interval.get("endTime"), "Positive-control end")
            if point_start >= point_end or point_start < query_start or point_end > request_end:
                raise ValueError("Monitoring positive control falls outside the queried interval")
            if point["value"].get("int64Value") != "1":
                raise ValueError("Monitoring positive control is malformed")
    if series_count != 1:
        raise ValueError("Monitoring evidence does not contain exactly one non-generating positive control")
    captured_at = _aware_datetime(evidence.get("captured_at"), "Monitoring capture time")
    if any(captured_at <= query_end for query_end in query_end_times):
        raise ValueError("Monitoring evidence was captured before query windows ended")
    if not any("not an invoice" in str(limit).lower() for limit in evidence.get("limitations", [])):
        raise ValueError("Monitoring limitations must disclose that this is not invoice evidence")


def append_monitoring_reconciliation(
    results: Path, run_id: str, ledger_export: Path, monitoring_evidence: Path,
) -> dict:
    """Validate source artifacts and create an immutable public reconciliation record.

    `results` is the results directory containing `<version>/runs` and `<version>/ledgers`.
    Existing identical-source records are returned unchanged; conflicting records fail closed.
    """
    rid = safe_id(run_id)
    root = results.resolve(strict=True)
    run_path = _regular_file(root / "3.0" / "runs" / f"{rid}.json", under=root)
    ledger_path = _regular_file(ledger_export, under=root)
    evidence_path = _regular_file(monitoring_evidence)
    run = _read_json(run_path)
    ledger = _read_json(ledger_path)
    evidence = _read_json(evidence_path)
    if run.get("run_id") != rid or run.get("version") != "3.0":
        raise ValueError("Published run identity does not match the requested reconciliation")
    if run.get("status") != "dnf" or run.get("failure_cause") != "unknown":
        raise ValueError("Only the targeted unknown-cause DNF can be reconciled")
    if run.get("budget_status") != "billing_uncertain" or not isinstance(run.get("spending_exposure_usd"), (int, float)) or run["spending_exposure_usd"] <= 0:
        raise ValueError("Run does not contain unresolved billing exposure")
    if run.get("cost_usd") != 0:
        raise ValueError("Run's original recorded cost does not match the audited case")
    if ledger.get("run_id") != rid or ledger.get("billing_reconciled") is not False:
        raise ValueError("Ledger export identity or original state does not match")
    source_ledger_hash = ledger.get("ledger_sha256")
    if not isinstance(source_ledger_hash, str) or len(source_ledger_hash) != 64 or any(c not in "0123456789abcdef" for c in source_ledger_hash):
        raise ValueError("Ledger export does not contain the original SQLite ledger hash")
    calls = ledger.get("calls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValueError("Ledger export does not match the single-call audited case")
    call = calls[0]
    if call.get("state") != "uncertain" or call.get("actual") is not None or call.get("reserved") != run["spending_exposure_usd"]:
        raise ValueError("Ledger export does not match the original uncertain reservation")
    _validate_monitoring_evidence(evidence, rid, run.get("completed_at"))

    record_path = root / "3.0" / "reconciliations" / f"{rid}.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    if not record_path.parent.resolve(strict=True).is_relative_to(root):
        raise ValueError("Reconciliation output must be inside the results directory")
    if record_path.is_symlink():
        raise ValueError("Reconciliation output cannot be a symlink")
    record = {
        "schema_version": 1,
        "run_id": rid,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "conclusion": "not_billed_based_on_provider_monitoring",
        "monitoring_estimate_usd": 0,
        "actual_cost_usd": None,
        "basis": "Provider request-count monitoring showed no generation request from the locally checked key and project in the window.",
        "limitations": [
            "This is a monitoring-based estimate, not an invoice or request-specific billing receipt.",
            "The original failure cause remains unknown; this reconciliation does not change it.",
            "Identity mapping was checked locally against private provider originals, not independently verified; the review received redacted records.",
            "Output-token absence is supporting evidence only and lacks a known-generation positive control.",
            "The run did not record request-start time. The lower bound for query coverage is inferred as recorded completion minus the adapter's 180-second per-operation socket timeout; it is not an observed start timestamp or a total-request deadline.",
            "Original run cost, budget status, spending exposure, run JSON, and ledger export remain unchanged.",
        ],
        "original_artifacts": {
            "run_sha256": _sha256(run_path),
            "ledger_export_sha256": _sha256(ledger_path),
            "source_sqlite_ledger_sha256": source_ledger_hash,
            "monitoring_evidence_sha256": _sha256(evidence_path),
            "monitoring_evidence_canonical_sha256": _canonical_sha256(evidence),
        },
        "monitoring_evidence": evidence,
    }
    return _append_json_once(record_path, record, under=root)
