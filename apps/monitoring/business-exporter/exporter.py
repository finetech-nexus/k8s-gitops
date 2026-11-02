#!/usr/bin/env python3
"""Export functional + technical business KPIs to Prometheus (Clarity KYC + ES + API pods)."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer

CLARITY_URL = os.environ.get("CLARITY_URL", "http://clarity-api.kyc-aml.svc.cluster.local:8000").rstrip("/")
CLARITY_USER = os.environ.get("CLARITY_USER", "admin")
CLARITY_PASSWORD = os.environ.get("CLARITY_PASSWORD", "password")
ES_URL = os.environ.get("ES_URL", "http://infra-elasticsearch.infra.svc.cluster.local:9200").rstrip("/")
ES_USER = os.environ.get("ES_USER", "elastic")
ES_PASSWORD = os.environ.get("ES_PASSWORD", "elasticSearchPas42")
SCRAPE_SECONDS = int(os.environ.get("SCRAPE_SECONDS", "60"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9105"))

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

_lock = threading.Lock()
_metrics: dict[str, float] = {}
_labels: dict[str, list[tuple[dict[str, str], float]]] = {}
_last_error = ""


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
    # KYC cycle expired/abandoned may only appear on kyc_status.
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
        res = _http_json(
            f"{ES_URL}/logs-tn-*/_search",
            method="POST",
            data=query,
            auth=(ES_USER, ES_PASSWORD),
            timeout=20,
        )
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


def scrape_loop():
    global _last_error
    while True:
        try:
            scrape_clarity()
            scrape_es_functional_logs()
            with _lock:
                _last_error = ""
                _set_gauge("business_exporter_up", 1)
                _set_gauge("business_exporter_scrape_timestamp", time.time())
        except Exception as exc:  # noqa: BLE001
            with _lock:
                _last_error = str(exc)
                _set_gauge("business_exporter_up", 0)
        time.sleep(SCRAPE_SECONDS)


def render_prometheus() -> str:
    lines = [
        "# HELP business_exporter_up 1 if last scrape succeeded",
        "# TYPE business_exporter_up gauge",
        "# HELP clarity_customers Clarity customers total",
        "# TYPE clarity_customers gauge",
        "# HELP clarity_customers_by_status Customers by canonical status",
        "# TYPE clarity_customers_by_status gauge",
        "# HELP clarity_customers_by_kyc_progress Customers by KYC cycle status",
        "# TYPE clarity_customers_by_kyc_progress gauge",
        "# HELP clarity_customers_by_kind Customers by kind (individual/business)",
        "# TYPE clarity_customers_by_kind gauge",
        "# HELP clarity_users_funnel User onboarding funnel stages",
        "# TYPE clarity_users_funnel gauge",
        "# HELP logs_events_15m Log events in last 15m by functional perimeter",
        "# TYPE logs_events_15m gauge",
        "# HELP logs_events_15m_by_ns Log events in last 15m by namespace",
        "# TYPE logs_events_15m_by_ns gauge",
        "# HELP logs_events_15m_by_level Log events in last 15m by level",
        "# TYPE logs_events_15m_by_level gauge",
        "# HELP logs_errors_15m_by_ns Error/fatal log events in last 15m by namespace",
        "# TYPE logs_errors_15m_by_ns gauge",
    ]
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
