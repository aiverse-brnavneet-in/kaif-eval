"""Generic HTTP API connector."""

from __future__ import annotations

import urllib.parse

from app.config import connector_fetch
from app.http import http_json


class ApiConnector:
    name = "api"

    def fetch(self, hub, src: dict, job_id: str, extra: dict) -> dict:
        base = str(src.get("url") or extra.get("url") or "").rstrip("/")
        path = str(extra.get("path") or src.get("path") or "")
        method = str(extra.get("method") or src.get("method") or "GET").upper()
        timeout = float(src.get("timeout_s") or 20)
        if not base:
            return {"ok": False, "error": "missing_api_url"}
        path = path.replace("$session_id", job_id).replace("${session_id}", job_id)
        query = extra.get("query") if isinstance(extra.get("query"), dict) else src.get("query")
        q = ""
        if isinstance(query, dict) and query:
            qmap = {
                str(k): str(v).replace("$session_id", job_id).replace("${session_id}", job_id)
                for k, v in query.items()
            }
            q = "?" + urllib.parse.urlencode(qmap)
        url = base + (path if path.startswith("/") or not path else "/" + path) + q
        hdrs = hub._headers(src)
        fetch = connector_fetch(hub.designer, self.name)
        header_name = str(
            fetch.get("header") or src.get("correlation_header") or ""
        ).strip()
        if header_name and job_id:
            hdrs.setdefault(header_name, job_id)
        body = extra.get("body") if extra.get("body") is not None else src.get("body")
        try:
            payload = http_json(
                url,
                method=method,
                body=body if isinstance(body, dict) else None,
                timeout=timeout,
                headers=hdrs,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200], "url": url}
        return {"ok": True, "json": payload, "url": url, "method": method}
