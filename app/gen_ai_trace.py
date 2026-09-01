"""OpenTelemetry GenAI semantic conventions — span attribute extraction for eval.

Spec (as of 2026-09): https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md

KAIF producers (kagent ADK + agentgateway) emit a mix of stable GenAI attributes and
kaif.* correlation labels. This module normalises Jaeger/Tempo span JSON into eval facts.
"""

from __future__ import annotations

import json
import re
from collections import Counter

# Session / turn correlation (OTel GenAI + KAIF)
SESSION_ATTRS = (
    "gen_ai.conversation.id",
    "kaif.run_id",
    "gen_ai.task.id",
)
CORRELATION_ATTRS = (
    "kaif.flow",
    "kaif.agent",
    "kaif.scenario",
    "kaif.skill",
    "kaif.tool",
    "gen_ai.agent.name",
    "gen_ai.agent.description",
)

# Inference (chat / generate)
INFERENCE_ATTRS = (
    "gen_ai.operation.name",
    "gen_ai.system",
    "gen_ai.provider.name",
    "gen_ai.request.model",
    "gen_ai.response.model",
    "gen_ai.response.id",
    "gen_ai.response.finish_reasons",
)

# Token usage — OTel uses input/output; older paths use prompt/completion
TOKEN_IN_ATTRS = (
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.prompt_tokens",
    "llm.inputTokens",
)
TOKEN_OUT_ATTRS = (
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.completion_tokens",
    "llm.outputTokens",
)
TOKEN_CACHE_ATTRS = (
    "gen_ai.usage.cache_read.input_tokens",
    "gen_ai.usage.cache_read_input_tokens",
    "gen_ai.usage.cache_creation.input_tokens",
)

# Tool execution spans
TOOL_ATTRS = (
    "gen_ai.tool.name",
    "gen_ai.tool.type",
    "gen_ai.tool.call.id",
    "gen_ai.tool.description",
)

CHAT_OPERATIONS = frozenset(
    {
        "chat",
        "generate_content",
        "text_completion",
        "chat.completions",
        "openai.chat",
    }
)

