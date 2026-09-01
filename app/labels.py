"""Leveled labels: define (catalog) and/or fetch (source field) from the designer."""

from __future__ import annotations

from app.config import dotted


def spec(cfg: dict) -> list[dict]:
    rows = cfg.get("labels") or []
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            level = int(row.get("level") or i + 1)
        except (TypeError, ValueError):
            level = i + 1
        item = dict(row)
        item["level"] = level
        item["name"] = name
        out.append(item)
    out.sort(key=lambda r: r["level"])
    return out


def flows(cfg: dict) -> dict:
    block = cfg.get("flows") or {}
    return block if isinstance(block, dict) else {}


def default_flow(cfg: dict) -> str:
    names = [k for k in flows(cfg).keys() if k != "files"]
    return names[0] if names else "unknown"


def flow_block(cfg: dict, flow_name: str) -> dict:
    block = flows(cfg).get(flow_name) or {}
    return block if isinstance(block, dict) else {}


def agent_entries(flow_cfg: dict) -> list[dict]:
    raw = flow_cfg.get("agents")
    if raw is None:
        raw = flow_cfg.get("agent")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"name": item.strip()})
        elif isinstance(item, dict) and str(item.get("name") or "").strip():
            out.append(item)
    return out


def agent_names(flow_cfg: dict) -> list[str]:
    return [str(a.get("name")) for a in agent_entries(flow_cfg)]


def agent_block(flow_cfg: dict, agent_name: str) -> dict:
    want = (agent_name or "").strip()
    entries = agent_entries(flow_cfg)
    for a in entries:
        if str(a.get("name")) == want:
            return a
    return entries[0] if entries else {}


def allowed(flow_cfg: dict, label_name: str) -> list[str]:
    """Allowed values for a label. `agent` reads flows.<flow>.agents[].name."""
    if label_name == "flow":
        return []
    if label_name in ("agent", "agents"):
        return agent_names(flow_cfg)
    raw = flow_cfg.get(label_name)
    if raw is None:
        raw = flow_cfg.get(label_name + "s")
    if isinstance(raw, list):
        names = []
        for x in raw:
            if isinstance(x, str) and x.strip():
                names.append(x.strip())
            elif isinstance(x, dict) and x.get("name"):
                names.append(str(x.get("name")))
        return names
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def defined_values(cfg: dict, row: dict, flow_name: str) -> list[str]:
    define = row.get("define") if isinstance(row.get("define"), dict) else {}
    if define.get("from") == "policies":
        return [k for k in flows(cfg).keys() if k != "files"]
    key = str(define.get("from_policy_key") or "").strip()
    if key:
        return allowed(flow_block(cfg, flow_name), key)
    raw = define.get("values")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def snap(value: str, allowed_values: list[str]) -> str:
    v = (value or "").strip()
    if not allowed_values:
        return v or "unknown"
    if v in allowed_values:
        return v
    return "unknown"


def _fetch_steps(row: dict) -> list[dict]:
    fetch = row.get("fetch")
    if isinstance(fetch, list):
        return [x for x in fetch if isinstance(x, dict)]
    if isinstance(fetch, dict):
        return [fetch]
    return []


def fetch_value(row: dict, records: dict) -> str:
    for step in _fetch_steps(row):
        src = str(step.get("source") or "").strip()
        field = str(step.get("field") or "").strip()
        payload = records.get(src) if isinstance(records.get(src), dict) else {}
        if not payload or not payload.get("ok"):
            continue
        val = dotted(payload, field, "")
        if val not in (None, ""):
            return str(val)
    return ""


def pack(cfg: dict, values: dict, records: dict | None = None) -> list[dict]:
    """[{level, key, value}, ...] using designer label names."""
    records = records if isinstance(records, dict) else {}
    flow_name = snap(
        str(values.get("flow") or default_flow(cfg)),
        list(flows(cfg).keys()) or [default_flow(cfg)],
    )
    if flow_name == "unknown":
        flow_name = default_flow(cfg)
    block = flow_block(cfg, flow_name)
    out = []
    for row in spec(cfg):
        name = row["name"]
        fetched = fetch_value(row, records)
        if name == "flow":
            val = fetched or flow_name
            catalog = defined_values(cfg, row, flow_name)
            val = snap(val, catalog) if catalog else val
            if val == "unknown":
                val = flow_name
        else:
            catalog = defined_values(cfg, row, flow_name) or allowed(block, name)
            raw = fetched or str(values.get(name) or "")
            val = snap(raw, catalog)
        out.append({"level": row["level"], "key": name, "value": val})
    return out


def unpack(labels: object) -> dict:
    out: dict[str, str] = {}
    rows = labels
    if isinstance(labels, str):
        import json

        try:
            rows = json.loads(labels)
        except Exception:
            rows = []
    if not isinstance(rows, list):
        return out
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("name") or "").strip()
        if not key:
            continue
        out[key] = str(item.get("value") or "")
    return out


def apply_to_card(card: dict) -> dict:
    merged = dict(card)
    flat = unpack(card.get("labels"))
    for k, v in flat.items():
        if v != "" or k not in merged:
            merged[k] = v
    return merged
