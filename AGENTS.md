# Agent layout

| Path | Owns |
|------|------|
| `app/` | Engine — `worker`, `connectors/*`, `outcomes`, `quality`, `store` |
| `app/connectors/` | **One Python module per connector** (`jaeger.py`, `kagent.py`, …) |
| `config/` | Raw templates only — connectors, source templates, designer modules, global |
| `config/designer/` | Modular eval-designer fragments (`session_id`, `labels`, `fetch`) |
| `demo/` | POC bindings — concrete sources, designer overlays, policies, prompts |
| `deploy/` | install.py, Dockerfile, Helm |
| `docs/` | Product overview and connector guides |

**Rule:** POC names (`X-Kaif-Run-Id`, `jaeger-traces`, `software_architect`) live in `demo/` only.

**Entry point:** `kaif-eval --config demo/eval.yaml --job-id <uuid>`
