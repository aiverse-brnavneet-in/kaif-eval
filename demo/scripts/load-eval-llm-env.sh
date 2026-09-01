#!/usr/bin/env bash
# Export KAIF_EVAL_LLM_* for the G-Eval judge. Does not print secrets.
#
# Upstream: agentgateway /llm-eval-glm → Vercel AI Gateway zai/glm-5.2
# Auth: same AI_GATEWAY_API_KEY as agentgateway-system/vercel-ai-gateway
#
# Usage:  set -a; source scripts/load-eval-llm-env.sh; set +a
set -euo pipefail

GW_IP="${KAIF_AGW_IP:-}"
if [[ -z "$GW_IP" ]]; then
  GW_IP="$(kubectl -n agentgateway-system get svc agentgateway-proxy \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
fi
if [[ -z "$GW_IP" ]]; then
  GW_IP="192.168.64.2"
fi

export KAIF_EVAL_LLM_URL="${KAIF_EVAL_LLM_URL:-http://${GW_IP}:8090/llm-eval-glm}"
export KAIF_EVAL_LLM_MODEL="${KAIF_EVAL_LLM_MODEL:-zai/glm-5.2}"

# Client key is dummy: agentgateway injects vercel-ai-gateway (same Vercel AI Gateway key
# as /llm). Set KAIF_EVAL_PASS_VERCEL_KEY=1 only if you must send the real key from the laptop.
if [[ -z "${KAIF_EVAL_LLM_KEY:-}" ]]; then
  if [[ "${KAIF_EVAL_PASS_VERCEL_KEY:-}" == "1" ]]; then
    ENV_FILE="${KAIF_API_KEYS_ENV:-/Users/navneet/Documents/MyWorkspace/.secret/kaif-api-keys.env}"
    if [[ -f "$ENV_FILE" ]]; then
      # shellcheck disable=SC1090
      set -a
      source "$ENV_FILE"
      set +a
      export KAIF_EVAL_LLM_KEY="${AI_GATEWAY_API_KEY:-}"
    fi
  fi
  export KAIF_EVAL_LLM_KEY="${KAIF_EVAL_LLM_KEY:-not-needed}"
fi

echo "KAIF_EVAL_LLM_URL=$KAIF_EVAL_LLM_URL"
echo "KAIF_EVAL_LLM_MODEL=$KAIF_EVAL_LLM_MODEL"
echo "KAIF_EVAL_LLM_KEY=set"
