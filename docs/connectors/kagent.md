# kagent connector

`app/connectors/kagent.py` implements the **kagent** connector type.

kagent is a **named source** in eval config (e.g. `demo/sources/kagent-sessions.yaml`). Eval does not list sessions — it fetches `GET /api/sessions/{session_id}` keyed by the caller's job id.

| Role | Typical source name (demo) | Used for |
|------|---------------------------|----------|
| Runtime | `kagent-sessions` | Session events, tools, artifact, clock |
| Traces | `jaeger-traces` | Primary outcome/quality path in architecture POC |

Correlation header and span attributes are defined in `demo/designer/session_id.yaml`, not in the connector Python code.
