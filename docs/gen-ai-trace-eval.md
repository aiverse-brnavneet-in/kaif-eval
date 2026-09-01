# GenAI trace fields for kaif-eval

**Spec:** [OTel GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md) (as of 2026-09).

KAIF traces are produced by **kagent** (ADK / OpenInference) and **agentgateway** (LLM gateway). The eval spine reads them from **Jaeger** via `jaeger-traces` source.

## Session lookup

| Priority | Jaeger tag | Notes |
|----------|------------|--------|
| 1 | `gen_ai.conversation.id` | kagent UI / A2A `contextId` — **use this** |
| 2 | `kaif.run_id` | Set when caller sends `X-Kaif-Run-Id` (often empty today) |
| 3 | `gen_ai.task.id` | Single user turn / task |

Configure: `KAIF_TRACE_ATTR` or `sources/jaeger-traces.yaml`.

## Coverage matrix

| OTel GenAI area | Attribute(s) | Emitted on RD? | Extracted to `gen_ai` blob? |
|-----------------|--------------|----------------|----------------------------|
| **Conversation** | `gen_ai.conversation.id` | Yes (kagent) | Yes |
| **Task / turn** | `gen_ai.task.id` | Yes | Yes |
| **Operation** | `gen_ai.operation.name` | Yes (`chat`, tool spans) | Yes → `operations` |
| **System / provider** | `gen_ai.system`, `gen_ai.provider.name` | Yes | Yes → `providers` |
| **Models** | `gen_ai.request.model`, `gen_ai.response.model` | Yes (agentgateway + kagent) | Yes → `models` |
| **Response id** | `gen_ai.response.id` | Yes | Used to dedupe token double-count |
| **Finish reason** | `gen_ai.response.finish_reasons`, `gen_ai.completion.*.finish_reason` | Yes | Yes → `finish_reasons` |
| **Input tokens** | `gen_ai.usage.input_tokens`, `gen_ai.usage.prompt_tokens` | Yes | Yes → `tokens_in` |
| **Output tokens** | `gen_ai.usage.output_tokens`, `gen_ai.usage.completion_tokens` | Yes | Yes → `tokens_out` |
| **Cache tokens** | `gen_ai.usage.cache_read.input_tokens`, `cache_creation.input_tokens` | Sometimes | Yes |
| **Tool execution** | `gen_ai.tool.name`, `.type`, `.call.id` | Yes (MCP tools) | Yes → `tools`, `tool_names` |
| **Agent** | `gen_ai.agent.name`, `.description` | Yes (kagent) | Yes → `agent` fallback |
| **Prompt / completion body** | `gen_ai.prompt.*.content`, `gen_ai.completion.*.content` | Yes when `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` | Not stored in eval card (PII); available in Jaeger UI |
| **Embeddings** | `gen_ai.operation.name=embeddings` | Not in current agents | Ready when added |
| **Retrieval** | retrieval spans | Not yet | — |

## KAIF extensions (not in OTel spec)

| Attribute | Source | Extracted |
|-----------|--------|-----------|
| `kaif.flow` | agentgateway headers / inject | Yes → `flow` |
| `kaif.agent` | agentgateway headers | Yes → `agent` |
| `kaif.scenario` | header or body `kaif_scenario` | Yes → `scenario` |
| `kaif.skill` | header or active skill inject | Yes → `skill` |
| `kaif.tool` | header | Span-level only |
| `kaif.run_id` | `X-Kaif-Run-Id` | Search fallback |

## Token deduplication

One LLM call produces spans in **both** agent runtime (`openai.chat`) and LLM gateway (`POST /llm-failover-*`). `app.gen_ai_trace` dedupes by `gen_ai.response.id` before summing tokens.

## Jaeger UI

```text
# All traces for one chat session
gen_ai.conversation.id=<session-uuid>

# One agent
kaif.agent=software-architect

# LLM calls only (manual filter)
gen_ai.operation.name=chat
```

## Eval worker fields

`jaeger-traces` payload includes top-level `tokens_in`, `tokens_out`, `flow`, `agent`, `scenario`, `skill`, `duration_s`, plus nested `gen_ai` with models, tools, operations, and errors.

Spend (`usd_est`) is computed in the worker from `tokens_in/out` and agent rate card — not from span cost attributes (agentgateway cost metrics stay in Prometheus).

## Trace-only outcome and judge input

Without kagent session API, `infer_runtime()` derives job facts from spans:

| Eval need | Trace signal | Rule |
|-----------|--------------|------|
| **Pending** | `gen_ai.tool.name=ask_user` (or `adk_request_confirmation`) is the last executed tool; no `store_report` sha | `status=BLOCKED_ON_USER` |
| **Published** | `store_report` execute span; `gcp.vertex.agent.tool_response` JSON contains `sha` | `store_report_ok` + `artifact.sha` |
| **Tools called** | `gen_ai.tool.name` on execute spans + `gen_ai.completion.*.tool_calls.*` on LLM spans | `tools[]`, `last_tool` |
| **Judge markdown** | `gcp.vertex.agent.tool_call_args` / LLM tool-call args: `report_markdown` on `store_report` | `markdown` / `artifact_markdown` |

Policy (`architecture.yaml`) now uses `jaeger-traces` for success, pending, deterministic quality, and G-Eval `input.source`. Gitea (`architect-published-doc`) remains optional fallback when traces lack markdown.

Jaeger search uses `tag=gen_ai.conversation.id:<job_id>&service=software_architect` (not JSON `tags=` — that returns 400).
