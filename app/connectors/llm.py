"""LLM connector — judge backend configuration (fetch is a capability probe)."""

from __future__ import annotations


class LlmConnector:
    name = "llm"

    def fetch(self, hub, src: dict, job_id: str, extra: dict) -> dict:
        return {"ok": bool(src.get("enabled", True)), "kind": "llm"}
