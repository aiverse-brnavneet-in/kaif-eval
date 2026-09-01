"""DeepEval G-Eval adapter: one named metric per YAML rule.

Uses GEval (https://deepeval.com/docs/metrics-llm-evals), not a custom prompt
parser. Each rule is GEval(name=..., evaluation_steps XOR criteria). The
document under test is the Gitea artifact (actual_output), never a hardcoded path.

Scores are DeepEval-native 0–1. The quality rule still applies field/op/value.
"""

from __future__ import annotations

import json
import os
import re
import sys
import typing

from app.http import http_json


def _enable_pep604_unions() -> None:
    """DeepEval 4.2 still claims Python 3.9 but uses `X | Y` type aliases at runtime.

    See https://github.com/confident-ai/deepeval/issues/2049 — without this,
    `from deepeval.metrics import GEval` raises TypeError on 3.9.
    """
    if sys.version_info >= (3, 10):
        return

    def _or(left, right):
        return typing.Union[left, right]

    for name in (
        "_GenericAlias",
        "_LiteralGenericAlias",
        "_SpecialGenericAlias",
        "_UnionGenericAlias",
        "_SpecialForm",
    ):
        cls = getattr(typing, name, None)
        if cls is None:
            continue
        try:
            cls.__or__ = _or  # type: ignore[attr-defined]
        except Exception:
            continue


def _prepare_deepeval() -> None:
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
    _enable_pep604_unions()


def _step_text(item) -> str:
    if isinstance(item, dict):
        return "; ".join("%s: %s" % (k, v) for k, v in item.items() if str(v).strip())
    return str(item).strip()


def criterion_slug(step: str) -> str:
    """Prom-safe name from an evaluation_step (text before ':' if present)."""
    text = (step or "").strip()
    if ":" in text:
        text = text.split(":", 1)[0]
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (slug or "criterion")[:64]


def criteria_and_steps(rule: dict) -> tuple[str, list]:
    """YAML: evaluation_steps XOR criteria (DeepEval). prompt is an alias for criteria.

    If both are set, evaluation_steps wins — DeepEval forbids passing both.
    """
    raw = rule.get("evaluation_steps")
    steps: list = []
    if isinstance(raw, list):
        steps = [_step_text(s) for s in raw]
        steps = [s for s in steps if s]
    elif isinstance(raw, str) and raw.strip():
        steps = [ln.lstrip("- ").strip() for ln in raw.splitlines() if ln.strip()]
    criteria = str(rule.get("criteria") or "").strip()
    if not criteria:
        criteria = str(rule.get("prompt") or "").strip()
    if steps:
        criteria = ""
    return criteria, steps


