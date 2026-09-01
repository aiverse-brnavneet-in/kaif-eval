"""Evaluate one job_id. Each outcome type fetches its named source. No session listing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.config import evidence_name, load_config, load_store_schema, source_map, store_spec, worker_spec
from app.labels import (
    agent_block,
    agent_names,
    allowed,
    default_flow,
    flow_block,
    pack,
    snap,
)
from app.outcomes import classify_with_data, parse_outcome
from app.quality import all_rules
from app.quality import normalize as normalize_quality
from app.quality import score as quality_score
from app.sources import SourceHub
from app.store import JobStore, wrap_evaluation


def eval_job_id(cfg: dict, store: JobStore, job_id: str) -> dict:
    job_id = (job_id or "").strip()
    if not job_id:
        raise SystemExit("session_id / job_id required")
    srcs = source_map(cfg)
    hub = SourceHub(srcs, designer=cfg)
    hub.job_id = job_id
    flow_name = default_flow(cfg)
    flow_cfg = flow_block(cfg, flow_name)
    agents = agent_names(flow_cfg)
    default_agent = agents[0] if agents else "unknown"
    traces_name = evidence_name(cfg, "traces", "jaeger-traces")
    runtime_name = evidence_name(cfg, "runtime", "kagent-sessions")

    traces = hub.get(traces_name, job_id) if traces_name in srcs else {"ok": False}
    if traces.get("ok") and traces.get("flow"):
        flow_name = snap(str(traces.get("flow")), list((cfg.get("flows") or {}).keys()))
        if flow_name == "unknown":
            flow_name = default_flow(cfg)
        flow_cfg = flow_block(cfg, flow_name)
        agents = agent_names(flow_cfg)
        default_agent = agents[0] if agents else default_agent

    agent_name = snap(
        str(traces.get("agent") or default_agent),
        agents,
    )
    if agent_name == "unknown":
        agent_name = default_agent
    agent_cfg = agent_block(flow_cfg, agent_name)
    runtime_cfg = agent_cfg.get("runtime") if isinstance(agent_cfg.get("runtime"), dict) else {}
    if runtime_cfg != hub.runtime_cfg:
        hub.runtime_cfg = runtime_cfg
        hub._cache = {}
        traces = hub.get(traces_name, job_id) if traces_name in srcs else traces
    outcomes_cfg = (
        agent_cfg.get("outcomes")
        if isinstance(agent_cfg.get("outcomes"), dict)
        else {}
    )
    quality_raw = agent_cfg.get("quality")
    qnorm = normalize_quality(quality_raw, agent_cfg)
    rates = qnorm.get("rates") or {}

    extra = {
        "flow": flow_name,
        "agent": agent_name,
        "scenarios": allowed(flow_cfg, "scenario"),
        "skills": allowed(flow_cfg, "skill"),
        "scenario_inference": agent_cfg.get("scenario_inference") or [],
        "skill_catalog": agent_cfg.get("skill_catalog") or allowed(flow_cfg, "skill"),
    }
    hub.flow = flow_name
    hub.agent = agent_name
    hub.job_id = job_id

    if traces_name in srcs and not traces.get("ok"):
        labels = pack(
            cfg,
            {
                "flow": flow_name,
                "scenario": "unknown",
                "agent": agent_name,
                "skill": "unknown",
            },
            records={traces_name: traces},
        )
        card = {
            "run_id": job_id,
            "job_id": job_id,
            "labels": labels,
            "status": "NO_TRACES",
            "outcome": "unfinished",
            "started_at": "",
            "ended_at": "",
            "evaluation": wrap_evaluation(
                {"score": 0, "formula": "average of enabled sections", "sections": {}},
                status="no_traces",
                sources={},
                error=str(traces.get("error") or "no_traces"),
            ),
            "spend_in_usd": {
                "agent": 0,
                "eval": 0,
                "total": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "source": "none",
            },
            "time_taken_sec": 0,
            "error": traces.get("error") or "no_traces",
            "source": traces_name,
        }
        store.upsert_card(card)
        return card

    fetched: dict[str, dict] = {}
    for otype in ("success", "pending", "unfinished", "failed"):
        spec = parse_outcome(outcomes_cfg.get(otype), "")
        src_name = spec.get("source") or ""
        if not src_name:
            fetched[otype] = traces if otype in ("unfinished", "failed") else {"ok": False}
            continue
        fetched[otype] = hub.get(src_name, job_id, extra)

    status, outcome = classify_with_data(outcomes_cfg, fetched)
    runtime = hub.get(runtime_name, job_id, extra) if runtime_name in srcs else {}
    kagent_data: dict = {}
    if traces.get("ok"):
        kagent_data = dict(traces)
        if isinstance(traces.get("runtime"), dict):
            kagent_data.update(traces["runtime"])
    else:
        for payload in list(fetched.values()) + [runtime]:
            if payload.get("kind") == "kagent" and payload.get("ok"):
                kagent_data = payload
                break
            if payload.get("last_tool") or payload.get("artifact"):
                kagent_data = payload

    art = kagent_data.get("artifact") if isinstance(kagent_data.get("artifact"), dict) else {}
    if not art:
        art = {"sha": None, "url": None, "path": None}
    user_turns = int(kagent_data.get("user_turns") or 0)

    tin = float(traces.get("tokens_in") or 0)
    tout = float(traces.get("tokens_out") or 0)
    spend_cfg = cfg.get("spend") if isinstance(cfg.get("spend"), dict) else {}
    token_src = str(spend_cfg.get("tokens") or traces_name).strip()
    metrics_name = evidence_name(cfg, "metrics", "prometheus-metrics")
    if token_src in ("prometheus", metrics_name) and metrics_name in srcs:
        prom = hub.get(metrics_name, job_id, extra)
        if prom.get("ok") and prom.get("value") is not None:
            tin = float(prom.get("value") or 0)
            tout = float(prom.get("tokens_out") or 0)
            traces["token_source"] = metrics_name
    usd_agent = tin * float(rates.get("input") or 0.25) / 1e6 + tout * float(
        rates.get("output") or 2.0
    ) / 1e6
    traces["usd_est"] = usd_agent
    facts = {
        "usd_est": usd_agent,
        "tokens_in": tin,
        "tokens_out": tout,
        "artifact": art,
        "sha": (art or {}).get("sha"),
        "user_turns": user_turns,
        "tools": kagent_data.get("tools") or [],
        "last_tool": kagent_data.get("last_tool") or "",
        "status": status,
        "store_report_ok": bool(kagent_data.get("store_report_ok")),
        "markdown": str(kagent_data.get("markdown") or kagent_data.get("artifact_markdown") or ""),
        "span_names": traces.get("span_names") or [],
        "gen_ai": traces.get("gen_ai") or {},
        "runtime": traces.get("runtime") or {},
    }
    hub.scenario = str(traces.get("scenario") or kagent_data.get("scenario") or "")
    hub.skill = str(traces.get("skill") or kagent_data.get("skill") or "")

    def _fetch(src_name: str, rule=None) -> dict:
        extra_q = dict(extra)
        extra_q["path"] = (art or {}).get("path") or ""
        extra_q["url"] = (art or {}).get("url") or ""
        if isinstance(rule, dict) and rule.get("query"):
            extra_q["query"] = rule.get("query")
        return hub.get(src_name, job_id, extra_q)

    def _judge(prompt, document, rule):
        src = str((rule or {}).get("source") or evidence_name(cfg, "judge", "judge-llm"))
        return hub.judge(src, prompt, document, rule)

    qscore, breakdown, weights, eval_doc = quality_score(
        quality_raw, _fetch, facts, agent_cfg, _judge, outcome
    )
    usd_judge = round(float((eval_doc or {}).get("usd_judge") or 0), 6)
    usd_est = round(usd_agent + usd_judge, 6)
    sections = {
        k: (v or {}).get("score")
        for k, v in ((eval_doc.get("sections") or {}).items())
    }

    records = {
        traces_name: traces,
        runtime_name: kagent_data if kagent_data else runtime,
    }
    records.update({k: v for k, v in fetched.items() if isinstance(v, dict)})
    scenario = traces.get("scenario") or kagent_data.get("scenario") or "unknown"
    skill = traces.get("skill") or kagent_data.get("skill") or "unknown"
    labels = pack(
        cfg,
        {
            "flow": flow_name,
            "scenario": scenario,
            "agent": agent_name,
            "skill": skill,
        },
        records=records,
    )
    used = sorted({spec.get("source") for spec in (
        parse_outcome(outcomes_cfg.get(n), "") for n in ("success", "pending", "unfinished", "failed")
    ) if spec.get("source")})
    used.extend(str(r.get("source") or "") for r in all_rules(qnorm) if r.get("source"))
    used = [u for u in used if u]
    started_at, ended_at, time_taken_sec = _clock_fields(cfg, hub, job_id, extra, traces, kagent_data)
    evaluation = wrap_evaluation(
        eval_doc if isinstance(eval_doc, dict) else {},
        status="ok",
        sources={
            "kagent": {
                "user_turns": user_turns,
                "artifact": art,
            }
        },
    )
    spend = {
        "agent": round(usd_agent, 6),
        "eval": usd_judge,
        "total": usd_est,
        "tokens_in": round(tin, 1),
        "tokens_out": round(tout, 1),
        "source": _spend_token_source(cfg, traces, traces_name),
    }
    card = {
        "run_id": job_id,
        "job_id": job_id,
        "labels": labels,
        "status": status,
        "outcome": outcome,
        "started_at": started_at,
        "ended_at": ended_at,
        "time_taken_sec": time_taken_sec,
        "user_turns": user_turns,
        "artifact": art,
        "tokens_in": round(tin, 1),
        "tokens_out": round(tout, 1),
        "usd_agent": round(usd_agent, 6),
        "usd_judge": usd_judge,
        "usd_est": usd_est,
        "evaluation": evaluation,
        "spend_in_usd": spend,
        "eval": eval_doc,
        "quality_score": qscore,
        "quality_sections": sections,
        "quality_breakdown": breakdown,
        "quality_weights": weights,
        "source": "+".join(dict.fromkeys(used)) if used else traces_name,
    }
    store.upsert_card(card)
    return card


def _clock_fields(cfg: dict, hub, job_id: str, extra: dict, traces: dict, runtime: dict) -> tuple:
    clock = cfg.get("clock") if isinstance(cfg.get("clock"), dict) else {}
    start_src = str(clock.get("started_at") or evidence_name(cfg, "runtime") or "").strip()
    end_src = str(clock.get("ended_at") or start_src).strip()
    dur_src = str(clock.get("duration") or evidence_name(cfg, "traces") or "").strip()

    def _payload(name: str) -> dict:
        if name == evidence_name(cfg, "traces") or name == traces.get("source"):
            return traces
        if name in (evidence_name(cfg, "runtime"),) or name == runtime.get("source"):
            return runtime
        if name and name in hub.sources:
            return hub.get(name, job_id, extra)
        return {}

    def _from(src: str, field: str) -> str:
        primary = _payload(src)
        other = runtime if primary is traces else traces
        return str(primary.get(field) or other.get(field) or "")

    started = _from(start_src, "started_at")
    ended = _from(end_src, "ended_at")
    t_sec = 0.0
    dur = _payload(dur_src)
    if dur.get("duration_s") not in (None, ""):
        try:
            t_sec = float(dur.get("duration_s") or 0)
        except (TypeError, ValueError):
            t_sec = 0.0
    if t_sec <= 0 and started and ended:
        try:
            from datetime import datetime

            def _ts(s):
                return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()

            t_sec = max(0.0, _ts(ended) - _ts(started))
        except Exception:
            t_sec = 0.0
    return started, ended, round(float(t_sec or 0), 1)


def _spend_token_source(cfg: dict, traces: dict, traces_name: str) -> str:
    spend_cfg = cfg.get("spend") if isinstance(cfg.get("spend"), dict) else {}
    src = str(spend_cfg.get("tokens") or traces_name).strip()
    if src and not traces.get("ok"):
        return "none"
    return src or traces_name


def main() -> None:
    p = argparse.ArgumentParser(description="kaif-eval: score one session_id from named sources")
    p.add_argument("--config", default=os.environ.get("KAIF_EVAL_CONFIG", ""))
    p.add_argument("--job-id", required=True, help="Session id / caller job id")
    p.add_argument("--once", action="store_true", default=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg_path = args.config or os.environ.get("KAIF_EVAL_CONFIG", "")
    if not cfg_path:
        demo_cfg = root / "demo" / "eval.yaml"
        cfg_path = str(demo_cfg if demo_cfg.is_file() else root / "config" / "eval-designer.yaml")
    if not Path(cfg_path).is_file():
        cfg_path = str(root / "config" / "eval.yaml")
    cfg = load_config(cfg_path)
    cfg["designer_dir"] = str(Path(cfg_path).parent)
    st = store_spec(cfg)
    store = JobStore(
        path=st["path"],
        url=st["url"] or os.environ.get("KAIF_EVAL_STORE_URL") or "",
        schema_ddl=load_store_schema(cfg, repo_root=root),
        label_cfg=cfg,
    )
    card = eval_job_id(cfg, store, args.job_id)
    print(json.dumps({
        "job_id": card.get("job_id"),
        "outcome": card.get("outcome"),
        "status": card.get("status"),
        "token_source": card.get("token_source"),
        "traces": len(card.get("trace_ids") or []),
        "tokens_in": card.get("tokens_in"),
        "tokens_out": card.get("tokens_out"),
        "usd_est": card.get("usd_est"),
        "usd_agent": card.get("usd_agent"),
        "usd_judge": card.get("usd_judge"),
        "tokens_judge_in": card.get("tokens_judge_in"),
        "tokens_judge_out": card.get("tokens_judge_out"),
        "quality_score": card.get("quality_score"),
        "quality_sections": card.get("quality_sections"),
        "eval": card.get("eval"),
        "quality_breakdown": card.get("quality_breakdown"),
        "quality_weights": card.get("quality_weights"),
        "labels": card.get("labels"),
        "error": card.get("error"),
        "source": card.get("source"),
        "db": str(store.path),
    }, indent=2))


if __name__ == "__main__":
    main()
