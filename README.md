# kaif-eval

kaif-eval turns **agent telemetry and related signals** into **eval jobs** — one record per run with **outcome**, **quality**, **spend**, and **labels**.

It is a configuration-driven measurement engine. For each **job id** (session / run id) it fetches evidence through **connectors**, applies **policy**, and writes a row to the **eval store**. **kaif-value** reads those jobs and exports business KPIs. kaif-eval does not own dashboards.

## What it does

1. **Joins signals on a correlation id** — OpenTelemetry traces and metrics, agent runtime sessions, published artifacts, and (where configured) business systems.
2. **Classifies outcome** — `success`, `failed`, or `pending` (for example: published to Git, ended without publish, waiting on a person).
3. **Scores quality** — weighted deterministic rules plus optional LLM-as-judge (G-Eval / DeepEval).
4. **Writes the eval store** — one job row per run for kaif-value and any consumer of `GET /v1/outcomes`.
5. **Stays vendor-agnostic** — Jaeger, Prometheus, kagent, and Gitea are bindings; policy references **source names**, not SDKs.

Everything operators declare lives in the **eval designer** (YAML today; UI and Kubernetes CRD on the roadmap).

## Why this exists

Agent platforms produce rich telemetry: spans, token counts, tool calls, latency. That answers *what happened*, but not:

- Did the agent **finish the business task**?
- Was the output **good enough**?
- What is the **return on spend** for completed vs unfinished work?

The agent-eval space is large and fast-moving (observability UIs, DeepEval, Ragas, LangSmith, runtime hooks). Teams should not embed a judge in every agent or marry measurement to one vendor.

kaif-eval fills three gaps:

| Gap | What kaif-eval does |
|-----|---------------------|
| **Telemetry ≠ business outcome** | Correlates traces + artifacts + runtime into outcome and quality on a **job record** |
| **Tool churn** | **Connectors** and **sources** abstract backends; engines stay vendor-blind |
| **Operability** | **Eval designer** + worker jobs (CLI/API/schedule/events) with OOB rules and pluggable BYO eval |

