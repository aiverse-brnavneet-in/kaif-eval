"""Weighted quality: two sections (deterministic, llm_as_judge), each 0–100.

Total quality_score is the average of enabled sections.
Ops: exists, missing, eq, ne, lt, lte, gt, gte, any_of, all_of, contains, regex
llm_as_judge: DeepEval G-Eval; score is 0–1 unless the rule bar is >1 (legacy 0–100).
"""

from __future__ import annotations

import json
import re


def _named_geval_metrics(raw: dict) -> list:
    """DeepEval shape: name + evaluation_steps XOR criteria.

    https://deepeval.com/docs/metrics-llm-evals — one GEval instance per named metric.
    Section-level source/input/field/op/value are inherited by each metric.
    """
    shared = {
        k: raw[k]
        for k in ("source", "metric", "input", "field", "op", "value")
        if k in raw
    }
    if isinstance(raw.get("metrics"), list):
        items = [x for x in raw["metrics"] if isinstance(x, dict)]
    elif isinstance(raw.get("rules"), list):
        items = [x for x in raw["rules"] if isinstance(x, dict)]
    elif isinstance(raw.get("checks"), list):
        items = [x for x in raw["checks"] if isinstance(x, dict)]
    else:
        return []
    out = []
    for item in items:
        merged = dict(shared)
        merged.update(item)
        if merged.get("evaluation_steps") or merged.get("criteria") or merged.get("prompt"):
            merged.setdefault("source", "judge-llm")
            merged.setdefault("metric", "g_eval")
        out.append(merged)
    return out


def _as_section(raw, default_enabled: bool) -> dict:
    """List of rules, or `{enabled, metrics|rules}` / a single rule dict."""
    if raw is None:
        return {"enabled": False, "require_outcome": "", "rules": []}
    if isinstance(raw, list):
        return {
            "enabled": default_enabled,
            "require_outcome": "",
            "rules": [r for r in raw if isinstance(r, dict)],
        }
    if not isinstance(raw, dict):
        return {"enabled": False, "require_outcome": "", "rules": []}
    enabled = raw.get("enabled")
    if enabled is None:
        enabled = default_enabled
    need = str(raw.get("require_outcome") or raw.get("outcome") or "").strip().lower()
    if need in ("", "any", "*"):
        need = ""
    metrics = _named_geval_metrics(raw)
    if metrics:
        return {
            "enabled": bool(enabled),
            "require_outcome": need,
            "rules": metrics,
        }
    rule = {k: v for k, v in raw.items() if k not in ("enabled", "require_outcome", "outcome")}
    if any(
        k in rule
        for k in (
            "name",
            "evaluation_steps",
            "criteria",
            "prompt",
            "metrics",
            "field",
            "source",
            "weight",
        )
    ):
        return {"enabled": bool(enabled), "require_outcome": need, "rules": [rule]}
    return {"enabled": bool(enabled), "require_outcome": need, "rules": []}


def _split_typed_list(rules: list) -> dict:
    det, llm = [], []
    for r in rules:
        if not isinstance(r, dict):
            continue
        t = str(r.get("type") or "deterministic").strip().lower()
        body = {k: v for k, v in r.items() if k != "type"}
        if t in ("llm_as_judge", "llm"):
            llm.append(body)
        else:
            det.append(body)
    return {
        "deterministic": {"enabled": True, "require_outcome": "", "rules": det},
        "llm_as_judge": {"enabled": bool(llm), "require_outcome": "success", "rules": llm},
    }


def normalize(quality: object, agent_cfg: dict | None = None) -> dict:
    """Two sections plus rates. Legacy: typed list or a Layer A rubric dict."""
    rates = {}
    extra = agent_cfg if isinstance(agent_cfg, dict) else {}
    if isinstance(extra.get("rates_usd_per_million"), dict):
        rates = dict(extra["rates_usd_per_million"])
    empty = {
        "deterministic": {"enabled": False, "require_outcome": "", "rules": []},
        "llm_as_judge": {"enabled": False, "require_outcome": "success", "rules": []},
    }
    if isinstance(quality, list):
        return {"rates": rates, "sections": _split_typed_list(quality)}
    if not isinstance(quality, dict):
        return {"rates": rates, "sections": empty}
    if isinstance(quality.get("rates_usd_per_million"), dict):
        rates = dict(quality["rates_usd_per_million"])
    if "deterministic" in quality or "llm_as_judge" in quality:
        return {
            "rates": rates,
            "sections": {
                "deterministic": _as_section(quality.get("deterministic"), True),
                "llm_as_judge": _as_section(quality.get("llm_as_judge"), True),
            },
        }
    rules = quality.get("rules") or quality.get("checks")
    if isinstance(rules, list):
        return {"rates": rates, "sections": _split_typed_list(rules)}
    if quality.get("rubric") == "layer_a" or quality.get("name"):
        return {"legacy": quality, "rates": rates, "sections": empty}
    return {"rates": rates, "sections": empty}


