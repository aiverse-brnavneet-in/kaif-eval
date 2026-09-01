"""Load eval-designer.yaml (composition root) or a legacy eval.yaml."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def expand_env(s: str) -> str:
    def repl(m):
        inner = m.group(1)
        if ":-" in inner:
            name, default = inner.split(":-", 1)
            return os.environ.get(name, default)
        return os.environ.get(inner, "")

    return re.sub(r"\$\{([^}]+)\}", repl, s)


def parse_file(path: Path) -> dict:
    raw = expand_env(path.read_text(encoding="utf-8"))
    if path.suffix == ".json":
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    try:
        import yaml  # type: ignore
    except ImportError:
        alt = path.with_suffix(".json")
        if alt.is_file():
            data = json.loads(expand_env(alt.read_text(encoding="utf-8")))
            return data if isinstance(data, dict) else {}
        raise SystemExit("Need PyYAML to load %s" % path)
    data = yaml.safe_load(raw) or {}
    return data if isinstance(data, dict) else {}


def _resolve(cfg_dir: Path, rel: str) -> Path:
    p = Path(str(rel).strip())
    if not p.is_absolute():
        p = cfg_dir / p
    return p


def _file_list(block: object) -> list[str]:
    if isinstance(block, dict):
        files = block.get("files") or []
    elif isinstance(block, list):
        files = block
    else:
        files = []
    if isinstance(files, str):
        files = [files]
    return [str(x).strip() for x in files if str(x).strip()]


def _load_included(cfg_dir: Path, rels: list[str]) -> list[tuple[Path, dict]]:
    out = []
    for rel in rels:
        p = _resolve(cfg_dir, rel)
        if not p.is_file():
            raise SystemExit("included file not found: %s" % rel)
        out.append((p, parse_file(p)))
    return out


def _as_flow_body(data: dict, stem: str) -> dict[str, dict]:
    if not data:
        return {}
    name = str(data.get("name") or stem).strip() or stem
    if "agents" in data or "agent" in data:
        body = {k: v for k, v in data.items() if k != "name"}
        return {name: body}
    out = {}
    for k, v in data.items():
        if k == "files":
            continue
        if isinstance(v, dict):
            out[str(k)] = v
    return out


def resolve_flows(cfg: dict, cfg_dir: Path) -> dict:
    block = cfg.get("flows") if isinstance(cfg.get("flows"), dict) else {}
    merged: dict[str, dict] = {}
    for rel in _file_list(block):
        p = _resolve(cfg_dir, rel)
        if not p.is_file():
            raise SystemExit("flow file not found: %s" % rel)
        merged.update(_as_flow_body(parse_file(p), p.stem))
    for k, v in block.items():
        if k == "files" or not isinstance(v, dict):
            continue
        merged[str(k)] = v
    cfg = dict(cfg)
    cfg["flows"] = merged
    return cfg


def _is_designer(raw: dict) -> bool:
    if not isinstance(raw, dict):
        return False
    if raw.get("include"):
        return True
    if str(raw.get("kind") or "").lower() == "evaldesigner":
        return True
    connectors = raw.get("connectors")
    policies = raw.get("policies")
    if isinstance(raw.get("designer"), dict) and raw["designer"].get("files"):
        return True
    if isinstance(connectors, dict) and connectors.get("files"):
        return True
    if isinstance(policies, dict) and policies.get("files"):
        return True
    return False


def _deep_merge(base: object, override: object) -> object:
    if not isinstance(base, dict):
        return override if override is not None else base
    if not isinstance(override, dict):
        return base if override is None else override
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def _normalize_connector(data: dict, stem: str) -> tuple[str, dict]:
    if not isinstance(data, dict):
        raise SystemExit("connector file must be a mapping with name:")
    ctype = str(data.get("name") or data.get("type") or stem).strip()
    if not ctype:
        raise SystemExit("connector file missing name:")
    body = dict(data)
    body["name"] = ctype
    return ctype, body


def _flatten_source(name: str, data: dict, connector: dict) -> dict:
    merged_auth = _deep_merge(connector.get("auth") or {}, data.get("auth") or {})
    merged_headers = _deep_merge(connector.get("headers") or {}, data.get("headers") or {})
    merged_conn = _deep_merge({}, data.get("connection") or {})
    params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
    if not params and isinstance(data.get("params"), dict):
        params = data.get("params")
    out = dict(params)
    out["name"] = name
    out["connector"] = str(data.get("connector") or "").strip()
    out["tags"] = list(data.get("tags") or [])
    out["auth"] = merged_auth if isinstance(merged_auth, dict) else {}
    out["headers"] = merged_headers if isinstance(merged_headers, dict) else {}
    url = ""
    if isinstance(merged_conn, dict):
        url = str(merged_conn.get("url") or "")
    if not url:
        url = str(out.get("url") or "")
    out["url"] = url
    out["type"] = out["connector"] or name
    if out["connector"] == "kagent":
        out.setdefault("api", url)
    if out["connector"] == "llm":
        out.setdefault("endpoint", url)
        token = str((out.get("auth") or {}).get("token") or "")
        if token:
            out.setdefault("api_key", token)
    return out


def _normalize_source(data: dict, connectors: dict) -> tuple[str, dict]:
    if not isinstance(data, dict):
        raise SystemExit("source file must be a mapping with name: and connector:")
    name = str(data.get("name") or "").strip()
    if not name:
        raise SystemExit("source file missing name:")
    connector_name = str(data.get("connector") or "").strip()
    if not connector_name:
        raise SystemExit("source %s missing connector:" % name)
    connector = connectors.get(connector_name)
    if not isinstance(connector, dict):
        raise SystemExit("source %s refers to unknown connector %s" % (name, connector_name))
    return name, _flatten_source(name, data, connector)


def _connector_include_list(block: object) -> list[str]:
    if not isinstance(block, dict):
        return []
    inc = block.get("include")
    if not inc:
        return []
    if isinstance(inc, str):
        return [inc.strip()] if inc.strip() else []
    return [str(x).strip() for x in inc if str(x).strip()]


def _apply_designer_fragment(cfg: dict, fragment: dict) -> dict:
    """Merge modular designer YAML (session_id, store, worker, evidence, …)."""
    out = dict(cfg)
    for key, value in fragment.items():
        if key in ("connectors", "sources", "policies", "designer", "global", "include"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out.get(key) or {}, value)
        else:
            out[key] = value
    return out


def store_spec(cfg: dict) -> dict:
    raw = cfg.get("store") if isinstance(cfg.get("store"), dict) else {}
    conn = raw.get("connection") if isinstance(raw.get("connection"), dict) else {}
    return {
        "driver": str(raw.get("driver") or "postgres").strip(),
        "url": str(conn.get("url") or raw.get("url") or "").strip(),
        "path": str(conn.get("path") or raw.get("path") or "").strip(),
        "schema": raw.get("schema") if isinstance(raw.get("schema"), dict) else {},
        "table": str((raw.get("schema") or {}).get("table") or "jobs"),
    }


def worker_spec(cfg: dict) -> dict:
    return cfg.get("worker") if isinstance(cfg.get("worker"), dict) else {}


def load_store_schema(cfg: dict, repo_root: Path | None = None) -> str:
    """Resolve DDL from store.schema.file or store.schema.ddl in designer config."""
    from app.store import DEFAULT_SCHEMA

    schema = store_spec(cfg).get("schema") or {}
    ddl = str(schema.get("ddl") or "").strip()
    if ddl:
        return ddl
    rel = str(schema.get("file") or "").strip()
    if not rel:
        return DEFAULT_SCHEMA
    roots: list[Path] = []
    designer_dir = str(cfg.get("designer_dir") or "").strip()
    if designer_dir:
        roots.append(Path(designer_dir))
    if repo_root:
        roots.append(repo_root / "config")
    roots.append(Path(__file__).resolve().parents[1] / "config")
    for root in roots:
        p = root / rel
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return DEFAULT_SCHEMA


def designer_meta(cfg: dict) -> dict:
    return {
        "apiVersion": str(cfg.get("apiVersion") or ""),
        "kind": str(cfg.get("kind") or "EvalDesigner"),
        "name": str((cfg.get("metadata") or {}).get("name") or "default"),
        "namespace": str((cfg.get("metadata") or {}).get("namespace") or ""),
    }


def _load_designer_modules(cfg_dir: Path, block: object) -> dict:
    merged: dict = {}
    for _path, data in _load_included(cfg_dir, _file_list(block)):
        merged = _deep_merge(merged, data)
    return merged


def _merge_designer_overlay(base: dict, overlay: dict, cfg_dir: Path) -> dict:
    """Apply demo/user overlay on top of a composed designer config."""
    cfg = dict(base)
    if overlay.get("designer"):
        frag = _load_designer_modules(cfg_dir, overlay["designer"])
        cfg = _apply_designer_fragment(cfg, frag)

    connectors = dict(base.get("connectors") or {})
    conn_block = overlay.get("connectors") if isinstance(overlay.get("connectors"), dict) else {}
    include_only = _connector_include_list(conn_block)
    for path, data in _load_included(cfg_dir, _file_list(conn_block)):
        ctype, conn_body = _normalize_connector(data, path.stem)
        if include_only and ctype not in include_only:
            continue
        connectors[ctype] = conn_body

    sources = dict(base.get("sources") or {})
    if overlay.get("sources"):
        sources = {}
    for _path, data in _load_included(cfg_dir, _file_list(overlay.get("sources"))):
        name, body = _normalize_source(data, connectors)
        sources[name] = body

    flows = dict(base.get("flows") or {})
    for path, data in _load_included(cfg_dir, _file_list(overlay.get("policies"))):
        flows.update(_as_flow_body(data, path.stem))

    gblock = overlay.get("global")
    if isinstance(gblock, dict) and gblock.get("file"):
        gp = _resolve(cfg_dir, str(gblock["file"]))
        if not gp.is_file():
            raise SystemExit("global file not found: %s" % gblock["file"])
        cfg = _deep_merge(cfg, parse_file(gp))
    elif isinstance(gblock, dict):
        cfg = _deep_merge(cfg, {k: v for k, v in gblock.items() if k != "file"})

    if isinstance(overlay.get("session_id"), dict):
        cfg["session_id"] = _deep_merge(cfg.get("session_id") or {}, overlay["session_id"])
    if isinstance(overlay.get("labels"), list):
        cfg["labels"] = overlay["labels"]
    if isinstance(overlay.get("prerequisites"), dict):
        cfg["prerequisites"] = _deep_merge(cfg.get("prerequisites") or {}, overlay["prerequisites"])
    if isinstance(overlay.get("store"), dict):
        cfg["store"] = _deep_merge(cfg.get("store") or {}, overlay["store"])
    if isinstance(overlay.get("worker"), dict):
        cfg["worker"] = _deep_merge(cfg.get("worker") or {}, overlay["worker"])

    cfg["connectors"] = connectors
    cfg["sources"] = sources
    cfg["flows"] = flows
    cfg["designer_dir"] = str(cfg_dir)
    return cfg


def assemble_designer(raw: dict, cfg_dir: Path) -> dict:
    if raw.get("include"):
        inc = raw["include"]
        paths = [inc] if isinstance(inc, str) else [str(x) for x in inc if str(x).strip()]
        base: dict = {}
        for rel in paths:
            p = _resolve(cfg_dir, rel)
            base = _deep_merge(base, assemble_designer(parse_file(p), p.parent))
        overlay = {k: v for k, v in raw.items() if k != "include"}
        if not overlay:
            return base
        return _merge_designer_overlay(base, overlay, cfg_dir)

    fragment: dict = {}
    if raw.get("designer"):
        fragment = _load_designer_modules(cfg_dir, raw["designer"])
    body = _deep_merge(fragment, {k: v for k, v in raw.items() if k != "designer"})

    connectors: dict[str, dict] = {}
    conn_block = body.get("connectors") if isinstance(body.get("connectors"), dict) else {}
    include_only = _connector_include_list(conn_block)
    for path, data in _load_included(cfg_dir, _file_list(conn_block)):
        ctype, conn_body = _normalize_connector(data, path.stem)
        if include_only and ctype not in include_only:
            continue
        connectors[ctype] = conn_body

    sources: dict[str, dict] = {}
    for _path, data in _load_included(cfg_dir, _file_list(body.get("sources"))):
        name, src_body = _normalize_source(data, connectors)
        sources[name] = src_body

    global_cfg: dict = {}
    gblock = body.get("global")
    if isinstance(gblock, dict) and gblock.get("file"):
        gp = _resolve(cfg_dir, str(gblock["file"]))
        if not gp.is_file():
            raise SystemExit("global file not found: %s" % gblock["file"])
        global_cfg = parse_file(gp)
        if global_cfg.get("include"):
            global_cfg = assemble_designer(global_cfg, gp.parent)
    elif isinstance(gblock, dict):
        global_cfg = {k: v for k, v in gblock.items() if k != "file"}

    flows: dict[str, dict] = {}
    for path, data in _load_included(cfg_dir, _file_list(body.get("policies"))):
        flows.update(_as_flow_body(data, path.stem))

    cfg = _apply_designer_fragment(global_cfg, fragment)
    cfg = _apply_designer_fragment(
        cfg,
        {k: v for k, v in body.items() if k not in ("connectors", "sources", "policies", "designer", "global")},
    )
    cfg["connectors"] = connectors
    cfg["sources"] = sources
    cfg["flows"] = flows
    cfg["designer_dir"] = str(cfg_dir)
    return cfg


def load_config(path: str) -> dict:
    p = Path(path)
    raw = parse_file(p)
    if _is_designer(raw):
        return assemble_designer(raw, p.parent)
    return resolve_flows(raw, p.parent)


def source_map(cfg: dict) -> dict:
    src = cfg.get("sources") if isinstance(cfg.get("sources"), dict) else {}
    if src:
        return src
    out = {}
    for name in ("jaeger", "gitea", "llm", "kagent", "prometheus"):
        if isinstance(cfg.get(name), dict):
            out[name] = cfg[name]
    if isinstance(cfg.get("adapter"), dict):
        ad = dict(cfg["adapter"])
        ad.setdefault("type", ad.get("name") or "kagent")
        out.setdefault("kagent", ad)
    return out


def evidence_name(cfg: dict, role: str, default: str = "") -> str:
    ev = cfg.get("evidence") if isinstance(cfg.get("evidence"), dict) else {}
    return str(ev.get(role) or default).strip()


def session_id_spec(cfg: dict) -> dict:
    spec = cfg.get("session_id") if isinstance(cfg.get("session_id"), dict) else {}
    return spec


def connector_fetch(cfg: dict, connector_type: str) -> dict:
    spec = session_id_spec(cfg)
    fetch = spec.get("fetch") if isinstance(spec.get("fetch"), dict) else {}
    by_c = fetch.get("by_connector") if isinstance(fetch.get("by_connector"), dict) else {}
    block = by_c.get(connector_type)
    return block if isinstance(block, dict) else {}


def trace_lookup_attrs(cfg: dict) -> list[str]:
    """Ordered span attributes used to find a job in Jaeger."""
    spec = session_id_spec(cfg)
    trace = spec.get("trace") if isinstance(spec.get("trace"), dict) else {}
    attrs: list[str] = []
    primary = str(trace.get("primary_attribute") or "").strip()
    if primary:
        attrs.append(primary)
    for item in trace.get("fallback_attributes") or []:
        s = str(item).strip()
        if s and s not in attrs:
            attrs.append(s)
    for item in spec.get("aliases") or []:
        s = str(item).strip()
        if s and s not in attrs:
            attrs.append(s)
    return attrs


def dotted(record: dict, path: str, default=""):
    cur: object = record
    for part in str(path or "").split("."):
        part = part.strip()
        if not part:
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return default
    if cur is None:
        return default
    return cur