def _parse_json_obj(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    blob = fence.group(1) if fence else raw
    start, end = blob.find("{"), blob.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(blob[start : end + 1])
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _num(v, default=0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _est_tokens(text: str) -> float:
    return float(max(1, (len(text or "") + 3) // 4))


def _usage_tokens(body: dict) -> tuple[float | None, float | None]:
    u = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    tin = u.get("prompt_tokens")
    if tin is None:
        tin = u.get("input_tokens")
    if tin is None:
        tin = u.get("promptTokens")
    tout = u.get("completion_tokens")
    if tout is None:
        tout = u.get("output_tokens")
    if tout is None:
        tout = u.get("completionTokens")
    if tin is None:
        tin = body.get("prompt_tokens")
    if tin is None:
        tin = body.get("input_tokens")
    if tout is None:
        tout = body.get("completion_tokens")
    if tout is None:
        tout = body.get("output_tokens")
    try:
        tin_n = float(tin) if tin is not None and tin != "" else None
    except (TypeError, ValueError):
        tin_n = None
    try:
        tout_n = float(tout) if tout is not None and tout != "" else None
    except (TypeError, ValueError):
        tout_n = None
    return tin_n, tout_n


def price_tokens(src: dict, tokens_in: float, tokens_out: float) -> float:
    """USD from sources.llm rates_usd_per_million (OpenAI-style per 1M tokens)."""
    rates = src.get("rates_usd_per_million") if isinstance(src.get("rates_usd_per_million"), dict) else {}
    rin = _num(rates.get("input"), 0.25)
    rout = _num(rates.get("output"), 2.0)
    return round(float(tokens_in or 0) * rin / 1e6 + float(tokens_out or 0) * rout / 1e6, 6)


def kaif_llm_headers(src: dict) -> dict:
    """Same Prom/trace headers as kagent ModelConfig defaultHeaders.

    Gateway policy copies X-Kaif-Flow/Agent/Tool onto kaif_flow/kaif_agent/kaif_tool.
    Run-id / scenario / skill are span attrs only (not Prometheus).
    """
    src = src if isinstance(src, dict) else {}
    labels = src.get("labels") if isinstance(src.get("labels"), dict) else {}
    pairs = (
        ("flow", "X-Kaif-Flow"),
        ("agent", "X-Kaif-Agent"),
        ("tool", "X-Kaif-Tool"),
        ("scenario", "X-Kaif-Scenario"),
        ("skill", "X-Kaif-Skill"),
        ("run_id", "X-Kaif-Run-Id"),
    )
    hdrs = {}
    for key, name in pairs:
        val = str(labels.get(key) or src.get("kaif_" + key) or "").strip()
        if val:
            hdrs[name] = val
    extra = src.get("headers")
    if isinstance(extra, dict):
        for k, v in extra.items():
            if str(v).strip():
                hdrs[str(k)] = str(v).strip()
    hdrs.setdefault("X-Kaif-Tool", "llm-eval")
    return hdrs


class CompatibleChatModel:
    """OpenAI-compatible chat wrapper for DeepEvalBaseLLM (endpoint from sources.llm)."""

    def __init__(self, src: dict):
        self.src = src if isinstance(src, dict) else {}
        self.endpoint = str(self.src.get("endpoint") or "").rstrip("/")
        self.model = str(self.src.get("model") or "")
        self.api_key = str(self.src.get("api_key") or self.src.get("token") or "")
        self.timeout_s = float(self.src.get("timeout_s") or 60)
        self.token_limit = int(self.src.get("token_limit") or 8000)
        self.tokens_in = 0.0
        self.tokens_out = 0.0
        self.calls = 0
        self.usage_source = "none"

    def _record(self, prompt: str, content: str, body: dict | None) -> None:
        self.calls += 1
        tin = tout = None
        if isinstance(body, dict):
            tin, tout = _usage_tokens(body)
        if tin is None or tout is None:
            tin = _est_tokens(prompt) if tin is None else tin
            tout = _est_tokens(content) if tout is None else tout
            self.usage_source = "estimated"
        elif self.usage_source == "none":
            self.usage_source = "api"
        self.tokens_in += float(tin or 0)
        self.tokens_out += float(tout or 0)

    def complete(self, prompt: str) -> str:
        url = self.endpoint
        if not url.endswith("/chat/completions"):
            url = self.endpoint + "/chat/completions"
        # GLM-5.2 thinks by default; G-Eval needs message.content, not CoT.
        # Vercel OpenAI-compat: reasoning.enabled=false
        # (https://vercel.com/ai-gateway/models/glm-5.2, https://docs.z.ai/guides/capabilities/thinking)
        req = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": min(1600, self.token_limit),
            "messages": [{"role": "user", "content": prompt}],
            "reasoning": {"enabled": False},
        }
        extra = self.src.get("extra_body")
        if isinstance(extra, dict):
            req.update(extra)
        try:
            body = http_json(
                url,
                method="POST",
                body=req,
                bearer=self.api_key,
                timeout=self.timeout_s,
                headers=kaif_llm_headers(self.src),
            )
        except Exception:
            return ""
        if not isinstance(body, dict):
            return ""
        choices = body.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(msg.get("content") or "")
            if not content.strip():
                content = str(msg.get("reasoning") or msg.get("reasoning_content") or "")
        self._record(prompt, content, body)
        return content


def _deepeval_model(chat: CompatibleChatModel):
    _prepare_deepeval()
    try:
        from deepeval.models import DeepEvalBaseLLM
    except ImportError:
        from deepeval.models.base_model import DeepEvalBaseLLM

    class OpenAICompatibleJudge(DeepEvalBaseLLM):
        def __init__(self):
            super().__init__(model=chat.model or "openai-compatible")

        def load_model(self):
            return chat

        def get_model_name(self):
            return chat.model or "openai-compatible"

        def generate(self, prompt: str, schema=None, **kwargs):
            text = chat.complete(str(prompt))
            if schema is None:
                return text
            obj = _parse_json_obj(text)
            try:
                return schema.model_validate(obj)
            except Exception:
                try:
                    return schema(**obj)
                except Exception as exc:
                    raise ValueError("judge JSON did not match schema: %s" % exc) from exc

        async def a_generate(self, prompt: str, schema=None, **kwargs):
            return self.generate(prompt, schema=schema, **kwargs)

    return OpenAICompatibleJudge()


def _cost_fields(src: dict, chat: CompatibleChatModel | None) -> dict:
    if chat is None:
        return {
            "tokens_in": 0.0,
            "tokens_out": 0.0,
            "usd_est": 0.0,
            "model": str((src or {}).get("model") or ""),
            "calls": 0,
            "usage_source": "none",
        }
    return {
        "tokens_in": round(chat.tokens_in, 1),
        "tokens_out": round(chat.tokens_out, 1),
        "usd_est": price_tokens(src, chat.tokens_in, chat.tokens_out),
        "model": chat.model,
        "calls": chat.calls,
        "usage_source": chat.usage_source,
    }


def g_eval(src: dict, document: str, rule: dict, prompt: str = "") -> dict:
    """Run one DeepEval GEval for this named metric.

    https://deepeval.com/docs/metrics-llm-evals — name + evaluation_steps XOR criteria.
    """
    empty = {
        "ok": False,
        "score": None,
        "tokens_in": 0.0,
        "tokens_out": 0.0,
        "usd_est": 0.0,
        "criteria": [],
    }
    if not src.get("enabled"):
        return {**empty, "error": "llm_disabled"}
    if not str(src.get("endpoint") or "").strip() or not str(src.get("model") or "").strip():
        return {**empty, "error": "llm_unconfigured"}
    criteria, steps = criteria_and_steps(rule)
    if prompt and not criteria and not steps:
        criteria = str(prompt).strip()
    if not criteria and not steps:
        return {**empty, "error": "missing_criteria"}
    doc = document or ""
    limit = int(src.get("token_limit") or 8000)
    max_chars = max(500, limit * 3)
    if len(doc) > max_chars:
        doc = doc[:max_chars]
    try:
        _prepare_deepeval()
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase
        try:
            from deepeval.test_case import SingleTurnParams as _Params
        except ImportError:
            from deepeval.test_case import LLMTestCaseParams as _Params
    except (ImportError, TypeError):
        return {**empty, "error": "deepeval_missing"}

    inp = rule.get("input") if isinstance(rule.get("input"), dict) else {}
    task = str(inp.get("task") or "Evaluate the architecture document in actual_output.")
    display = str(rule.get("name") or "quality_of_output").strip() or "quality_of_output"
    slug = criterion_slug(display)
    chat = CompatibleChatModel(src)
    case = LLMTestCase(input=task, actual_output=doc)

    kwargs = {
        "name": display,
        "evaluation_params": [_Params.ACTUAL_OUTPUT],
        "model": _deepeval_model(chat),
        "async_mode": False,
        "verbose_mode": False,
    }
    if steps:
        kwargs["evaluation_steps"] = steps
    else:
        kwargs["criteria"] = criteria
    try:
        kwargs["threshold"] = None
        metric = GEval(**kwargs)
    except TypeError:
        kwargs.pop("threshold", None)
        metric = GEval(**kwargs)

    overall = None
    reason = ""
    try:
        metric.measure(case)
        overall = metric.score
        reason = str(getattr(metric, "reason", "") or "")
    except Exception as exc:
        return {
            **empty,
            "error": str(exc)[:300],
            **_cost_fields(src, chat),
        }
    criteria_out = [
        {
            "name": slug,
            "steps": steps,
            "criteria": criteria,
            "score": overall,
            "reason": reason,
        }
    ]
    return {
        "ok": overall is not None,
        "score": overall,
        "reason": reason,
        "criteria": criteria_out,
        "output": json.dumps({"score": overall, "reason": reason, "name": slug}),
        "error": "" if overall is not None else "no_score",
        **_cost_fields(src, chat),
    }
