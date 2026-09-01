# Demo: architecture workflow (software-architect)

OOTB configuration for the local POC. **Not** part of the product runtime — copy patterns into your own policies.

| Path | Purpose |
|------|---------|
| `eval.yaml` | Includes `config/eval-designer.yaml` + architecture policy + git artifacts source |
| `flows/architecture/policy.yaml` | Outcomes, quality, runtime tool mapping, scenario inference |
| `sources/git-artifacts.yaml` | Gitea published markdown (optional corroboration) |
| `flows/architecture/run-job.py` | Mint job_id, A2A send, eval worker (needs cluster port-forwards) |
| `flows/architecture/prompts/` | Sample prompts for pending/publish runs |
| `grafana/` | KAIF Evals dashboards (consumed by kaif-value) |
| `scripts/load-eval-llm-env.sh` | Optional judge LLM env from cluster secrets |

## Prerequisites

1. **Observability stack** — OTel Collector → Jaeger + Prometheus (see `config/global.yaml` `prerequisites`).
2. **100% trace sampling** in lab (`tracing.sampling: "1.0"`).
3. **Unique session_id** per run, injected as `X-Kaif-Run-Id` and `kaif.run_id` span attribute (`config/eval-designer.yaml` `session_id.trace`).

## Quick run

```bash
export JAEGER_URL=http://127.0.0.1:16686
export KAIF_EVAL_DB=/tmp/kaif-eval.db
kaif-eval --config demo/eval.yaml --job-id <session-uuid>
```