**kaif-eval writes** jobs. **kaif-value reports** on them. See [kaif-value](https://github.com/aiverse-brnavneet-in/kaif-value) for the read path.

## How it fits

![kaif-eval overview — signals, engine, eval store, kaif-value](docs/diagrams/01-kaif-eval-overview.png)

Signals flow into the **kaif-eval** engine (eval designer + worker job), which measures **outcome** and **quality** and writes the **eval store**. **kaif-value** reads that store and exports KPIs to dashboards or any HTTP consumer.

| Component | Role |
|-----------|------|
| **Signals** | Telemetry, runtimes, artifacts, business apps — read-only evidence |
| **Eval designer** | Session id, labels, connectors, sources, store schema, worker config, policies |
| **Worker job** | One job id in → measure → one store row out |
| **Eval store** | Jobs ledger (SQLite or PostgreSQL) |
| **kaif-value** | KPIs and HTTP export |

## Architecture diagrams

| # | Diagram | What it shows |
|---|---------|---------------|
| 1 | [Overview](docs/diagrams/01-kaif-eval-overview.excalidraw) | End-to-end: signals → kaif-eval → kaif-value |
| 2 | [Eval designer](docs/diagrams/02-eval-designer.excalidraw) | Mother-file components (session id, labels, connectors, sources, policies, store, worker) |
| 3 | [Worker job](docs/diagrams/03-worker-job.excalidraw) | Triggers (CLI, API, schedule, events) and job pipeline |
| 4 | [Correlation engine](docs/diagrams/04-correlation-engine.excalidraw) | OTel telemetry, correlation id, outcome and quality measurement |

### 1 — Overview

![kaif-eval overview](docs/diagrams/01-kaif-eval-overview.png)

### 2 — Eval designer

![Eval designer mother file](docs/diagrams/02-eval-designer.png)

### 3 — Worker job

![Worker triggers and pipeline](docs/diagrams/03-worker-job.png)

### 4 — Correlation engine

![OTel correlation and quality measurement](docs/diagrams/04-correlation-engine.png)

Editable source: open `.excalidraw` files in the [Excalidraw VS Code extension](https://marketplace.visualstudio.com/items?itemName=pomdtr.excalidraw-editor) or at [excalidraw.com](https://excalidraw.com). Mermaid fallback: [docs/diagrams/preview.md](docs/diagrams/preview.md). Regenerate: `python3 docs/build_excalidraw_diagrams.py`.

Deeper narrative: [docs/kaif-eval-architecture-design.md](docs/kaif-eval-architecture-design.md) · [docs/kaif-eval-product.md](docs/kaif-eval-product.md)

## Prerequisites

Before kaif-eval can produce trustworthy jobs, the platform needs:

| # | Requirement | Why |
|---|-------------|-----|
| 1 | **Observability** — OTel Collector exporting to trace and metrics backends (for example Jaeger, Prometheus) | Primary evidence plane |
| 2 | **Trace sampling** — full sampling recommended in lab so tool and publish spans are not dropped | Partial sampling hides outcome signals |
| 3 | **GenAI span attributes** — conversation or task id on spans ([OTel GenAI conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)) | Trace queries key off stable attributes |
| 4 | **Correlation contract** — one unique **job id** per run, propagated via header and span attributes (declared in eval designer) | Joins telemetry with artifacts and runtime |
| 5 | **Eval store** — SQLite (local) or PostgreSQL (shared / cluster) | Job ledger for kaif-value |

Verify observability reachability:

```bash
python3 deploy/scripts/check_prereqs.py --jaeger-url "$JAEGER_URL" --prometheus-url "$PROMETHEUS_URL"
```

Correlation is declared in eval designer (`session_id` / `session_id.trace`). The OOTB demo binds `X-Kaif-Run-Id` and `gen_ai.conversation.id` — see [docs/eval-designer.md](docs/eval-designer.md).

## Quick start

Python **3.9+**. Commands below are from the **repo root**.

Clone:

```bash
git clone https://github.com/aiverse-brnavneet-in/kaif-eval.git
cd kaif-eval
```

### Manual — local CLI

Install into a venv and evaluate one job by id:

```bash
python3 deploy/install.py
```

Port-forward or point at your trace UI (example: Jaeger on 16686):

```bash
export JAEGER_URL=http://127.0.0.1:16686
export KAIF_EVAL_DB=/tmp/kaif-eval.db
```

Run eval for a known session id (must exist in traces):

```bash
.venv/bin/kaif-eval --config demo/eval.yaml --job-id <session-uuid>
```

On Windows:

```bash
.venv\Scripts\kaif-eval.exe --config demo/eval.yaml --job-id <session-uuid>
```

Without installing the console script:

```bash
PYTHONPATH=. .venv/bin/python -m app.worker --config demo/eval.yaml --job-id <session-uuid>
```

PostgreSQL store:

```bash
export KAIF_EVAL_STORE_URL="postgresql://USER:PASSWORD@HOST:5432/kaif_eval"
# configure store.connection in your eval designer overlay
```

Do not commit database URLs or API keys.

### Manual — full architecture demo (cluster)

When a KAIF agent cluster is available, the demo driver mints a job id, sends an A2A message, waits for traces, and runs kaif-eval:

```bash
python3 deploy/install.py
export JAEGER_URL=http://127.0.0.1:16686
# optional: source demo/scripts/load-eval-llm-env.sh for G-Eval judge
python3 demo/flows/architecture/run-job.py
```

Settings: `demo/flows/architecture/run-config.yaml`. Policy and quality rubric: `demo/flows/architecture/policy.yaml`.

### Docker

```bash
python3 deploy/install.py docker
# docker run with demo config and job id — see deploy/Dockerfile
```

### Kubernetes (Helm)

Stage config (OOTB demo overlay with `--demo`):

```bash
python3 deploy/install.py helm --demo
helm upgrade --install kaif-eval ./deploy -n <namespace> --set jobId=<session-uuid>
```

Set store URL and Jaeger URL via chart values / secrets — never commit real credentials.

### After eval

Inspect the job row (SQLite example):

```bash
sqlite3 "$KAIF_EVAL_DB" "SELECT job_id, outcome, evaluation FROM jobs ORDER BY rowid DESC LIMIT 1;"
```

Point **kaif-value** at the same store and call `GET /v1/outcomes` to see KPIs.

## Use with a coding agent (Cursor, Claude Code, Codex)

Open **this repository folder** in your agent IDE. Point the agent at **[AGENTS.md](AGENTS.md)** and say:

```text
Follow AGENTS.md. Install kaif-eval locally, verify prerequisites, and run eval for job id <uuid>.
```

The agent should:

1. Run `python3 deploy/install.py`
2. Run `deploy/scripts/check_prereqs.py` with your Jaeger/Prometheus URLs
3. Confirm `JAEGER_URL`, `KAIF_EVAL_DB` (or Postgres URL), and `demo/eval.yaml`
4. Run `kaif-eval --config demo/eval.yaml --job-id <uuid>` or `demo/flows/architecture/run-job.py` when a cluster is available

It must not guess cluster endpoints or commit secrets. For layout and rules (templates in `config/`, bindings in `demo/`), see AGENTS.md.

You can skip the agent and use the manual commands above.

## Configuration layers

| Layer | Location | Content |
|-------|----------|---------|
| Eval designer (template) | `config/eval-designer.yaml` | Mother file — connector schemas, designer modules |
| Designer modules | `config/designer/*.yaml` | session_id, labels, store, worker, evidence |
| Connector schemas | `config/connectors/*.yaml` | Protocol templates (no tenant URLs) |
| OOTB overlay | `demo/eval.yaml` | `include: ../config/eval-designer.yaml` + demo sources and policy |
| Flow policy | `demo/flows/*/policy.yaml` | Outcome, quality, runtime tool mapping |

Product surface: [docs/eval-designer.md](docs/eval-designer.md). Store contract with kaif-value: [docs/evaldbschema.txt](docs/evaldbschema.txt).

## Layout

| Path | What it is |
|------|------------|
| `app/` | Engine — worker, connectors, outcomes, quality, store |
| `app/connectors/` | One Python module per connector (`jaeger`, `kagent`, `prometheus`, `gitea`, `llm`, `api`) |
| `config/` | Product templates — eval designer, connectors, sources, schema |
| `demo/` | OOTB bindings — sources, designer overlays, architecture flow, Grafana samples |
| `deploy/` | `install.py`, Dockerfile, Helm chart, `check_prereqs.py` |
| `docs/` | Architecture design, product doc, Excalidraw diagrams |
| `tests/` | Unit tests (no cluster required) |

## Roadmap by component

### Connectors

| Status | Systems |
|--------|---------|
| **Now** | **jaeger** (traces), **prometheus** (metrics), **kagent** (sessions), **gitea** (Git artifacts), **llm** (G-Eval judge), **api** (generic HTTP), eval store via **postgres** / SQLite |
| **Next** | GitHub, GitLab, Bitbucket; Tempo; Langfuse / LangSmith as trace or eval sources |
| **Later** | MySQL, Elasticsearch, Redis; S3, Azure Blob; Jira, ServiceNow, Salesforce; Confluence; Slack, MS Teams; Google Drive, Nexus; NVIDIA NIM, Google ADK, CrewAI, LangGraph runtime APIs |

Connectors are **types**. Sources are **named instances** in your overlay.

### Eval designer

| Status | Surface |
|--------|---------|
| **Now** | YAML mother file + modular fragments (`config/designer/`, `demo/designer/`) |
| **Next** | `EvalDesigner` Kubernetes CRD (`apiVersion: kaif.dev/v1alpha1`) |
| **Later** | UI wizard; validating admission webhook for schema and source refs |

### Worker jobs

| Status | Trigger |
|--------|---------|
| **Now** | On-demand CLI (`kaif-eval --job-id <uuid>`) |
| **Next** | HTTP API (`POST /v1/eval/run`); scheduled poll / cron |
| **Later** | Event-driven — Kafka, AWS SNS, Argo Events, Kubernetes watches |

Pipeline (all triggers): config load → validation → fetch evidence → policy engines → write eval store. See [worker job diagram](docs/diagrams/03-worker-job.png).

### Eval (outcome + quality)

| Status | Capability |
|--------|------------|
| **Now** | Deterministic rules (weighted, per-rule breakdown); DeepEval G-Eval LLM-as-judge; skip judge when outcome ≠ success |
| **Next** | Additional G-Eval metrics; richer runtime inference from GenAI spans |
| **Later** | BYO frameworks (Ragas, Phoenix, custom HTTP judges); design-time and build-time eval on the same store |

### Eval store

| Status | Capability |
|--------|------------|
| **Now** | SQLite and PostgreSQL; configurable DDL via eval designer `store.schema` |
| **Next** | Schema versioning contract with kaif-value |
| **Later** | Multi-tenant isolation; cross-job analytics connectors |

## Documentation

| Doc | Purpose |
|-----|---------|
| [kaif-eval-architecture-design.md](docs/kaif-eval-architecture-design.md) | Public architecture — goals, concepts, prerequisites |
| [kaif-eval-product.md](docs/kaif-eval-product.md) | Product — why, gap, requirements, connector roadmap |
| [eval-designer.md](docs/eval-designer.md) | Mother file and CRD mapping |
| [gen-ai-trace-eval.md](docs/gen-ai-trace-eval.md) | Span attributes for trace-based eval |
| [diagrams/README.md](docs/diagrams/README.md) | PNG exports and how to open Excalidraw sources |

## License

[Apache License 2.0](LICENSE)