def all_rules(cfg: dict) -> list:
    out = []
    for sec in (cfg.get("sections") or {}).values():
        if isinstance(sec, dict):
            out.extend(r for r in (sec.get("rules") or []) if isinstance(r, dict))
    return out


def parse_judge_score(text: str):
    """Read a numeric score from judge JSON or a bare 0–100 number. Criteria stay in the YAML prompt."""
    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    blob = fence.group(1) if fence else raw
    obj = None
    try:
        obj = json.loads(blob)
    except Exception:
        m = re.search(r"\{[^{}]*\"score\"[^{}]*\}", raw, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if isinstance(obj, dict):
        n = _num(obj.get("score"), None)
        if n is not None:
            return n
    m = re.search(r"\b([0-9]{1,3}(?:\.[0-9]+)?)\b", raw)
    if m:
        n = _num(m.group(1), None)
        if n is not None and 0 <= n <= 100:
            return n
    return None


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def lookup(data: dict, field: str):
    field = (field or "").strip()
    if not field:
        return None
    cur: object = data
    for part in field.split("."):
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
                continue
            art = cur.get("artifact") if isinstance(cur.get("artifact"), dict) else None
            if art and part in art:
                cur = art[part]
                continue
            return None
        return None
    return cur


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _infer_predicate(rule: dict) -> tuple[str, str, object]:
    """(field, op, value) from explicit keys or from name + value shape."""
    field = str(rule.get("field") or "").strip()
    op = str(rule.get("op") or "").strip().lower()
    value = rule.get("value")
    if field and op:
        return field, op, value
    name = str(rule.get("name") or "").strip().lower()
    if isinstance(value, list):
        return field or "tools", op or "any_of", value
    if _num(value) is not None and not isinstance(value, bool):
        return field or "usd_est", op or "lte", _num(value)
    if name in ("published", "publish", "has_artifact"):
        return "artifact.sha", "exists", True
    if name in ("notified_user", "ask_user", "hitl"):
        return "tools", "any_of", ["ask_user", "adk_request_confirmation"]
    if name in ("asked_users_for_feedback", "user_feedback", "user_turns"):
        return "user_turns", "gte", 1
    if name in ("diagram", "mermaid"):
        return "markdown", "contains", "```mermaid"
    if name:
        return name, "exists", True
    return "ok", "eq", True


def _truthy_exists(got) -> bool:
    if got is None or got is False:
        return False
    if got == "":
        return False
    if isinstance(got, (list, dict)) and not got:
        return False
    return True


def match(rule: dict, data: dict) -> bool:
    field, op, value = _infer_predicate(rule)
    got = lookup(data, field)
    if op == "exists":
        return _truthy_exists(got)
    if op == "missing":
        return not _truthy_exists(got)
    if op in ("eq", ""):
        return str(got) == str(value)
    if op == "ne":
        return str(got) != str(value)
    if op in ("lt", "lte", "gt", "gte"):
        a, b = _num(got), _num(value)
        if a is None or b is None:
            return False
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b
        if op == "gt":
            return a > b
        return a >= b
    if op == "any_of":
        want = {str(x) for x in _as_list(value)}
        have = {str(x) for x in _as_list(got)}
        if field == "last_tool" or not have:
            have.add(str(data.get("last_tool") or ""))
            have.update(str(n) for n in (data.get("span_names") or []) if n)
        return bool(want & have)
    if op == "all_of":
        want = {str(x) for x in _as_list(value)}
        have = {str(x) for x in _as_list(got)}
        return bool(want) and want <= have
    if op == "contains":
        return str(value).lower() in str(got or "").lower()
    if op == "regex":
        try:
            return re.search(str(value), str(got or "")) is not None
        except re.error:
            return False
    return False


def _run_llm_judge(rule: dict, fetch, facts: dict, judge) -> dict:
    """Fetch Gitea markdown, run DeepEval G-Eval, expose score (0–1) for op/value."""
    from app.deepeval_judge import criteria_and_steps

    criteria, steps = criteria_and_steps(rule)
    data = dict(facts)
    if not criteria and not steps:
        data["score"] = None
        data["output"] = ""
        data["error"] = "missing_criteria"
        return data
    inp = rule.get("input") if isinstance(rule.get("input"), dict) else {}
    doc_src = str(inp.get("source") or "gitea").strip()
    doc_field = str(inp.get("field") or "markdown").strip()
    doc_payload = fetch(doc_src) if callable(fetch) else {}
    if isinstance(doc_payload, dict):
        data.update(doc_payload)
    document = str(lookup(data, doc_field) or data.get("markdown") or "")
    if not document.strip():
        data["score"] = None
        data["output"] = ""
        data["error"] = "missing_document"
        return data
    prompt = criteria or "\n".join(steps)
    judged = judge(prompt, document, rule) if callable(judge) else {}
    if not isinstance(judged, dict):
        judged = {}
    data.update(judged)
    score = _num(judged.get("score"), None)
    if score is None:
        score = parse_judge_score(str(data.get("output") or ""))
    # DeepEval is 0–1. If the rule still uses a 0–100 bar, scale so op/value match.
    bar = _num(rule.get("value"), None)
    if score is not None and bar is not None and bar > 1 and score <= 1:
        score = score * 100.0
    data["score"] = score
    field = str(rule.get("field") or "score").strip()
    if field and field != "score":
        data[field] = score
    return data


def _g_eval_ready(row: dict) -> bool:
    """True only when DeepEval returned a numeric score and no error."""
    if str(row.get("error") or "").strip():
        return False
    return row.get("judge_score") is not None


def _g_eval_section_score(details: list) -> float | None:
    """0–100 from G-Eval scores only (0–1 scaled ×100). None if no real output."""
    ready = [r for r in details if isinstance(r, dict) and _g_eval_ready(r)]
    if not ready:
        return None
    total_w = 0.0
    acc = 0.0
    for r in ready:
        w = _num(r.get("weight"), 0.0) or 0.0
        n = _num(r.get("judge_score"), None)
        if n is None:
            continue
        if n <= 1:
            n = n * 100.0
        acc += n * w
        total_w += w
    if not total_w:
        return None
    return round(acc / total_w, 1)


def _run_section(kind: str, rules: list, fetch, facts: dict, judge) -> tuple[float, dict, dict, list]:
    """One section, independently 0–100 = Σ(awarded) / Σ(weights) × 100."""
    breakdown: dict[str, float] = {}
    weights: dict[str, float] = {}
    details: list = []
    awarded = 0.0
    total_w = 0.0
    for rule in rules:
        name = str(rule.get("name") or "unnamed").strip()
        weight = _num(rule.get("weight"), 0.0) or 0.0
        src = str(rule.get("source") or "").strip()
        data = dict(facts)
        if kind == "llm_as_judge":
            data = _run_llm_judge(rule, fetch, facts, judge)
            src = src or "judge-llm"
        elif src and callable(fetch):
            try:
                payload = fetch(src, rule) or {}
            except TypeError:
                payload = fetch(src) or {}
            if isinstance(payload, dict):
                data.update(payload)
        ok = match(rule, data)
        got = weight if ok else 0.0
        breakdown[name] = got
        weights[name] = weight
        awarded += got
        total_w += weight
        row = {
            "name": name,
            "source": src,
            "weight": weight,
            "awarded": got,
            "pass": bool(ok),
        }
        if kind == "llm_as_judge":
            row["judge_score"] = data.get("score")
            row["reason"] = str(data.get("reason") or "")
            row["error"] = str(data.get("error") or "")
            row["criteria"] = data.get("criteria") if isinstance(data.get("criteria"), list) else []
            row["tokens_in"] = _num(data.get("tokens_in"), 0.0) or 0.0
            row["tokens_out"] = _num(data.get("tokens_out"), 0.0) or 0.0
            row["usd_est"] = _num(data.get("usd_est"), 0.0) or 0.0
            row["model"] = str(data.get("model") or "")
            row["calls"] = int(_num(data.get("calls"), 0.0) or 0)
            row["usage_source"] = str(data.get("usage_source") or "")
        details.append(row)
    pct = round(100.0 * awarded / total_w, 1) if total_w else 0.0
    return pct, breakdown, weights, details


def score(
    quality: object,
    fetch,
    facts: dict | None = None,
    agent_cfg: dict | None = None,
    judge=None,
    outcome: str = "",
) -> tuple[float, dict, dict, dict]:
    """Run both quality sections. Returns (score, breakdown, weights, eval JSON).

    llm_as_judge is skipped unless the job outcome matches `require_outcome`
    (default: success). Skipped sections are omitted from the average.
    """
    cfg = normalize(quality, agent_cfg)
    facts = dict(facts or {})
    got_outcome = str(outcome or "").strip().lower()
    if cfg.get("legacy"):
        from app.quality_layer_a import layer_a

        sha = facts.get("sha") or lookup(facts, "artifact.sha")
        md = str(facts.get("markdown") or "")
        s, bd = layer_a(md, sha)
        weights = {k: 25 if k == "published" else (15 if k == "required_sections" else 10) for k in bd}
        weights["published"] = 25
        weights["required_sections"] = 15
        ev = {
            "score": s,
            "formula": "average of enabled sections",
            "sections": {
                "deterministic": {
                    "enabled": True,
                    "score": s,
                    "rules": [
                        {"name": k, "weight": weights.get(k, 0), "awarded": v, "pass": v > 0}
                        for k, v in bd.items()
                    ],
                }
            },
        }
        return s, bd, weights, ev

    breakdown: dict[str, float] = {}
    weights: dict[str, float] = {}
    eval_sections: dict = {}
    part_scores: list[float] = []
    for kind in ("deterministic", "llm_as_judge"):
        sec = (cfg.get("sections") or {}).get(kind) or {}
        rules = sec.get("rules") or []
        need = str(sec.get("require_outcome") or "").strip().lower()
        if kind == "llm_as_judge" and not need:
            need = "success"
        skipped = bool(need) and got_outcome != need
        if skipped:
            eval_sections[kind] = {
                "enabled": False,
                "score": None,
                "skipped": True,
                "require_outcome": need,
                "got_outcome": got_outcome or None,
                "rules": [],
            }
            continue
        if kind == "llm_as_judge" and (not sec.get("enabled") or not rules):
            eval_sections[kind] = {"enabled": False, "score": None, "rules": []}
            continue
        if not rules:
            eval_sections[kind] = {"enabled": False, "score": None, "rules": []}
            continue
        pct, bd, w, details = _run_section(kind, rules, fetch, facts, judge)
        if kind == "llm_as_judge":
            g_pct = _g_eval_section_score(details)
            if g_pct is None:
                err = next(
                    (str(r.get("error") or "") for r in details if r.get("error")),
                    "no_g_eval",
                )
                eval_sections[kind] = {
                    "enabled": False,
                    "score": None,
                    "skipped": True,
                    "skip_reason": "no_g_eval",
                    "error": err,
                    "rules": details,
                }
                continue
            pct = g_pct
            bd = {}
            w = {}
            for r in details:
                if not _g_eval_ready(r):
                    continue
                name = str(r.get("name") or "unnamed")
                n = _num(r.get("judge_score"), None)
                if n is None:
                    continue
                if n <= 1:
                    n = n * 100.0
                bd[name] = round(n, 1)
                w[name] = _num(r.get("weight"), 0.0) or 0.0
        block = {"enabled": True, "score": pct, "rules": details}
        if kind == "llm_as_judge":
            tin = sum(_num(r.get("tokens_in"), 0.0) or 0.0 for r in details)
            tout = sum(_num(r.get("tokens_out"), 0.0) or 0.0 for r in details)
            block["tokens_in"] = round(tin, 1)
            block["tokens_out"] = round(tout, 1)
            block["usd_est"] = round(sum(_num(r.get("usd_est"), 0.0) or 0.0 for r in details), 6)
            block["model"] = next((str(r.get("model") or "") for r in details if r.get("model")), "")
            block["calls"] = int(sum(_num(r.get("calls"), 0.0) or 0.0 for r in details))
            block["usage_source"] = next(
                (str(r.get("usage_source") or "") for r in details if r.get("usage_source")),
                "none",
            )
        eval_sections[kind] = block
        breakdown.update(bd)
        weights.update(w)
        part_scores.append(pct)
    total = round(sum(part_scores) / len(part_scores), 1) if part_scores else 0.0
    judge_sec = eval_sections.get("llm_as_judge") or {}
    ev = {
        "score": total,
        "formula": "average of enabled sections",
        "sections": eval_sections,
        "usd_judge": round(_num(judge_sec.get("usd_est"), 0.0) or 0.0, 6),
        "tokens_judge_in": round(_num(judge_sec.get("tokens_in"), 0.0) or 0.0, 1),
        "tokens_judge_out": round(_num(judge_sec.get("tokens_out"), 0.0) or 0.0, 1),
    }
    return total, breakdown, weights, ev
