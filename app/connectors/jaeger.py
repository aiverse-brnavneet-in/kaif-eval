"""Jaeger query HTTP API, keyed by session_id (GenAI conversation id or kaif.run_id)."""

from __future__ import annotations

import json
import time
import urllib.parse
from datetime import datetime, timezone

from app.gen_ai_trace import aggregate_spans, infer_runtime, tag_map
from app.http import http_json


def _span_start_us(span: dict) -> float | None:
    v = span.get("startTime") or span.get("startTimeUnixNano")
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n > 1e15:
        return n / 1000.0
    return n


def _rfc_from_us(us: float | None) -> str:
    if not us:
        return ""
    return datetime.fromtimestamp(us / 1e6, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _search_one(
    base: str,
    job_id: str,
    attr: str,
    lookback_s: int,
    service: str,
    headers: dict,
    services: list[str] | None = None,
) -> list[dict]:
    safe = job_id.replace('"', "")
    end_us = int((time.time() + 60) * 1e6)
    start_us = max(0, end_us - int(lookback_s or 7 * 86400) * 1_000_000)
    svc_list: list[str] = []
    if service:
        svc_list.append(service)
    for s in services or []:
        if s and s not in svc_list:
            svc_list.append(s)
    if not svc_list:
        svc_list = [""]

    for svc in svc_list:
        params = {
            "tag": "%s:%s" % (attr, safe),
            "start": str(start_us),
            "end": str(end_us),
            "limit": "50",
        }
        if svc:
            params["service"] = svc
        url = base + "/api/traces?" + urllib.parse.urlencode(params)
        try:
            data = http_json(url, timeout=20, headers=headers)
        except Exception:
            continue
        rows = []
        if isinstance(data, dict):
            rows = data.get("data") or data.get("traces") or []
        if isinstance(rows, list) and rows:
            return [t for t in rows if isinstance(t, dict)]
    return []


def _search(
    base: str,
    job_id: str,
    attrs: list[str],
    lookback_s: int,
    service: str,
    headers: dict,
    services: list[str] | None = None,
) -> tuple[list[dict], str]:
    seen: set[str] = set()
    merged: list[dict] = []
    matched_attr = ""
    for attr in attrs:
        if not attr:
            continue
        for tr in _search_one(
            base, job_id, attr, lookback_s, service, headers, services
        ):
            tid = str(tr.get("traceID") or tr.get("traceId") or tr.get("id") or "")
            if tid and tid in seen:
                continue
            if tid:
                seen.add(tid)
            merged.append(tr)
            matched_attr = matched_attr or attr
        if merged:
            break
    return merged, matched_attr


def _empty(job_id: str, error: str) -> dict:
    return {
        "ok": False,
        "job_id": job_id,
        "tokens_in": 0.0,
        "tokens_out": 0.0,
        "traces": [],
        "span_names": [],
        "flow": "",
        "agent": "",
        "scenario": "",
        "skill": "",
        "started_at": "",
        "ended_at": "",
        "duration_s": 0.0,
        "gen_ai": {},
        "search_attribute": "",
        "error": error,
    }


def fetch_job(
    url: str,
    job_id: str,
    attr: str = "gen_ai.conversation.id",
    lookback_s: int = 7 * 86400,
    service: str = "",
    headers: dict | None = None,
    search_attrs: list[str] | None = None,
    services: list[str] | None = None,
    runtime_cfg: dict | None = None,
) -> dict:
    empty = _empty(job_id, "no_traces")
    if not url or not job_id:
        empty["error"] = "missing_jaeger_or_job_id"
        return empty
    base = url.rstrip("/")
    attrs = [a for a in (search_attrs or []) if a]
    if attr:
        attrs = [attr] + [a for a in attrs if a != attr]
    if not attrs:
        attrs = list(search_attrs or [])
    found, matched_attr = _search(
        base, job_id, attrs, lookback_s, service, headers or {}, services
    )
    if not found:
        return empty

    all_spans: list[dict] = []
    ids: list[str] = []
    tmin: float | None = None
    tmax: float | None = None

    for tr in found:
        tid = str(tr.get("traceID") or tr.get("traceId") or tr.get("id") or "")
        if tid:
            ids.append(tid)
        spans = tr.get("spans") or []
        if not isinstance(spans, list) or not spans:
            try:
                body = http_json(base + "/api/traces/" + tid, timeout=20, headers=headers or {})
            except Exception:
                body = {}
            if isinstance(body, dict):
                data = body.get("data") or []
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    spans = data[0].get("spans") or []
        if not isinstance(spans, list):
            continue
        all_spans.extend([s for s in spans if isinstance(s, dict)])
        for sp in spans:
            if not isinstance(sp, dict):
                continue
            ts = _span_start_us(sp)
            if ts is None:
                continue
            tmin = ts if tmin is None else min(tmin, ts)
            dur = float(sp.get("duration") or 0)
            end = ts + dur if dur else ts
            tmax = end if tmax is None else max(tmax, end)

    agg = aggregate_spans(all_spans)
    runtime = infer_runtime(all_spans, runtime_cfg)
    duration_s = 0.0
    if tmin is not None and tmax is not None:
        duration_s = max(0.0, (float(tmax) - float(tmin)) / 1e6)

    return {
        "ok": True,
        "job_id": job_id,
        "tokens_in": agg["tokens_in"],
        "tokens_out": agg["tokens_out"],
        "traces": ids,
        "span_names": agg["span_names"],
        "flow": agg["flow"],
        "agent": agg["agent"],
        "scenario": agg["scenario"],
        "skill": agg["skill"],
        "started_at": _rfc_from_us(tmin),
        "ended_at": _rfc_from_us(tmax),
        "duration_s": duration_s,
        "search_attribute": matched_attr,
        "runtime": runtime,
        "store_report_ok": runtime.get("store_report_ok"),
        "last_tool": runtime.get("last_tool"),
        "tools": runtime.get("tools"),
        "artifact": runtime.get("artifact"),
        "artifact_markdown": runtime.get("artifact_markdown"),
        "markdown": runtime.get("markdown"),
        "status": runtime.get("status"),
        "gen_ai": {
            "conversation_id": agg["conversation_id"],
            "task_id": agg["task_id"],
            "models": agg["models"],
            "providers": agg["providers"],
            "operations": agg["operations"],
            "finish_reasons": agg["finish_reasons"],
            "tool_names": agg["tool_names"],
            "tools": agg["tools"],
            "llm_calls": agg["llm_calls"],
            "span_count": agg["span_count"],
            "tokens_cache_read": agg["tokens_cache_read"],
            "tokens_cache_create": agg["tokens_cache_create"],
            "errors": agg["errors"],
        },
        "error": "",
    }


class JaegerConnector:
    name = "jaeger"

    def fetch(self, hub, src: dict, job_id: str, extra: dict) -> dict:
        from app.config import connector_fetch, trace_lookup_attrs

        fetch = connector_fetch(hub.designer, self.name)
        attr = str(
            src.get("attribute")
            or fetch.get("attribute")
            or (trace_lookup_attrs(hub.designer) or [""])[0]
        ).strip()
        try:
            lookback = int(src.get("lookback_s") or 7 * 86400)
        except (TypeError, ValueError):
            lookback = 7 * 86400
        search_attrs = [
            a.strip()
            for a in str(src.get("search_attributes") or fetch.get("search_attributes") or "").split(",")
            if a.strip()
        ]
        if not search_attrs:
            search_attrs = trace_lookup_attrs(hub.designer)
        services = [
            s.strip()
            for s in str(src.get("services") or fetch.get("services") or "").split(",")
            if s.strip()
        ]
        traces = fetch_job(
            str(src.get("url") or ""),
            job_id,
            attr,
            lookback,
            str(src.get("service") or ""),
            hub._headers(src),
            search_attrs=search_attrs,
            services=services,
            runtime_cfg=hub.runtime_cfg,
        )
        traces["ok"] = bool(traces.get("ok"))
        return traces
