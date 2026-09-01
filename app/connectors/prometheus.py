"""Prometheus connector — PromQL instant query."""

from __future__ import annotations

import urllib.parse

from app.config import connector_fetch
from app.http import http_json


class PrometheusConnector:
    name = "prometheus"

    def fetch(self, hub, src: dict, job_id: str, extra: dict) -> dict:
        fetch = connector_fetch(hub.designer, self.name)
        placeholder = str(fetch.get("placeholder") or "$session_id").strip() or "$session_id"
        base = str(src.get("url") or "").rstrip("/")
        query = str(extra.get("query") or src.get("query") or "").strip()
        query = (
            query.replace(placeholder, job_id)
            .replace("$job_id", job_id)
            .replace("${job_id}", job_id)
            .replace("$session_id", job_id)
            .replace("${session_id}", job_id)
        )
        if not base:
            return {"ok": False, "error": "missing_prometheus_url", "value": None}
        if not query:
            return {"ok": False, "error": "missing_prometheus_query", "value": None}
        url = base + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
        try:
            data = http_json(url, headers=hub._headers(src))
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200], "value": None, "query": query}
        if not isinstance(data, dict) or data.get("status") != "success":
            return {"ok": False, "error": "prometheus_query_failed", "value": None, "query": query}
        result = ((data.get("data") or {}) if isinstance(data.get("data"), dict) else {}).get("result") or []
        samples = []
        value = None
        if isinstance(result, list):
            for item in result:
                if not isinstance(item, dict):
                    continue
                pair = item.get("value") or item.get("values") or []
                raw = pair[1] if isinstance(pair, list) and len(pair) > 1 else None
                try:
                    n = float(raw)
                except (TypeError, ValueError):
                    continue
                samples.append({"metric": item.get("metric") or {}, "value": n})
                value = n if value is None else value + n
        return {"ok": value is not None, "value": value, "samples": samples, "query": query}
