"""Outcome classification. Each outcome type names a source from eval.yaml."""

from __future__ import annotations

DEFAULT_OUTCOMES: dict = {}


def parse_outcome(raw: object, default_source: str = "") -> dict:
    """Normalize one outcome type to {source, rules, default}."""
    if raw is None or raw == "default" or raw is True:
        return {"source": default_source, "rules": [], "default": True}
    if isinstance(raw, list):
        return {
            "source": default_source,
            "rules": [r for r in raw if isinstance(r, dict)],
            "default": False,
        }
    if not isinstance(raw, dict):
        return {"source": default_source, "rules": [], "default": True}
    rules = raw.get("rules")
    if rules is None:
        rules = raw.get("match") or raw.get("when")
    if not isinstance(rules, list):
        rules = []
        for k, v in raw.items():
            if k in ("source", "default", "rules", "match", "when"):
                continue
            if isinstance(v, list):
                rules.extend([x for x in v if isinstance(x, dict)])
            elif isinstance(v, dict):
                rules.append(v)
            elif k in ("tool_result", "last_tool", "field", "status"):
                rules.append({k: v})
    return {
        "source": str(raw.get("source") or default_source or ""),
        "rules": [r for r in rules if isinstance(r, dict)],
        "default": bool(raw.get("default")),
    }


def pending_tools(outcomes: dict | None) -> list[str]:
    spec = parse_outcome((outcomes or {}).get("pending"), "")
    names = []
    for rule in spec.get("rules") or []:
        t = str(rule.get("last_tool") or "").strip()
        if t:
            names.append(t)
    return names


def _sha(data: dict) -> str:
    art = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
    return str(art.get("sha") or data.get("sha") or "").strip()


def _match_rule(rule: dict, data: dict) -> bool:
    last = str(data.get("last_tool") or "").strip()
    st = str(data.get("status") or "").strip()
    sha = _sha(data)
    spans = " ".join(str(n) for n in (data.get("span_names") or [])).lower()
    if rule.get("tool_result"):
        tool = str(rule.get("tool_result"))
        field = str(rule.get("field") or "sha")
        if field == "sha" and (bool(sha) or bool(data.get("store_report_ok") or data.get("publish_ok"))):
            return last == tool or tool.lower() in spans or bool(sha)
        if tool.lower() in spans:
            return True
        return last == tool
    if rule.get("last_tool"):
        want = str(rule.get("last_tool"))
        return last == want or want.lower() in spans
    if rule.get("status"):
        return st == str(rule.get("status"))
    return False


def classify_with_data(outcomes: dict | None, fetched: dict[str, dict]) -> tuple[str, str]:
    """Apply per-type rules to data already fetched from each type's source.

    fetched: outcome_type → source payload (ok, artifact, last_tool, span_names, ...)
    """
    cfg = outcomes or DEFAULT_OUTCOMES
    order = ("success", "pending", "unfinished")
    unfinished_status = "INCOMPLETE"
    for name in order:
        raw = cfg.get(name)
        if name == "unfinished" and raw is None:
            raw = cfg.get("failed")
        spec = parse_outcome(raw, "")
        data = fetched.get(name) or fetched.get("failed") or {}
        if name == "success" and spec.get("rules"):
            if any(_match_rule(r, data) for r in spec["rules"]):
                return "PUBLISHED", "success"
        elif name == "pending" and spec.get("rules"):
            if any(_match_rule(r, data) for r in spec["rules"]):
                return "BLOCKED_ON_USER", "pending"
        elif name == "unfinished":
            if spec.get("rules") and any(_match_rule(r, data) for r in spec["rules"]):
                st = str(data.get("status") or unfinished_status)
                return st, "unfinished"
    data = fetched.get("pending") or fetched.get("success") or fetched.get("unfinished") or fetched.get("failed") or {}
    st = str(data.get("status") or unfinished_status)
    if st == "BLOCKED_ON_USER":
        return st, "pending"
    if _sha(data):
        return "PUBLISHED", "success"
    return st or unfinished_status, "unfinished"


def classify(
    status: str,
    last_tool: str,
    artifact_sha: str | None,
    outcomes: dict | None = None,
) -> tuple[str, str]:
    data = {
        "status": status,
        "last_tool": last_tool,
        "artifact": {"sha": artifact_sha},
        "store_report_ok": bool(artifact_sha),
        "span_names": [],
    }
    return classify_with_data(
        outcomes,
        {"success": data, "pending": data, "unfinished": data},
    )
