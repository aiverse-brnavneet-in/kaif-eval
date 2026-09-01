"""Fetch job data from named sources via connector registry."""

from __future__ import annotations

import json

from app.connectors import get, register_all
from app.http import auth_headers

register_all()


def connector_of(src: dict) -> str:
    return str(src.get("connector") or src.get("type") or "").strip().lower()


class SourceHub:
    """Lazy fetch keyed by (source name, session_id). Worker never lists sessions."""

    def __init__(
        self,
        sources: dict,
        designer: dict | None = None,
        flow: str = "",
        agent: str = "",
        runtime_cfg: dict | None = None,
    ):
        self.sources = sources if isinstance(sources, dict) else {}
        self.designer = designer if isinstance(designer, dict) else {}
        self.flow = flow
        self.agent = agent
        self.job_id = ""
        self.scenario = ""
        self.skill = ""
        self.runtime_cfg = runtime_cfg if isinstance(runtime_cfg, dict) else {}
        self._cache: dict[tuple, dict] = {}

    def cfg(self, name: str) -> dict:
        block = self.sources.get(name) or {}
        return block if isinstance(block, dict) else {}

    def _headers(self, src: dict) -> dict:
        hdrs = dict(src.get("headers") or {})
        hdrs.update(auth_headers(src.get("auth")))
        return hdrs

    def get(self, name: str, job_id: str, extra: dict | None = None) -> dict:
        name = (name or "").strip()
        job_id = (job_id or "").strip()
        extra = extra or {}
        if not name or name not in self.sources:
            return {"ok": False, "source": name, "error": "unknown_source"}
        cache_key = (
            name,
            job_id,
            extra.get("path") or extra.get("url") or extra.get("query") or "",
            json.dumps(self.runtime_cfg or {}, sort_keys=True, default=str),
        )
        if cache_key in self._cache:
            return self._cache[cache_key]
        src = self.cfg(name)
        kind = connector_of(src)
        conn = get(kind)
        if conn is None:
            data = {"ok": False, "source": name, "error": "unsupported_connector:%s" % kind}
        else:
            data = conn.fetch(self, src, job_id, extra)
        data["source"] = name
        data["kind"] = kind
        self._cache[cache_key] = data
        return data

    def judge(self, name: str, prompt: str, document: str, rule: dict | None = None) -> dict:
        src = dict(self.cfg(name))
        if not src:
            return {"ok": False, "score": None, "error": "unknown_source"}
        from app.deepeval_judge import g_eval

        src["labels"] = {
            "flow": self.flow or "unknown",
            "agent": self.agent or "unknown",
            "tool": "llm-eval",
            "scenario": self.scenario or "",
            "skill": self.skill or "",
            "run_id": self.job_id or "",
        }
        return g_eval(src, document, rule or {}, prompt=prompt)
