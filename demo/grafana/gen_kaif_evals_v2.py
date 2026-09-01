#!/usr/bin/env python3
"""Build KAIF Evals v2 from value.yaml (kaif-evals outputs + description prompts).

Queries follow the Infinity contract in those descriptions. Not a copy of KAIF Evals.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

try:
    import yaml  # type: ignore
except ImportError:
    sys.exit("pyyaml required: python3 -m pip install pyyaml")

HERE = Path(__file__).resolve().parent
VALUE_YAML = HERE.parents[1] / "kaif-value" / "config" / "value.yaml"
OUT = HERE / "kaif-evals-v2.json"
API = "http://kaif-value-exporter.observability.svc.cluster.local:8000"
DS = {"type": "yesoreyeram-infinity-datasource", "uid": "kaif-value-api"}
DASH = "kaif-evals"


def load_outputs() -> list[dict]:
    cfg = yaml.safe_load(VALUE_YAML.read_text(encoding="utf-8")) or {}
    for board in cfg.get("dashboards") or []:
        if board.get("uid") == DASH:
            return [o for o in (board.get("outputs") or []) if isinstance(o, dict)]
    raise SystemExit("kaif-evals dashboard missing in value.yaml")


# Grafana display only. KPI meaning lives in value.yaml description.
VISUAL = {
    "Jobs": {"unit": "short", "colorMode": "value", "color": "text", "decimals": 0},
    "Published": {"unit": "short", "colorMode": "background", "color": "green", "decimals": 0},
    "Incomplete": {
        "unit": "short",
        "colorMode": "background",
        "decimals": 0,
        "thresholds": "0 green; >=1 orange; >=2 semi-dark-red",
    },
    "Waiting": {
        "unit": "short",
        "colorMode": "background",
        "decimals": 0,
        "thresholds": "0 green; >=1 blue",
    },
    "Quality of published work": {
        "unit": "none",
        "min": 0,
        "max": 100,
        "decimals": 1,
        "colorMode": "background",
        "thresholds": "<50 semi-dark-red; >=50 orange; >=80 green",
    },
    "Completion rate": {
        "unit": "percentunit",
        "colorMode": "background",
        "decimals": 0,
        "thresholds": "<0.5 semi-dark-red; >=0.5 orange; >=0.8 green",
    },
    "Failure rate": {
        "unit": "percentunit",
        "colorMode": "background",
        "decimals": 0,
        "thresholds": "0 green; >=0.2 orange; >=0.5 semi-dark-red",
    },
    "Deterministic: pass moving average": {"unit": "percentunit", "min": 0, "max": 1},
    "LLM as judge: score moving average": {"unit": "percentunit", "min": 0, "max": 1},
}


def outcomes(*names: str) -> str:
    q = (
        "from=${__from}&to=${__to}&flow=${flow}&scenario=${scenario}"
        f"&agent=${{agent}}&dashboard={DASH}"
    )
    for n in names:
        q += "&name=" + quote(n, safe="")
    return f"{API}/v1/outcomes?{q}"


def target(name: str, columns: list, root: str = "") -> dict:
    return {
        "datasource": DS,
        "refId": "A",
        "type": "json",
        "source": "url",
        "format": "table",
        "parser": "backend",
        "uql": "",
        "root_selector": root,
        "url": outcomes(name),
        "url_options": {"method": "GET", "data": ""},
        "columns": columns,
        "filters": [],
    }


def col(selector: str, text: str, typ: str = "number") -> dict:
    return {"selector": selector, "text": text, "type": typ}


def parse_thresholds(spec: str) -> dict:
    steps = []
    for part in (spec or "").split(";"):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(>=|>|<)?\s*([0-9.]+)\s+(.+)$", part)
        if m:
            op, num, color = m.group(1), float(m.group(2)), m.group(3).strip()
            if op == "<":
                if not steps:
                    steps.append({"color": color, "value": None})
                continue
            steps.append({"color": color, "value": num})
            continue
        m = re.match(r"^([0-9.]+)\s+(.+)$", part)
        if m and float(m.group(1)) == 0:
            steps.append({"color": m.group(2).strip(), "value": None})
            continue
        steps.append({"color": part, "value": None})
    if not steps:
        steps = [{"color": "green", "value": None}]
    if steps[0]["value"] is not None:
        steps.insert(0, {"color": "green", "value": None})
    return {"mode": "absolute", "steps": steps}


def color_cfg(meta: dict) -> dict:
    if meta.get("color") in (None, "", "palette-classic"):
        if meta.get("thresholds"):
            return {"mode": "thresholds"}
        if meta.get("colorMode") == "background":
            return {"mode": "thresholds"}
        return {"mode": "thresholds"}
    if meta.get("color") == "palette-classic":
        return {"mode": "palette-classic"}
    return {"mode": "fixed", "fixedColor": meta["color"]}


def variable(name: str, label: str, url: str, *, multi: bool = False) -> dict:
    inf = {
        "refId": "variable",
        "type": "json",
        "source": "url",
        "format": "table",
        "parser": "backend",
        "uql": "",
        "root_selector": "values",
        "url": url,
        "url_options": {"method": "GET", "data": ""},
        "columns": [
            {"selector": "value", "text": "__text", "type": "string"},
            {"selector": "value", "text": "__value", "type": "string"},
        ],
        "filters": [],
        "datasource": DS,
    }
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DS,
        "includeAll": True,
        "allValue": ".*",
        "multi": multi,
        "refresh": 1,
        "sort": 1,
        "hide": 0,
        "regex": "",
        "skipUrlSync": False,
        "options": [],
        "current": {"selected": True, "text": "All", "value": "$__all"},
        "definition": "KAIF Value API- (infinity) json",
        "query": {"queryType": "infinity", "query": "", "infinityQuery": inf},
    }


def row(pid: int, title: str, y: int) -> dict:
    return {
        "id": pid,
        "type": "row",
        "title": title,
        "collapsed": False,
        "panels": [],
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
    }


def stat_panel(pid: int, spec: dict, meta: dict, x: int, y: int, w: int, h: int) -> dict:
    name = spec["name"]
    unit = meta.get("unit") or "short"
    decimals = int(float(meta["decimals"])) if meta.get("decimals") else 0
    color_mode = meta.get("colorMode") or "value"
    defaults = {
        "color": color_cfg(meta) if not meta.get("thresholds") else {"mode": "thresholds"},
        "thresholds": parse_thresholds(meta["thresholds"]) if meta.get("thresholds") else {
            "mode": "absolute",
            "steps": [{"color": meta.get("color") or "green", "value": None}],
        },
        "unit": unit,
        "decimals": decimals,
    }
    if meta.get("min") is not None:
        defaults["min"] = float(meta["min"])
    if meta.get("max") is not None:
        defaults["max"] = float(meta["max"])
    if meta.get("color") and not meta.get("thresholds") and meta.get("color") not in ("text",):
        if meta["color"] != "green":
            defaults["color"] = {"mode": "fixed", "fixedColor": meta["color"]}
    if meta.get("color") == "text":
        defaults["color"] = {"mode": "fixed", "fixedColor": "text"}
        defaults["thresholds"] = {"mode": "absolute", "steps": [{"color": "green", "value": None}]}
    return {
        "id": pid,
        "type": "stat",
        "title": name,
        "description": str(spec.get("description") or "").strip(),
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(name, [col(name, name)])],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": name, "values": True},
            "orientation": "auto",
            "textMode": "auto",
            "wideLayout": True,
            "colorMode": color_mode,
            "graphMode": "none",
            "justifyMode": "center",
            "showPercentChange": False,
            "percentChangeColorMode": "standard",
            "text": {"titleSize": 14 if h >= 5 else 12, "valueSize": 36 if h >= 5 else 22},
        },
        "fieldConfig": {"defaults": defaults, "overrides": []},
    }


def ma_panel(pid: int, spec: dict, meta: dict, y: int) -> dict:
    name = spec["name"]
    unit = meta.get("unit") or "percentunit"
    return {
        "id": pid,
        "type": "timeseries",
        "title": name,
        "description": str(spec.get("description") or "").strip(),
        "datasource": DS,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 10},
        "targets": [
            target(
                name,
                [
                    col("t", "Time"),
                    col("metric", "metric", "string"),
                    col("ma", "Value"),
                ],
                root=name,
            )
        ],
        "transformations": [
            {
                "id": "convertFieldType",
                "options": {"conversions": [{"targetField": "Time", "destinationType": "time"}]},
            },
            {
                "id": "partitionByValues",
                "options": {
                    "fields": ["metric"],
                    "keepFields": False,
                    "naming": {"asLabels": False},
                },
            },
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "barAlignment": 0,
                    "lineInterpolation": "smooth",
                    "lineWidth": 3,
                    "fillOpacity": 0,
                    "gradientMode": "none",
                    "spanNulls": True,
                    "insertNulls": False,
                    "showPoints": "always",
                    "pointSize": 10,
                    "stacking": {"mode": "none", "group": "A"},
                    "axisPlacement": "auto",
                    "axisLabel": "",
                    "axisColorMode": "text",
                    "axisBorderShow": False,
                    "axisCenteredZero": False,
                    "axisGridShow": True,
                    "scaleDistribution": {"type": "linear"},
                    "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                    "thresholdsStyle": {"mode": "off"},
                    "lineStyle": {"fill": "solid"},
                },
                "min": float(meta.get("min") or 0),
                "max": float(meta.get("max") or 1),
                "decimals": 0,
                "unit": unit,
                "color": {"mode": "palette-classic"},
            },
            "overrides": [],
        },
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def build() -> dict:
    outputs = load_outputs()
    by_name = {o["name"]: o for o in outputs}
    pid = 10
    panels = [
        {
            "id": 1,
            "type": "text",
            "title": "",
            "transparent": True,
            "gridPos": {"h": 2, "w": 24, "x": 0, "y": 0},
            "options": {
                "mode": "markdown",
                "content": (
                    "**Identity:** Published + Incomplete + Waiting = Jobs. "
                    "**Quality** is published work only (same as KAIF Value). "
                    "**Completion / Failure** are shares of Jobs; waiting is not failure. "
                    "Panels and dropdowns are built from `value.yaml` descriptions → `GET /v1/outcomes?dashboard=kaif-evals`."
                ),
            },
        },
        row(2, "Jobs in this filter", 2),
    ]
    # four count tiles
    for i, name in enumerate(("Jobs", "Published", "Incomplete", "Waiting")):
        spec = by_name[name]
        panels.append(stat_panel(pid, spec, VISUAL[name], x=i * 6, y=3, w=6, h=4))
        pid += 1
    panels.append(row(3, "Quality and rates (same Jobs denominator)", 7))
    for i, name in enumerate(("Quality of published work", "Completion rate", "Failure rate")):
        spec = by_name[name]
        panels.append(stat_panel(pid, spec, VISUAL[name], x=i * 8, y=8, w=8, h=5))
        pid += 1
    panels.append(row(4, "Quality trends (moving average by metric)", 13))
    y = 14
    for name in (
        "Deterministic: pass moving average",
        "LLM as judge: score moving average",
    ):
        spec = by_name[name]
        panels.append(ma_panel(pid, spec, VISUAL[name], y))
        pid += 1
        y += 10

    return {
        "uid": "kaif-evals-v2",
        "title": "KAIF Evals v2",
        "description": "Quality drill-down from GET /v1/outcomes?dashboard=kaif-evals. Built from value.yaml descriptions.",
        "tags": ["kaif", "eval", "quality"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "",
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "liveNow": False,
        "weekStart": "",
        "id": None,
        "links": [
            {"title": "KAIF Value v2 (CTO)", "type": "link", "url": "/d/kaif-value-v2", "targetBlank": False, "keepTime": True},
            {"title": "KAIF LLM cost & budget", "type": "link", "url": "/d/kaif-llm-cost", "targetBlank": False, "keepTime": True},
        ],
        "annotations": {"list": []},
        "time": {"from": "now-12h", "to": "now"},
        "timepicker": {},
        "templating": {
            "list": [
                variable("flow", "Flow", f"{API}/v1/label-values?key=flow"),
                variable("scenario", "Scenario", f"{API}/v1/label-values?key=scenario&flow=${{flow}}"),
                variable("agent", "Agents", f"{API}/v1/label-values?key=agent&flow=${{flow}}&scenario=${{scenario}}", multi=True),
            ]
        },
        "panels": panels,
    }


def main() -> None:
    dash = build()
    missing = [o["name"] for o in load_outputs() if o["name"] not in {p.get("title") for p in dash["panels"]}]
    if missing:
        raise SystemExit(f"outputs not on dashboard: {missing}")
    OUT.write_text(json.dumps(dash, indent=2) + "\n")
    print("wrote", OUT, "panels", len(dash["panels"]))


if __name__ == "__main__":
    main()
