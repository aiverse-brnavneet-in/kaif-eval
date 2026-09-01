"""Tests for OTel GenAI span aggregation."""

from app.gen_ai_trace import aggregate_spans, infer_runtime, tag_map
from app.connectors.jaeger import fetch_job


def test_tag_map_jaeger_format():
    span = {
        "tags": [
            {"key": "gen_ai.conversation.id", "value": "sess-1", "type": "string"},
            {"key": "gen_ai.usage.input_tokens", "value": 100, "type": "int64"},
        ]
    }
    m = tag_map(span)
    assert m["gen_ai.conversation.id"] == "sess-1"
    assert m["gen_ai.usage.input_tokens"] == "100"


def test_token_dedupe_by_response_id():
    spans = [
        {
            "operationName": "openai.chat",
            "tags": [
                {"key": "gen_ai.response.id", "value": "resp-1"},
                {"key": "gen_ai.usage.input_tokens", "value": 1000},
                {"key": "gen_ai.usage.output_tokens", "value": 50},
                {"key": "gen_ai.operation.name", "value": "chat"},
            ],
        },
        {
            "operationName": "POST /llm-failover",
            "tags": [
                {"key": "gen_ai.response.id", "value": "resp-1"},
                {"key": "gen_ai.usage.prompt_tokens", "value": 1000},
                {"key": "gen_ai.usage.completion_tokens", "value": 50},
                {"key": "gen_ai.request.model", "value": "gpt-test"},
            ],
        },
    ]
    agg = aggregate_spans(spans)
    assert agg["tokens_in"] == 1000
    assert agg["tokens_out"] == 50
    assert agg["llm_calls"] == 1


def test_tool_spans_extracted():
    spans = [
        {
            "operationName": "execute_tool web_search",
            "tags": [
                {"key": "gen_ai.tool.name", "value": "web_search"},
                {"key": "gen_ai.tool.type", "value": "function"},
                {"key": "gen_ai.operation.name", "value": "execute_tool"},
            ],
        }
    ]
    agg = aggregate_spans(spans)
    assert "web_search" in agg["tool_names"]


def test_infer_runtime_pending():
    runtime_cfg = {
        "publish_tool": "store_report",
        "pending_tools": ["ask_user"],
    }
    spans = [
        {
            "startTime": 1000,
            "tags": [
                {"key": "gen_ai.tool.name", "value": "ask_user"},
                {"key": "gcp.vertex.agent.tool_response", "value": '{"result": "<not specified>"}'},
            ],
        }
    ]
    rt = infer_runtime(spans, runtime_cfg)
    assert rt["last_tool"] == "ask_user"
    assert rt["status"] == "BLOCKED_ON_USER"
    assert not rt["publish_ok"]


def test_infer_runtime_published():
    runtime_cfg = {
        "publish_tool": "store_report",
        "artifact_markdown_field": "report_markdown",
    }
    spans = [
        {
            "startTime": 2000,
            "tags": [
                {"key": "gen_ai.tool.name", "value": "store_report"},
                {
                    "key": "gcp.vertex.agent.tool_response",
                    "value": '{"sha":"abc123","html_url":"https://example.com/r.md","path":"reports/r.md"}',
                },
                {
                    "key": "gcp.vertex.agent.tool_call_args",
                    "value": '{"report_markdown":"# Architecture\\n\\n## STATUS\\nPUBLISHED"}',
                },
            ],
        }
    ]
    rt = infer_runtime(spans, runtime_cfg)
    assert rt["publish_ok"]
    assert rt["status"] == "PUBLISHED"
    assert rt["artifact"]["sha"] == "abc123"
    assert "Architecture" in rt["markdown"]


def test_fetch_job_empty():
    out = fetch_job("", "job-1")
    assert not out["ok"]
    assert out["error"] == "missing_jaeger_or_job_id"
