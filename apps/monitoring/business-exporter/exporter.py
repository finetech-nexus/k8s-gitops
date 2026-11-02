#!/usr/bin/env python3
"""Export functional + technical business KPIs to Prometheus.

Sources:
  - Clarity (KYC funnel)
  - Elasticsearch logs-tn-* (perimeter volume / errors)
  - Elasticsearch zeebe-* (transfer rails by context + problems)
  - mt-api /api/transactions (card payments amount / status)
  - Elasticsearch keyword signals (top-up channels, subscriptions, card ops)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer

CLARITY_URL = os.environ.get("CLARITY_URL", "http://clarity-api.kyc-aml.svc.cluster.local:8000").rstrip("/")
CLARITY_USER = os.environ.get("CLARITY_USER", "admin")
CLARITY_PASSWORD = os.environ.get("CLARITY_PASSWORD", "password")
ES_URL = os.environ.get("ES_URL", "http://infra-elasticsearch.infra.svc.cluster.local:9200").rstrip("/")
ES_USER = os.environ.get("ES_USER", "elastic")
ES_PASSWORD = os.environ.get("ES_PASSWORD", "elasticSearchPas42")
MT_API_URL = os.environ.get("MT_API_URL", "http://core-api-mt-api.api.svc.cluster.local").rstrip("/")
SCRAPE_SECONDS = int(os.environ.get("SCRAPE_SECONDS", "60"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9105"))
WINDOW = os.environ.get("METRICS_WINDOW", "24h")


def _window_ms(window: str | None = None) -> int:
    """Convert 15m/24h/7d style windows to milliseconds lookback."""
    raw = (window or WINDOW).strip().lower()
    try:
        if raw.endswith("ms"):
            return max(int(raw[:-2]), 1000)
        if raw.endswith("s"):
            return max(int(raw[:-1]), 1) * 1000
        if raw.endswith("m"):
            return max(int(raw[:-1]), 1) * 60_000
        if raw.endswith("h"):
            return max(int(raw[:-1]), 1) * 3_600_000
        if raw.endswith("d"):
            return max(int(raw[:-1]), 1) * 86_400_000
        return int(raw)
    except ValueError:
        return 86_400_000


def _zeebe_time_range(window: str | None = None) -> dict:
    """Zeebe exporter stores timestamp as epoch millis (not a date field)."""
    gte = int(time.time() * 1000) - _window_ms(window)
    return {"range": {"timestamp": {"gte": gte}}}


# Funnel buckets for Grafana functional dashboard.
SUCCESS_STATUSES = {"approved", "approved-partially"}
STOPPED_STATUSES = {"rejected", "expired", "cancelled", "abandoned"}
IN_PROGRESS_STATUSES = {
    "draft",
    "collecting",
    "screening_pending",
    "in_review",
    "documents_requested",
    "remediation",
    "pending",
}

# BPMN process id prefix → (rail_context, direction, perimeter, family)
# context: nexus | local | international | card
# direction: inbound | outbound | internal
PROCESS_MAP: list[tuple[str, tuple[str, str, str, str]]] = [
    ("internal_transfer", ("nexus", "internal", "payments", "transfer")),
    ("sibtel_domestic_inbound_transfer", ("local", "inbound", "payments", "transfer")),
    ("sibtel_domestic_transfer", ("local", "outbound", "payments", "transfer")),
    ("swift_inbound_credit", ("international", "inbound", "payments", "transfer")),
    ("swift_international_transfer", ("international", "outbound", "payments", "transfer")),
    ("mt_inbound_authorization", ("card", "inbound", "payments", "card_auth")),
    ("mt_inbound_capture", ("card", "inbound", "payments", "card_capture")),
    ("mt_inbound_refund", ("card", "inbound", "payments", "card_refund")),
    ("mt_inbound_void", ("card", "inbound", "payments", "card_void")),
    ("mt_card_payment", ("card", "outbound", "payments", "card_payment")),
    ("mt-card-refund", ("card", "outbound", "payments", "card_refund")),
    ("party_registration", ("nexus", "internal", "payments", "party")),
]

_lock = threading.Lock()
_metrics: dict[str, float] = {}
_labels: dict[str, list[tuple[dict[str, str], float]]] = {}
_last_error = ""
_help_lines: list[str] = []


def _http_json(url: str, *, method: str = "GET", data: dict | None = None, headers: dict | None = None, auth: tuple[str, str] | None = None, timeout: int = 30):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode() or "{}"
        return json.loads(raw)


def _es(path: str, query: dict, timeout: int = 25) -> dict:
    return _http_json(
        f"{ES_URL}/{path}",
        method="POST",
        data=query,
        auth=(ES_USER, ES_PASSWORD),
        timeout=timeout,
    )


def _set_gauge(name: str, value: float, labels: dict[str, str] | None = None):
    if labels:
        _labels.setdefault(name, [])
        kept = [item for item in _labels[name] if item[0] != labels]
        kept.append((labels, float(value)))
        _labels[name] = kept
    else:
        _metrics[name] = float(value)


def _reset_series(*names: str):
    for name in names:
        _labels[name] = []


def _classify_process(bpmn: str) -> tuple[str, str, str, str, str]:
    """Return context, direction, perimeter, family, process_key."""
    raw = (bpmn or "unknown").strip()
    key = raw
    if key.endswith("-nexusbank"):
        key = key[: -len("-nexusbank")]
    # longest prefix wins
    for prefix, mapped in sorted(PROCESS_MAP, key=lambda x: len(x[0]), reverse=True):
        if key == prefix or key.startswith(prefix):
            ctx, direction, perimeter, family = mapped
            return ctx, direction, perimeter, family, key
    return "other", "unknown", "payments", "other", key or "unknown"


def scrape_clarity():
    login = _http_json(
        f"{CLARITY_URL}/api/clarity/v1/auth/login",
        method="POST",
        data={"email": CLARITY_USER, "password": CLARITY_PASSWORD},
    )
    token = login["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    dash = _http_json(f"{CLARITY_URL}/api/clarity/v1/dashboard", headers=headers)
    _set_gauge("clarity_customers", dash.get("customers", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_individuals", dash.get("individuals", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_businesses", dash.get("businesses", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_in_review", dash.get("in_review", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_kyc_sessions", dash.get("kyc_sessions", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_kyb_sessions", dash.get("kyb_sessions", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_open_alerts", dash.get("open_alerts", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_open_cases", dash.get("open_cases", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_open_tasks", dash.get("open_tasks", 0), {"perimeter": "kyc"})
    _set_gauge("clarity_transactions", dash.get("transactions", 0), {"perimeter": "kyc"})

    status_counts: Counter[str] = Counter()
    kyc_status_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    offset = 0
    while True:
        page = _http_json(
            f"{CLARITY_URL}/api/clarity/v1/customers?limit=200&offset={offset}",
            headers=headers,
        )
        items = page.get("items") or []
        if not items:
            break
        for row in items:
            status = str(row.get("status") or "unknown")
            kyc_st = str(row.get("kyc_status") or "unknown")
            kind = str(row.get("kind") or "unknown")
            status_counts[status] += 1
            kyc_status_counts[kyc_st] += 1
            kind_counts[kind] += 1
        offset += len(items)
        if offset >= int(page.get("total") or offset):
            break
        if offset > 5000:
            break

    _reset_series(
        "clarity_customers_by_status",
        "clarity_customers_by_kyc_progress",
        "clarity_customers_by_kind",
        "clarity_users_funnel",
    )
    for status, count in status_counts.items():
        _set_gauge("clarity_customers_by_status", count, {"perimeter": "kyc", "status": status})
    for status, count in kyc_status_counts.items():
        _set_gauge("clarity_customers_by_kyc_progress", count, {"perimeter": "kyc", "kyc_status": status})
    for kind, count in kind_counts.items():
        _set_gauge("clarity_customers_by_kind", count, {"perimeter": "kyc", "kind": kind})

    success = sum(status_counts.get(s, 0) for s in SUCCESS_STATUSES)
    stopped = sum(status_counts.get(s, 0) for s in STOPPED_STATUSES)
    for s in ("expired", "abandoned", "cancelled"):
        if status_counts.get(s, 0) == 0:
            stopped += kyc_status_counts.get(s, 0)
    in_progress = sum(status_counts.get(s, 0) for s in IN_PROGRESS_STATUSES)
    other = max(0, sum(status_counts.values()) - success - stopped - in_progress)

    _set_gauge("clarity_users_funnel", success, {"perimeter": "kyc", "stage": "created_success"})
    _set_gauge("clarity_users_funnel", stopped, {"perimeter": "kyc", "stage": "stopped"})
    _set_gauge("clarity_users_funnel", in_progress, {"perimeter": "kyc", "stage": "in_progress"})
    _set_gauge("clarity_users_funnel", other, {"perimeter": "kyc", "stage": "other"})
    _set_gauge("clarity_users_funnel", sum(status_counts.values()), {"perimeter": "kyc", "stage": "total"})


def scrape_es_functional_logs():
    """Log volume by perimeter / namespace / level over the last 15m."""
    query = {
        "size": 0,
        "query": {"range": {"@timestamp": {"gte": "now-15m"}}},
        "aggs": {
            "by_perimeter": {"terms": {"field": "functional_perimeter", "size": 20, "missing": "unknown"}},
            "by_ns": {"terms": {"field": "k8s_namespace_name", "size": 40}},
            "by_level": {"terms": {"field": "level", "size": 10, "missing": "unknown"}},
            "errors": {
                "filter": {"terms": {"level": ["error", "fatal", "ERROR", "FATAL"]}},
                "aggs": {"by_ns": {"terms": {"field": "k8s_namespace_name", "size": 30}}},
            },
        },
    }
    try:
        res = _es("logs-tn-*/_search", query, timeout=20)
    except Exception:
        return
    _reset_series("logs_events_15m", "logs_events_15m_by_ns", "logs_events_15m_by_level", "logs_errors_15m_by_ns")
    aggs = res.get("aggregations", {})
    for bucket in aggs.get("by_perimeter", {}).get("buckets", []):
        _set_gauge(
            "logs_events_15m",
            bucket.get("doc_count", 0),
            {"perimeter": str(bucket.get("key") or "unknown"), "source": "logs-tn"},
        )
    for bucket in aggs.get("by_ns", {}).get("buckets", []):
        _set_gauge(
            "logs_events_15m_by_ns",
            bucket.get("doc_count", 0),
            {"namespace": str(bucket.get("key") or "unknown"), "source": "logs-tn"},
        )
    for bucket in aggs.get("by_level", {}).get("buckets", []):
        _set_gauge(
            "logs_events_15m_by_level",
            bucket.get("doc_count", 0),
            {"level": str(bucket.get("key") or "unknown"), "source": "logs-tn"},
        )
    for bucket in aggs.get("errors", {}).get("by_ns", {}).get("buckets", []):
        _set_gauge(
            "logs_errors_15m_by_ns",
            bucket.get("doc_count", 0),
            {"namespace": str(bucket.get("key") or "unknown"), "source": "logs-tn"},
        )


def _field_candidates(*names: str) -> list[str]:
    out: list[str] = []
    for n in names:
        out.append(n)
        if not n.endswith(".keyword"):
            out.append(f"{n}.keyword")
    return out


def _rewrite_must_fields(must: list, mapping: dict[str, str]) -> list:
    out = []
    for clause in must:
        cloned = json.loads(json.dumps(clause))
        for kind in ("term", "terms"):
            if kind in cloned:
                key = next(iter(cloned[kind].keys()))
                if key in mapping:
                    cloned[kind] = {mapping[key]: cloned[kind][key]}
        out.append(cloned)
    return out


def _terms_agg_first_working(
    index: str,
    query_must: list,
    field_candidates: list[str],
    size: int = 40,
    must_field_variants: list[dict[str, str]] | None = None,
) -> list[dict]:
    """Try keyword/non-keyword field variants until one aggregation returns."""
    last_err = None
    variants = must_field_variants or [{}]
    for variant in variants:
        must = _rewrite_must_fields(query_must, variant) if variant else query_must
        for field in field_candidates:
            try:
                res = _es(
                    f"{index}/_search",
                    {
                        "size": 0,
                        "query": {"bool": {"must": must}},
                        "aggs": {"t": {"terms": {"field": field, "size": size}}},
                    },
                )
                return res.get("aggregations", {}).get("t", {}).get("buckets", [])
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
    if last_err:
        raise last_err
    return []


def scrape_zeebe_transfers():
    """Transfer / card rails from Zeebe process instances + job problems."""
    series = (
        "payment_ops_count",
        "payment_ops_problems",
        "payment_ops_by_process",
        "payment_job_problems",
    )
    _reset_series(*series)

    intent_variants = [
        {},
        {"intent": "intent.keyword", "value.bpmnElementType": "value.bpmnElementType.keyword"},
    ]
    # Prefer broad zeebe-* then typed indices; keyword fields first (TN mapping).
    indices = ["zeebe-*", "zeebe-record_process-instance*", "zeebe-record_process-instance-creation*"]
    bpmn_fields = _field_candidates("value.bpmnProcessId")
    # keyword first
    bpmn_fields = sorted(bpmn_fields, key=lambda f: (0 if f.endswith(".keyword") else 1, f))

    # Completed + failed root process instances in window
    outcomes = {
        "completed": ["ELEMENT_COMPLETED"],
        "failed": ["ELEMENT_TERMINATED"],
        "activated": ["ELEMENT_ACTIVATED"],
    }
    for outcome, intents in outcomes.items():
        must = [
            {"terms": {"intent": intents}},
            {"term": {"value.bpmnElementType": "PROCESS"}},
            _zeebe_time_range(),
        ]
        buckets: list[dict] = []
        # Fallback without bpmnElementType filter (mapping differences across Zeebe record types).
        must_loose = [
            {"terms": {"intent": intents}},
            _zeebe_time_range(),
        ]
        for must_try in (must, must_loose):
            for index in indices:
                try:
                    buckets = _terms_agg_first_working(
                        index,
                        must_try,
                        bpmn_fields,
                        size=40,
                        must_field_variants=intent_variants,
                    )
                except Exception:
                    buckets = []
                if buckets:
                    break
            if buckets:
                break
        for bucket in buckets:
            bpmn = str(bucket.get("key") or "unknown")
            ctx, direction, perimeter, family, process = _classify_process(bpmn)
            count = float(bucket.get("doc_count") or 0)
            labels = {
                "perimeter": perimeter,
                "context": ctx,
                "direction": direction,
                "family": family,
                "process": process,
                "outcome": outcome,
                "window": WINDOW,
            }
            _set_gauge("payment_ops_by_process", count, labels)
            rollup = {
                "perimeter": perimeter,
                "context": ctx,
                "direction": direction,
                "family": family,
                "outcome": outcome,
                "window": WINDOW,
            }
            existing = 0.0
            for lab, val in _labels.get("payment_ops_count", []):
                if lab == rollup:
                    existing = val
                    break
            _set_gauge("payment_ops_count", existing + count, rollup)

    # Job failures / timeouts → operational problems
    must_jobs = [
        {"terms": {"intent": ["FAILED", "TIMED_OUT", "ERROR_THROWN"]}},
        _zeebe_time_range(),
    ]
    job_indices = ["zeebe-*", "zeebe-record_job*"]
    by_bpmn: list[dict] = []
    for index in job_indices:
        try:
            by_bpmn = _terms_agg_first_working(
                index,
                must_jobs,
                bpmn_fields,
                size=40,
                must_field_variants=intent_variants,
            )
        except Exception:
            by_bpmn = []
        if by_bpmn:
            break
    for bucket in by_bpmn:
        bpmn = str(bucket.get("key") or "unknown")
        ctx, direction, perimeter, family, process = _classify_process(bpmn)
        _set_gauge(
            "payment_ops_problems",
            float(bucket.get("doc_count") or 0),
            {
                "perimeter": perimeter,
                "context": ctx,
                "direction": direction,
                "family": family,
                "process": process,
                "problem": "job_failed_or_timeout",
                "window": WINDOW,
            },
        )

    type_fields = sorted(_field_candidates("value.type"), key=lambda f: (0 if f.endswith(".keyword") else 1, f))
    by_type: list[dict] = []
    for index in job_indices:
        try:
            by_type = _terms_agg_first_working(
                index,
                must_jobs,
                type_fields,
                size=40,
                must_field_variants=intent_variants,
            )
        except Exception:
            by_type = []
        if by_type:
            break
    for bucket in by_type:
        job_type = str(bucket.get("key") or "unknown")
        _set_gauge(
            "payment_job_problems",
            float(bucket.get("doc_count") or 0),
            {
                "perimeter": "payments",
                "job_type": job_type,
                "problem": "failed_or_timeout",
                "window": WINDOW,
            },
        )

    # Intent breakdown for problem severity
    intent_fields = sorted(_field_candidates("intent"), key=lambda f: (0 if f.endswith(".keyword") else 1, f))
    by_intent: list[dict] = []
    for index in job_indices:
        try:
            by_intent = _terms_agg_first_working(
                index,
                [_zeebe_time_range()],
                intent_fields,
                size=20,
            )
        except Exception:
            by_intent = []
        if by_intent:
            break
    _reset_series("payment_zeebe_intent_count")
    for bucket in by_intent:
        intent = str(bucket.get("key") or "unknown")
        _set_gauge(
            "payment_zeebe_intent_count",
            float(bucket.get("doc_count") or 0),
            {"perimeter": "payments", "intent": intent, "window": WINDOW},
        )


def _parse_amount(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def scrape_mt_card_payments():
    """Card payment amounts from mt-api console (unauthenticated in TN sandbox)."""
    series = (
        "card_payment_count",
        "card_payment_amount",
        "card_payment_amount_max",
        "card_payment_problems",
    )
    _reset_series(*series)

    counts: Counter[tuple] = Counter()
    amounts: defaultdict[tuple, float] = defaultdict(float)
    maxima: dict[tuple, float] = {}
    problems: Counter[tuple] = Counter()
    total = 0
    page = 0
    page_size = 100
    max_pages = 50  # cap scrape

    while page < max_pages:
        try:
            data = _http_json(
                f"{MT_API_URL}/api/transactions?page={page}&size={page_size}",
                timeout=20,
            )
        except Exception:
            _set_gauge("card_payment_scrape_up", 0, {"perimeter": "payments", "source": "mt-api"})
            return
        content = data.get("content") if isinstance(data, dict) else None
        if content is None and isinstance(data, list):
            content = data
        if not content:
            break
        for row in content:
            direction = str(row.get("direction") or "unknown").lower()
            operation = str(row.get("operation") or "unknown").lower()
            status = str(row.get("status") or "unknown").lower()
            currency = str(row.get("currency") or "UNK").upper()
            amount = _parse_amount(row.get("amount"))
            key = (direction, operation, status, currency)
            counts[key] += 1
            amounts[key] += amount
            maxima[key] = max(maxima.get(key, 0.0), amount)
            total += 1
            # problem heuristics (voided/refunded/issued with 00 are normal lifecycle states)
            bad_status = status in {"failed", "declined", "error", "rejected"}
            bad_code = (
                row.get("responseCode")
                and str(row.get("responseCode")) not in {"00", "000", "0", "None", "null", ""}
                and status not in {
                    "authorized",
                    "captured",
                    "approved",
                    "success",
                    "completed",
                    "settled",
                    "refunded",
                    "issued",
                    "pending",
                }
            )
            if bad_status or bad_code:
                problems[(direction, operation, status, currency, str(row.get("responseCode") or "unknown"))] += 1
        total_pages = int(data.get("totalPages") or 0) if isinstance(data, dict) else 0
        page += 1
        if total_pages and page >= total_pages:
            break
        if len(content) < page_size:
            break

    _set_gauge("card_payment_scrape_up", 1, {"perimeter": "payments", "source": "mt-api"})
    _set_gauge("card_payment_total", float(total), {"perimeter": "payments", "source": "mt-api"})

    for (direction, operation, status, currency), count in counts.items():
        labels = {
            "perimeter": "payments",
            "context": "card",
            "direction": direction,
            "operation": operation,
            "status": status,
            "currency": currency,
            "source": "mt-api",
        }
        _set_gauge("card_payment_count", float(count), labels)
        _set_gauge("card_payment_amount", amounts[(direction, operation, status, currency)], labels)
        _set_gauge("card_payment_amount_max", maxima.get((direction, operation, status, currency), 0.0), labels)

    for (direction, operation, status, currency, code), count in problems.items():
        _set_gauge(
            "card_payment_problems",
            float(count),
            {
                "perimeter": "payments",
                "context": "card",
                "direction": direction,
                "operation": operation,
                "status": status,
                "currency": currency,
                "response_code": code,
                "source": "mt-api",
            },
        )


def scrape_zeebe_transfer_amounts():
    """Best-effort amount sums from Zeebe variables named amount / transactionAmount."""
    _reset_series("transfer_amount_samples", "transfer_amount_sum_approx")
    # Pull recent amount variables; classify via linked process instance when possible.
    try:
        res = _es(
            "zeebe-record_variable*/_search",
            {
                "size": 200,
                "sort": [{"timestamp": {"order": "desc"}}],
                "query": {
                    "bool": {
                        "must": [
                            _zeebe_time_range(),
                            {
                                "bool": {
                                    "should": [
                                        {"term": {"value.name": "amount"}},
                                        {"term": {"value.name.keyword": "amount"}},
                                        {"term": {"value.name": "transactionAmount"}},
                                        {"term": {"value.name.keyword": "transactionAmount"}},
                                        {"wildcard": {"value.name": "*Amount*"}},
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                        ]
                    }
                },
                "_source": ["value.name", "value.value", "value.processInstanceKey", "value.bpmnProcessId", "intent"],
            },
            timeout=30,
        )
    except Exception:
        return

    sums: defaultdict[tuple, float] = defaultdict(float)
    counts: Counter[tuple] = Counter()
    for hit in res.get("hits", {}).get("hits", []):
        src = hit.get("_source") or {}
        value = src.get("value") or {}
        raw = value.get("value")
        amount = None
        if isinstance(raw, (int, float)):
            amount = float(raw)
        elif isinstance(raw, str):
            raw_s = raw.strip().strip('"')
            # JSON object with amount field
            if raw_s.startswith("{"):
                try:
                    obj = json.loads(raw_s)
                    amount = _parse_amount(obj.get("amount") or obj.get("value") or obj.get("transactionAmount"))
                except Exception:
                    amount = None
            else:
                # plain number or "10.5 TND"
                m = re.search(r"[-+]?\d+(?:\.\d+)?", raw_s.replace(",", ""))
                amount = float(m.group(0)) if m else None
        if amount is None:
            continue
        bpmn = str(value.get("bpmnProcessId") or src.get("bpmnProcessId") or "unknown")
        ctx, direction, perimeter, family, process = _classify_process(bpmn)
        if process == "unknown" and bpmn == "unknown":
            # unclassified sample — still count under payments/other
            ctx, direction, perimeter, family, process = "other", "unknown", "payments", "transfer", "unlinked"
        key = (ctx, direction, perimeter, family, process)
        sums[key] += amount
        counts[key] += 1

    for key, total in sums.items():
        ctx, direction, perimeter, family, process = key
        labels = {
            "perimeter": perimeter,
            "context": ctx,
            "direction": direction,
            "family": family,
            "process": process,
            "window": WINDOW,
            "source": "zeebe-variable",
        }
        _set_gauge("transfer_amount_sum_approx", total, labels)
        _set_gauge("transfer_amount_samples", float(counts[key]), labels)


def scrape_product_signals_from_logs():
    """Top-up / subscription / card product signals + problems from application logs."""
    series = (
        "product_ops_events",
        "product_ops_problems",
        "topup_events",
        "subscription_events",
    )
    _reset_series(*series)

    filters = {
        "topup_stripe": {
            "perimeter": "api",
            "product": "topup",
            "channel": "stripe",
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase": {"message": "create-topup"}},
                        {"match_phrase": {"message": "POST /api/stripe/create-topup"}},
                        {"match_phrase": {"message": "Stripe create-topup"}},
                        {"match_phrase": {"message": "payment_intent"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        },
        "topup_telecom": {
            "perimeter": "api",
            "product": "topup",
            "channel": "telecom",
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase": {"message": "telecom recharge"}},
                        {"match_phrase": {"message": "TOPUP-"}},
                        {"match_phrase": {"message": "TelecomRecharge"}},
                        {
                            "bool": {
                                "must": [
                                    {"wildcard": {"k8s_pod_name": "*produit*"}},
                                    {"match_phrase": {"message": "recharge"}},
                                ]
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            },
        },
        "subscription": {
            "perimeter": "api",
            "product": "subscription",
            "channel": "subscription-api",
            "query": {
                "bool": {
                    "should": [
                        {"wildcard": {"k8s_pod_name": "*subscription*"}},
                        {"match_phrase": {"message": "productType"}},
                        {"match_phrase": {"message": "BANK_PLAN"}},
                        {"match_phrase": {"message": "CreateSubscription"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        },
        "card_mgmt": {
            "perimeter": "api",
            "product": "card",
            "channel": "card-management",
            "query": {
                "bool": {
                    "should": [
                        {"wildcard": {"k8s_pod_name": "*card-management*"}},
                        {"match_phrase": {"message": "LIMIT_DAILY_AMOUNT"}},
                        {"match_phrase": {"message": "CardUseDecision"}},
                        {"match_phrase": {"message": "/api/cards"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        },
        "card_payment_api": {
            "perimeter": "payments",
            "product": "card",
            "channel": "mt-api",
            "query": {
                "bool": {
                    "should": [
                        {"wildcard": {"k8s_pod_name": "*mt-api*"}},
                        {"match_phrase": {"message": "AUTHORIZATION"}},
                        {"match_phrase": {"message": "CAPTURE"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        },
    }

    # Subscription product types hinted in logs
    type_filters = {
        "BANK_PLAN": "BANK_PLAN",
        "INSURANCE": "INSURANCE",
        "AUTO": "AUTO",
        "TELECOM": "TELECOM",
        "PRODUCT": "PRODUCT",
    }

    for name, cfg in filters.items():
        must = [{"range": {"@timestamp": {"gte": f"now-{WINDOW}"}}}, cfg["query"]]
        try:
            res = _es(
                "logs-tn-*/_search",
                {
                    "size": 0,
                    "query": {"bool": {"must": must}},
                    "aggs": {
                        "errors": {
                            "filter": {"terms": {"level": ["error", "fatal", "ERROR", "FATAL"]}},
                        }
                    },
                },
            )
        except Exception:
            continue
        total = float((res.get("hits") or {}).get("total", {}).get("value") or 0)
        # ES may return total as int on older clusters
        if isinstance((res.get("hits") or {}).get("total"), int):
            total = float(res["hits"]["total"])
        err = float(res.get("aggregations", {}).get("errors", {}).get("doc_count") or 0)
        labels = {
            "perimeter": cfg["perimeter"],
            "product": cfg["product"],
            "channel": cfg["channel"],
            "signal": name,
            "window": WINDOW,
            "source": "logs-tn",
        }
        _set_gauge("product_ops_events", total, labels)
        if cfg["product"] == "topup":
            _set_gauge(
                "topup_events",
                total,
                {
                    "perimeter": "api",
                    "channel": cfg["channel"],
                    "window": WINDOW,
                    "source": "logs-tn",
                },
            )
        if cfg["product"] == "subscription":
            _set_gauge(
                "subscription_events",
                total,
                {
                    "perimeter": "api",
                    "channel": cfg["channel"],
                    "type": "all",
                    "window": WINDOW,
                    "source": "logs-tn",
                },
            )
        if err:
            _set_gauge(
                "product_ops_problems",
                err,
                {
                    **labels,
                    "problem": "error_logs",
                },
            )

    for type_key, type_label in type_filters.items():
        try:
            res = _es(
                "logs-tn-*/_search",
                {
                    "size": 0,
                    "query": {
                        "bool": {
                            "must": [
                                {"range": {"@timestamp": {"gte": f"now-{WINDOW}"}}},
                                {"wildcard": {"k8s_pod_name": "*subscription*"}},
                                {"match_phrase": {"message": type_key}},
                            ]
                        }
                    },
                },
            )
        except Exception:
            continue
        total = (res.get("hits") or {}).get("total", {})
        count = float(total.get("value") if isinstance(total, dict) else (total or 0))
        _set_gauge(
            "subscription_events",
            count,
            {
                "perimeter": "api",
                "channel": "subscription-api",
                "type": type_label,
                "window": WINDOW,
                "source": "logs-tn",
            },
        )


def scrape_perimeter_problem_heatmap():
    """Cross-perimeter error density for ops dashboards."""
    _reset_series("perimeter_problems_15m")
    try:
        res = _es(
            "logs-tn-*/_search",
            {
                "size": 0,
                "query": {
                    "bool": {
                        "must": [
                            {"range": {"@timestamp": {"gte": "now-15m"}}},
                            {"terms": {"level": ["error", "fatal", "ERROR", "FATAL"]}},
                        ]
                    }
                },
                "aggs": {
                    "by_perimeter": {
                        "terms": {"field": "functional_perimeter", "size": 20, "missing": "unknown"},
                        "aggs": {
                            "by_ns": {"terms": {"field": "k8s_namespace_name", "size": 15}},
                        },
                    }
                },
            },
        )
    except Exception:
        return
    for bucket in res.get("aggregations", {}).get("by_perimeter", {}).get("buckets", []):
        perimeter = str(bucket.get("key") or "unknown")
        _set_gauge(
            "perimeter_problems_15m",
            float(bucket.get("doc_count") or 0),
            {"perimeter": perimeter, "namespace": "all", "source": "logs-tn"},
        )
        for ns in bucket.get("by_ns", {}).get("buckets", []):
            _set_gauge(
                "perimeter_problems_15m",
                float(ns.get("doc_count") or 0),
                {
                    "perimeter": perimeter,
                    "namespace": str(ns.get("key") or "unknown"),
                    "source": "logs-tn",
                },
            )


def scrape_loop():
    global _last_error
    while True:
        errors: list[str] = []
        try:
            scrape_clarity()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"clarity:{exc}")
        try:
            scrape_es_functional_logs()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"logs:{exc}")
        try:
            scrape_zeebe_transfers()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"zeebe:{exc}")
        try:
            scrape_zeebe_transfer_amounts()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"amounts:{exc}")
        try:
            scrape_mt_card_payments()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mt:{exc}")
        try:
            scrape_product_signals_from_logs()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"products:{exc}")
        try:
            scrape_perimeter_problem_heatmap()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"perimeter:{exc}")

        with _lock:
            _last_error = " | ".join(errors)
            _set_gauge("business_exporter_up", 0 if errors and "clarity:" in _last_error else 1)
            # stay up if clarity works; partial scrapes still useful
            if not any(e.startswith("clarity:") for e in errors):
                _set_gauge("business_exporter_up", 1)
            _set_gauge("business_exporter_scrape_timestamp", time.time())
            _set_gauge("business_exporter_partial_errors", float(len(errors)))
        time.sleep(SCRAPE_SECONDS)


HELP = [
    ("business_exporter_up", "gauge", "1 if last scrape succeeded (clarity required)"),
    ("business_exporter_partial_errors", "gauge", "Number of partial scrape failures in last cycle"),
    ("clarity_customers", "gauge", "Clarity customers total"),
    ("clarity_customers_by_status", "gauge", "Customers by canonical status"),
    ("clarity_customers_by_kyc_progress", "gauge", "Customers by KYC cycle status"),
    ("clarity_customers_by_kind", "gauge", "Customers by kind (individual/business)"),
    ("clarity_users_funnel", "gauge", "User onboarding funnel stages"),
    ("logs_events_15m", "gauge", "Log events in last 15m by functional perimeter"),
    ("logs_events_15m_by_ns", "gauge", "Log events in last 15m by namespace"),
    ("logs_events_15m_by_level", "gauge", "Log events in last 15m by level"),
    ("logs_errors_15m_by_ns", "gauge", "Error/fatal log events in last 15m by namespace"),
    ("payment_ops_count", "gauge", "Payment operations by rail context/direction/outcome"),
    ("payment_ops_by_process", "gauge", "Payment operations by BPMN process"),
    ("payment_ops_problems", "gauge", "Payment job failures/timeouts by process"),
    ("payment_job_problems", "gauge", "Payment job failures by Zeebe job type"),
    ("payment_zeebe_intent_count", "gauge", "Zeebe job intents volume"),
    ("transfer_amount_sum_approx", "gauge", "Approx transfer amount sum from Zeebe variables"),
    ("transfer_amount_samples", "gauge", "Number of amount variable samples"),
    ("card_payment_count", "gauge", "Card payments count from mt-api"),
    ("card_payment_amount", "gauge", "Card payments amount sum from mt-api"),
    ("card_payment_amount_max", "gauge", "Card payments max amount from mt-api"),
    ("card_payment_problems", "gauge", "Card payment problem rows from mt-api"),
    ("card_payment_total", "gauge", "Total card payment rows scraped"),
    ("card_payment_scrape_up", "gauge", "1 if mt-api scrape succeeded"),
    ("product_ops_events", "gauge", "Product operation log signals (topup/card/subscription)"),
    ("product_ops_problems", "gauge", "Product operation error log signals"),
    ("topup_events", "gauge", "Top-up events by channel (stripe/telecom)"),
    ("subscription_events", "gauge", "Subscription log events by product type"),
    ("perimeter_problems_15m", "gauge", "Error/fatal logs by functional perimeter (15m)"),
]


def render_prometheus() -> str:
    lines: list[str] = []
    for name, typ, help_txt in HELP:
        lines.append(f"# HELP {name} {help_txt}")
        lines.append(f"# TYPE {name} {typ}")
    with _lock:
        for name, value in sorted(_metrics.items()):
            lines.append(f"{name} {value}")
        for name, series in sorted(_labels.items()):
            for labels, value in series:
                label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
                lines.append(f"{name}{{{label_str}}} {value}")
        if _last_error:
            lines.append(f'# error {_last_error.replace(chr(10), " ")}')
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        body = render_prometheus().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: A003
        return


def main():
    threading.Thread(target=scrape_loop, daemon=True).start()
    HTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