TOOL_RESPONSE_KEYS = (
    "gcp.vertex.agent.tool_response",
    "gen_ai.tool.response",
)
TOOL_ARGS_KEYS = (
    "gcp.vertex.agent.tool_call_args",
)
def _num(v, default=0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def tag_map(span: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    tags = span.get("tags") or span.get("attributes") or []
    if isinstance(tags, list):
        for it in tags:
            if not isinstance(it, dict):
                continue
            k = str(it.get("key") or it.get("name") or "")
            v = it.get("value")
            if isinstance(v, dict):
                v = (
                    v.get("stringValue")
                    or v.get("intValue")
                    or v.get("doubleValue")
                    or v.get("boolValue")
                    or ""
                )
            if k:
                out[k] = str(v)
    elif isinstance(tags, dict):
        for k, v in tags.items():
            out[str(k)] = str(v)
    return out


def _first(tags: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = str(tags.get(k) or "").strip()
        if v:
            return v
    return ""


def _token_in(tags: dict[str, str]) -> float:
    return max(_num(tags.get(k)) for k in TOKEN_IN_ATTRS) if any(tags.get(k) for k in TOKEN_IN_ATTRS) else 0.0


def _token_out(tags: dict[str, str]) -> float:
    return max(_num(tags.get(k)) for k in TOKEN_OUT_ATTRS) if any(tags.get(k) for k in TOKEN_OUT_ATTRS) else 0.0


def _is_inference_span(op: str, tags: dict[str, str]) -> bool:
    op_l = (op or "").lower()
    gop = str(tags.get("gen_ai.operation.name") or "").lower()
    if gop in CHAT_OPERATIONS or gop == "chat":
        return True
    if "llm-failover" in op_l or op_l in ("openai.chat", "chat"):
        return True
    if tags.get("gen_ai.request.model") and tags.get("gen_ai.usage.input_tokens"):
        return True
    if tags.get("gen_ai.request.model") and tags.get("gen_ai.usage.prompt_tokens"):
        return True
    return False


def _is_tool_span(tags: dict[str, str]) -> bool:
    if tags.get("gen_ai.tool.name"):
        return True
    return str(tags.get("gen_ai.operation.name") or "").lower() in ("execute_tool", "tool")


def aggregate_spans(spans: list[dict]) -> dict:
    """Fold span list into eval-friendly GenAI facts."""
    names: list[str] = []
    labels = {
        "flow": "",
        "agent": "",
        "scenario": "",
        "skill": "",
        "conversation_id": "",
        "task_id": "",
    }
    models: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    operations: Counter[str] = Counter()
    finish_reasons: Counter[str] = Counter()
    tools: list[dict] = []
    errors: list[str] = []
    cache_read = cache_create = 0.0
    # Dedupe LLM token counts per gen_ai.response.id (kagent + agentgateway share one call)
    token_by_response: dict[str, tuple[float, float]] = {}
    orphan_tokens: list[tuple[float, float]] = []

    for sp in spans:
        if not isinstance(sp, dict):
            continue
        op = str(sp.get("operationName") or sp.get("name") or "")
        names.append(op)
        tags = tag_map(sp)
        labels["conversation_id"] = labels["conversation_id"] or _first(
            tags, ("gen_ai.conversation.id",)
        )
        labels["task_id"] = labels["task_id"] or _first(tags, ("gen_ai.task.id",))
        labels["flow"] = labels["flow"] or _first(tags, ("kaif.flow",))
        labels["agent"] = labels["agent"] or _first(
            tags, ("kaif.agent", "gen_ai.agent.name")
        )
        labels["scenario"] = labels["scenario"] or _first(tags, ("kaif.scenario",))
        labels["skill"] = labels["skill"] or _first(tags, ("kaif.skill",))

        if tags.get("error") == "true" or tags.get("otel.status_code") == "ERROR":
            errors.append(str(tags.get("otel.status_description") or op or "error"))

        gop = str(tags.get("gen_ai.operation.name") or op or "unknown")
        operations[gop] += 1
        req_model = str(tags.get("gen_ai.request.model") or "").strip()
        if req_model:
            models[req_model] += 1
        prov = str(tags.get("gen_ai.provider.name") or tags.get("gen_ai.system") or "").strip()
        if prov:
            providers[prov] += 1
        fr = str(tags.get("gen_ai.response.finish_reasons") or tags.get("gen_ai.completion.0.finish_reason") or "").strip()
        if fr:
            finish_reasons[fr] += 1

        for k in TOKEN_CACHE_ATTRS:
            if "creation" in k:
                cache_create += _num(tags.get(k))
            else:
                cache_read += _num(tags.get(k))

        if _is_tool_span(tags):
            tools.append(
                {
                    "name": tags.get("gen_ai.tool.name") or "",
                    "type": tags.get("gen_ai.tool.type") or "",
                    "call_id": tags.get("gen_ai.tool.call.id") or "",
                }
            )

        if not _is_inference_span(op, tags):
            continue
        tin, tout = _token_in(tags), _token_out(tags)
        if tin <= 0 and tout <= 0:
            continue
        rid = str(tags.get("gen_ai.response.id") or "").strip()
        if rid:
            prev = token_by_response.get(rid, (0.0, 0.0))
            token_by_response[rid] = (max(prev[0], tin), max(prev[1], tout))
        else:
            orphan_tokens.append((tin, tout))

    tin = sum(t[0] for t in token_by_response.values()) + sum(t[0] for t in orphan_tokens)
    tout = sum(t[1] for t in token_by_response.values()) + sum(t[1] for t in orphan_tokens)

    return {
        "tokens_in": tin,
        "tokens_out": tout,
        "tokens_cache_read": cache_read,
        "tokens_cache_create": cache_create,
        "span_names": [n for n in names if n],
        "span_count": len(names),
        "conversation_id": labels["conversation_id"],
        "task_id": labels["task_id"],
        "flow": labels["flow"],
        "agent": labels["agent"],
        "scenario": labels["scenario"],
        "skill": labels["skill"],
        "models": dict(models),
        "providers": dict(providers),
        "operations": dict(operations),
        "finish_reasons": dict(finish_reasons),
        "tools": tools,
        "tool_names": sorted({t["name"] for t in tools if t.get("name")}),
        "errors": errors,
        "llm_calls": len(token_by_response) + len(orphan_tokens),
    }


def _parse_json(value: object) -> dict | list | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _unwrap_tool_payload(parsed: object) -> dict:
    if not isinstance(parsed, dict):
        return {}
    if isinstance(parsed.get("result"), dict):
        return parsed["result"]
    if isinstance(parsed.get("result"), str):
        inner = _parse_json(parsed["result"])
        if isinstance(inner, dict):
            return inner
    content = parsed.get("content")
    if isinstance(content, list) and content:
        text = str((content[0] or {}).get("text") or "")
        inner = _parse_json(text)
        if isinstance(inner, dict):
            return inner
    structured = parsed.get("structuredContent")
    if isinstance(structured, dict) and isinstance(structured.get("result"), str):
        inner = _parse_json(structured["result"])
        if isinstance(inner, dict):
            return inner
    return parsed if isinstance(parsed, dict) else {}


def _span_start_us(span: dict) -> float:
    v = span.get("startTime") or span.get("startTimeUnixNano")
    if v is None:
        return 0.0
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    if n > 1e15:
        return n / 1000.0
    return n


def _tool_calls_from_tags(tags: dict[str, str]) -> list[dict]:
    """LLM spans record planned tool calls before execute_tool spans."""
    found: list[tuple[int, int, str, str]] = []
    for key, raw in tags.items():
        m = re.match(r"gen_ai\.completion\.(\d+)\.tool_calls\.(\d+)\.(name|arguments)$", key)
        if not m:
            continue
        idx, sub, kind = int(m.group(1)), int(m.group(2)), m.group(3)
        found.append((idx, sub, kind, raw))
    by_call: dict[tuple[int, int], dict] = {}
    for idx, sub, kind, raw in found:
        slot = by_call.setdefault((idx, sub), {"name": "", "arguments": {}})
        if kind == "name":
            slot["name"] = raw
        else:
            args = _parse_json(raw)
            slot["arguments"] = args if isinstance(args, dict) else {}
    return list(by_call.values())


def _runtime_cfg(runtime_cfg: dict | None) -> dict:
    cfg = runtime_cfg if isinstance(runtime_cfg, dict) else {}
    pending = [str(x).strip() for x in (cfg.get("pending_tools") or []) if str(x).strip()]
    return {
        "publish_tool": str(cfg.get("publish_tool") or "").strip(),
        "publish_result_field": str(cfg.get("publish_result_field") or "sha").strip() or "sha",
        "artifact_markdown_field": str(cfg.get("artifact_markdown_field") or "report_markdown").strip()
        or "report_markdown",
        "pending_tools": frozenset(pending),
    }


def infer_runtime(spans: list[dict], runtime_cfg: dict | None = None) -> dict:
    """Derive job runtime facts from trace spans (tools, publish, pending, artifact)."""
    rcfg = _runtime_cfg(runtime_cfg)
    publish_tool = rcfg["publish_tool"]
    publish_field = rcfg["publish_result_field"]
    markdown_field = rcfg["artifact_markdown_field"]
    pending_tools = rcfg["pending_tools"]
    events: list[dict] = []
    artifact_markdown = ""

    for sp in spans:
        if not isinstance(sp, dict):
            continue
        tags = tag_map(sp)
        start = _span_start_us(sp)
        tool_name = str(tags.get("gen_ai.tool.name") or "").strip()

        for call in _tool_calls_from_tags(tags):
            name = str(call.get("name") or "").strip()
            if not name:
                continue
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            events.append(
                {
                    "start": start,
                    "name": name,
                    "phase": "planned",
                    "args": args,
                    "response": {},
                }
            )
            if publish_tool and name == publish_tool and isinstance(args.get(markdown_field), str):
                artifact_markdown = args[markdown_field]

        if tool_name:
            raw_resp = _first(tags, TOOL_RESPONSE_KEYS)
            payload = _unwrap_tool_payload(_parse_json(raw_resp) or {})
            raw_args = _first(tags, TOOL_ARGS_KEYS)
            args = _parse_json(raw_args)
            if not isinstance(args, dict):
                args = {}
            if publish_tool and tool_name == publish_tool and isinstance(args.get(markdown_field), str):
                artifact_markdown = args[markdown_field]
            events.append(
                {
                    "start": start,
                    "name": tool_name,
                    "phase": "executed",
                    "args": args,
                    "response": payload,
                }
            )

    events.sort(key=lambda e: e["start"])
    tools = [e["name"] for e in events if e.get("name")]
    last_tool = tools[-1] if tools else ""

    artifact = {"sha": None, "url": None, "path": None}
    publish_ok = False
    for ev in events:
        if publish_tool and ev["name"] != publish_tool:
            continue
        if not publish_tool:
            continue
        resp = ev.get("response") if isinstance(ev.get("response"), dict) else {}
        published_value = str(resp.get(publish_field) or "").strip()
        if published_value:
            publish_ok = True
            artifact = {
                "sha": published_value if publish_field == "sha" else str(resp.get("sha") or "") or None,
                "url": str(resp.get("html_url") or resp.get("url") or "") or None,
                "path": str(resp.get("path") or "") or None,
            }
        args = ev.get("args") if isinstance(ev.get("args"), dict) else {}
        md = args.get(markdown_field)
        if isinstance(md, str) and md:
            artifact_markdown = md

    if publish_ok and (artifact.get("sha") or publish_field != "sha"):
        status = "PUBLISHED"
    elif pending_tools and last_tool in pending_tools and not publish_ok:
        status = "BLOCKED_ON_USER"
    else:
        status = "INCOMPLETE"

    return {
        "tools": tools,
        "last_tool": last_tool,
        "tool_results": events,
        "store_report_ok": publish_ok,
        "publish_ok": publish_ok,
        "artifact": artifact,
        "artifact_markdown": artifact_markdown,
        "markdown": artifact_markdown,
        "status": status,
        "sha": artifact.get("sha"),
    }
