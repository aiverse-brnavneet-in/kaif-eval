"""Designer composition loads without a cluster."""

from __future__ import annotations

from pathlib import Path

from app.config import dotted, load_config, source_map
from app.labels import pack, spec


ROOT = Path(__file__).resolve().parents[1]
DESIGNER = ROOT / "config" / "eval-designer.yaml"
DEMO = ROOT / "demo" / "eval.yaml"


def test_designer_has_store_and_worker_templates():
    cfg = load_config(str(DESIGNER))
    assert cfg.get("kind") == "EvalDesigner"
    assert cfg["store"]["schema"]["contract"] == "kaif-value-v1"
    assert cfg["store"]["schema"]["file"] == "schema/jobs.sql"
    assert cfg["worker"]["mode"] in ("on_demand", "${WORKER_MODE:-on_demand}", "")
    assert len(cfg["store"]["schema"].get("columns") or []) >= 8


def test_demo_worker_and_store_overlay():
    cfg = load_config(str(DEMO))
    assert cfg["worker"]["mode"] == "on_demand"
    assert cfg["worker"]["trigger"]["type"] == "manual"
    assert cfg["store"]["schema"]["table"] == "jobs"


def test_designer_template_has_no_poc_bindings():
    cfg = load_config(str(DESIGNER))
    assert cfg["session_id"]["name"] == "session_id"
    assert set(cfg["connectors"]) >= {"kagent", "jaeger", "prometheus", "gitea", "api", "llm"}
    trace = cfg["session_id"]["trace"]
    assert trace.get("primary_attribute") != "gen_ai.conversation.id"
    assert trace.get("inject", {}).get("header") != "X-Kaif-Run-Id"
    assert not source_map(cfg)


def test_demo_overlay_includes_architecture_policy():
    cfg = load_config(str(DEMO))
    srcs = source_map(cfg)
    assert set(srcs) >= {
        "kagent-sessions",
        "jaeger-traces",
        "prometheus-metrics",
        "judge-llm",
        "git-artifacts",
    }
    assert cfg["session_id"]["trace"]["primary_attribute"] == "gen_ai.conversation.id"
    assert cfg["session_id"]["trace"]["inject"]["header"] == "X-Kaif-Run-Id"
    assert "architecture" in cfg["flows"]
    agents = cfg["flows"]["architecture"]["agents"]
    assert agents[0]["outcomes"]["success"]["source"] == "jaeger-traces"
    assert agents[0]["runtime"]["publish_tool"] == "store_report"
    assert cfg["evidence"]["traces"] == "jaeger-traces"


def test_labels_define_and_fetch():
    cfg = load_config(str(DEMO))
    names = [row["name"] for row in spec(cfg)]
    assert names == ["flow", "scenario", "agent", "skill"]
    records = {
        "jaeger-traces": {
            "ok": True,
            "flow": "architecture",
            "agent": "software-architect",
            "scenario": "new_architecture",
            "skill": "problem-framing",
        },
    }
    labels = pack(cfg, {"flow": "architecture"}, records=records)
    by_key = {row["key"]: row["value"] for row in labels}
    assert by_key["flow"] == "architecture"
    assert by_key["scenario"] == "new_architecture"


def test_dotted_field():
    assert dotted({"artifact": {"sha": "abc"}}, "artifact.sha") == "abc"
    assert dotted({}, "artifact.sha", "") == ""
