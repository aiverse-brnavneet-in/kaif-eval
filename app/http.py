"""Tiny JSON HTTP helper. No third-party deps."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def auth_headers(auth: object) -> dict:
    """Build HTTP auth headers from a connector/source auth block."""
    if not isinstance(auth, dict):
        return {}
    kind = str(auth.get("type") or "none").strip().lower()
    if kind in ("", "none"):
        return {}
    token = str(auth.get("token") or auth.get("value") or "")
    if kind == "bearer":
        return {"Authorization": "Bearer " + token} if token else {}
    if kind == "token":
        return {"Authorization": "token " + token} if token else {}
    if kind == "basic":
        import base64

        raw = ("%s:%s" % (auth.get("username") or "", auth.get("password") or "")).encode("utf-8")
        return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}
    if kind in ("header", "api_key"):
        name = str(auth.get("header") or auth.get("name") or "X-API-Key")
        if not name or not token:
            return {}
        prefix = str(auth.get("prefix") or "")
        return {name: prefix + token}
    return {}


def http_json(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    token: str = "",
    bearer: str = "",
    timeout: float = 20,
    headers: dict | None = None,
) -> object:
    data = None if body is None else json.dumps(body).encode("utf-8")
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if bearer:
        hdrs["Authorization"] = "Bearer " + bearer
    elif token:
        hdrs["Authorization"] = f"token {token}"
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))
