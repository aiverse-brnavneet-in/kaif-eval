#!/usr/bin/env python3
"""Generate kaif-eval Excalidraw diagrams (VS Code / excalidraw.com compatible)."""

from __future__ import annotations

import json
import secrets
import string
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent / "diagrams"
OUT.mkdir(exist_ok=True)

SOURCE = "https://marketplace.visualstudio.com/items?itemName=pomdtr.excalidraw-editor"

C = {
    "signals": {"stroke": "#e8590c", "bg": "#fff9db", "fill": "#ffd8a8"},
    "engine": {"stroke": "#1971c2", "bg": "#f0f7ff", "fill": "#a5d8ff"},
    "policy": {"stroke": "#5f3dc4", "bg": "#f3f0ff", "fill": "#d0bfff"},
    "store": {"stroke": "#2b8a3e", "bg": "#ebfbee", "fill": "#b2f2bb"},
    "people": {"stroke": "#1e1e1e", "bg": "#fff3bf", "fill": "#fff3bf"},
    "neutral": {"stroke": "#495057", "bg": "#f8f9fa", "fill": "#e9ecef"},
    "ink": "#1e1e1e",
}

_IDX_CHARS = string.digits + string.ascii_uppercase + string.ascii_lowercase


def _nid() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(21))


def _frac(n: int) -> str:
    if n < len(_IDX_CHARS):
        return "a" + _IDX_CHARS[n]
    return "a" + _IDX_CHARS[n // len(_IDX_CHARS)] + _IDX_CHARS[n % len(_IDX_CHARS)]


class B:
    """Build Excalidraw elements matching excalidraw-vscode/examples format."""

    def __init__(self) -> None:
        self.elements: list[dict] = []
        self._ids: dict[str, str] = {}
        self._idx = 0
        self._t0 = int(time.time() * 1000)

    def _next_index(self) -> str:
        i = _frac(self._idx)
        self._idx += 1
        return i

    def _id(self, key: str | None = None) -> str:
        if key:
            if key not in self._ids:
                self._ids[key] = _nid()
            return self._ids[key]
        return _nid()

    def _meta(self, el_type: str, **extra) -> dict:
        ts = self._t0 + len(self.elements)
        return {
            "type": el_type,
            "angle": 0,
            "strokeColor": extra.pop("strokeColor", C["ink"]),
            "backgroundColor": extra.pop("backgroundColor", "transparent"),
            "fillStyle": "solid",
            "strokeWidth": extra.pop("strokeWidth", 2),
            "strokeStyle": extra.pop("strokeStyle", "solid"),
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "index": self._next_index(),
            "roundness": extra.pop("roundness", {"type": 3}),
            "seed": secrets.randbelow(2**31),
            "version": secrets.randbelow(200) + 1,
            "versionNonce": secrets.randbelow(2**31),
            "isDeleted": False,
            "boundElements": extra.pop("boundElements", []),
            "updated": ts,
            "link": None,
            "locked": False,
            **extra,
        }

    def title(self, x: float, y: float, text: str, size: int = 28) -> None:
        self._text(x, y, max(len(text) * size * 0.55, 200), size * 1.4, text, size, "left", "top")

    def zone(self, x: float, y: float, w: float, h: float, label: str, palette: str) -> None:
        p = C[palette]
        self._rect(x, y, w, h, p["stroke"], p["bg"], dashed=True)
        self._text(x + 12, y + 8, w - 24, 24, label, 16, "left", "top", stroke=p["stroke"])

    def box(self, x: float, y: float, w: float, h: float, label: str, palette: str = "engine", subtitle: str | None = None) -> str:
        p = C[palette]
        rid = _nid()
        lines = label.split("\n")
        body = label if not subtitle else label
        tid = _nid()
        self.elements.append(
            {
                "id": rid,
                **self._meta(
                    "rectangle",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    strokeColor=p["stroke"],
                    backgroundColor=p["fill"],
                    boundElements=[{"type": "text", "id": tid}],
                ),
            }
        )
        fs = 14 if subtitle or len(lines) > 1 else 16
        ty = y + (h - (len(lines) * fs * 1.25 + (12 if subtitle else 0))) / 2
        self._text(
            x + 8,
            ty,
            w - 16,
            h - 8,
            body,
            fs,
            "center",
            "middle",
            container=rid,
            eid=tid,
        )
        if subtitle:
            self._text(x + 8, y + h - 22, w - 16, 18, subtitle, 11, "center", "top", stroke="#868e96")
        return rid

    def note(self, x: float, y: float, text: str, w: float = 400) -> None:
        self._text(x, y, w, 20, text, 12, "left", "top", stroke="#868e96")

    def arrow(self, sx: float, sy: float, ex: float, ey: float, label: str | None = None) -> None:
        dx, dy = ex - sx, ey - sy
        self.elements.append(
            {
                "id": _nid(),
                **self._meta(
                    "arrow",
                    x=sx,
                    y=sy,
                    width=abs(dx) or 1,
                    height=abs(dy) or 1,
                    roundness={"type": 2},
                    points=[[0, 0], [dx, dy]],
                    startArrowhead=None,
                    endArrowhead="arrow",
                    lastCommittedPoint=None,
                ),
            }
        )
        if label:
            self._text(sx + dx / 2 - len(label) * 4, sy + dy / 2 - 10, len(label) * 8, 18, label, 12, "center", "middle")

    def legend(self, x: float, y: float) -> None:
        self.title(x, y, "Legend", 16)
        rows = [
            ("signals", "Signals / telemetry"),
            ("engine", "kaif-eval engine"),
            ("policy", "Policy / designer"),
            ("store", "Store / value"),
            ("people", "People / triggers"),
            ("neutral", "External systems"),
        ]
        for i, (pal, lbl) in enumerate(rows):
            py = y + 30 + i * 28
            p = C[pal]
            self._rect(x, py, 22, 16, p["stroke"], p["fill"])

    def _rect(self, x, y, w, h, stroke, bg, dashed=False) -> None:
        self.elements.append(
            {
                "id": _nid(),
                **self._meta(
                    "rectangle",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    strokeColor=stroke,
                    backgroundColor=bg,
                    strokeStyle="dashed" if dashed else "solid",
                ),
            }
        )

    def _text(
        self,
        x,
        y,
        w,
        h,
        text,
        size,
        align,
        valign,
        stroke=C["ink"],
        container: str | None = None,
        eid: str | None = None,
    ) -> None:
        self.elements.append(
            {
                "id": eid or _nid(),
                **self._meta(
                    "text",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    strokeColor=stroke,
                    roundness=None,
                    text=text,
                    originalText=text,
                    fontSize=size,
                    fontFamily=5,
                    textAlign=align,
                    verticalAlign=valign,
                    containerId=container,
                    autoResize=True,
                    lineHeight=1.25,
                ),
            }
        )

    def save(self, path: Path) -> None:
        doc = {
            "type": "excalidraw",
            "version": 2,
            "source": SOURCE,
            "elements": self.elements,
            "appState": {
                "gridSize": 20,
                "gridStep": 5,
                "gridModeEnabled": False,
                "viewBackgroundColor": "#ffffff",
            },
            "files": {},
        }
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def diagram_overview() -> None:
    b = B()
    b.title(40, 20, "Diagram 1 - kaif-eval overview")
    b.zone(40, 70, 300, 500, "Signals", "signals")
    b.box(60, 115, 260, 68, "Telemetry", "signals", "Jaeger · Prometheus · OTel")
    b.box(60, 200, 260, 68, "Agent runtimes", "signals", "kagent · ADK · custom")
    b.box(60, 285, 260, 68, "Artifact systems", "signals", "Git · S3 · registry")
    b.box(60, 370, 260, 68, "Business apps", "signals", "Jira · CRM · tickets")
    b.zone(380, 70, 640, 500, "kaif-eval engine", "engine")
    b.box(400, 110, 170, 58, "Eval designer", "policy", "mother YAML / CRD")
    b.box(620, 110, 170, 58, "Configuration", "engine", "assembled at runtime")
    b.arrow(570, 139, 620, 139)
    b.box(510, 210, 170, 64, "Worker job", "engine", "CLI · API · scheduler")
    b.arrow(705, 168, 595, 210)
    b.box(420, 330, 170, 64, "Outcome engine", "engine", "success · pending · failed")
    b.box(620, 330, 170, 64, "Quality engine", "engine", "deterministic + G-Eval")
    b.arrow(595, 274, 505, 330)
    b.arrow(595, 274, 705, 330)
    b.box(510, 450, 170, 64, "Eval store", "store", "Postgres / SQLite")
    b.arrow(505, 394, 555, 450)
    b.arrow(705, 394, 625, 450)
    b.zone(1060, 70, 320, 500, "kaif-value", "store")
    b.box(1080, 180, 280, 56, "Read eval store", "store")
    b.box(1080, 270, 280, 56, "Export KPIs", "store")
    b.box(1080, 360, 130, 56, "Dashboards", "neutral", "Grafana")
    b.box(1230, 360, 130, 56, "Agents", "neutral", "feedback loop")
    b.arrow(680, 482, 1080, 208)
    b.arrow(1220, 236, 1220, 270)
    b.arrow(1145, 326, 1145, 360)
    b.arrow(1295, 326, 1295, 360)
    b.legend(40, 600)
    b.save(OUT / "01-kaif-eval-overview.excalidraw")


def diagram_designer() -> None:
    b = B()
    b.title(40, 20, "Diagram 2 - Eval designer (mother composition)")
    b.zone(40, 70, 1100, 520, "eval-designer.yaml · kind: EvalDesigner", "policy")
    items = [
        ("Unique ID", "session_id · correlation header"),
        ("Labels", "flow · scenario · agent · skill"),
        ("Connectors", "jaeger · prometheus · kagent · llm"),
        ("Sources", "named instances + auth"),
        ("Policies", "outcomes · quality · runtime tools"),
        ("Store + schema", "DDL · kaif-value-v1 contract"),
        ("Worker config", "mode · triggers · retry"),
        ("Evidence map", "traces · judge · artifacts"),
    ]
    x0, y0, bw, bh, gap = 70, 120, 230, 72, 20
    for i, (title, sub) in enumerate(items):
        col, row = i % 4, i // 4
        pal = "policy" if i in (0, 4, 5) else "engine"
        b.box(x0 + col * (bw + gap), y0 + row * (bh + gap + 28), bw, bh, title, pal, sub)
    b.box(460, 460, 280, 64, "Configuration assembly", "engine", "app/config.py")
    b.box(70, 460, 300, 64, "Future surfaces", "neutral", "UI · K8s CRD · GitOps overlay")
    b.save(OUT / "02-eval-designer.excalidraw")


def diagram_worker() -> None:
    b = B()
    b.title(40, 20, "Diagram 3 - Worker job")
    b.zone(40, 70, 260, 480, "Triggers", "people")
    triggers = [
        ("Manual / CLI", "--job-id"),
        ("HTTP API", "POST /v1/eval/run"),
        ("Scheduler", "cron · interval"),
        ("Event-based", "Kafka · Argo · K8s · SNS"),
    ]
    for i, (t, s) in enumerate(triggers):
        b.box(60, 110 + i * 95, 220, 72, t, "people", s)
    b.box(370, 280, 190, 72, "Worker job", "engine", "app/worker.py")
    for i in range(len(triggers)):
        b.arrow(280, 146 + i * 95, 370, 316)
    b.zone(600, 70, 520, 480, "Job pipeline", "engine")
    steps = [
        ("1. Config load", "policies · labels · schema"),
        ("2. Validation", "prereqs · source refs"),
        ("3. Fetch evidence", "connectors → sources"),
        ("4. Policy engine", "outcome + quality"),
        ("5. Pluggable rules", "BYO eval framework"),
        ("6. Alerting", "webhook · metrics · ticket"),
        ("7. Output", "eval store row"),
    ]
    for i, (title, sub) in enumerate(steps):
        b.box(620, 110 + i * 62, 210, 50, title, "engine", sub)
        if i > 0:
            b.arrow(725, 110 + (i - 1) * 62 + 50, 725, 110 + i * 62)
    b.zone(40, 580, 1080, 140, "Policy engine detail", "policy")
    b.box(60, 620, 280, 72, "Deterministic rules", "policy", "published · tools · budget")
    b.box(370, 620, 280, 72, "LLM-as-judge", "policy", "G-Eval · DeepEval")
    b.box(680, 620, 280, 72, "Bring your own eval", "policy", "Ragas · Phoenix · custom")
    b.save(OUT / "03-worker-job.excalidraw")


def diagram_correlation() -> None:
    b = B()
    b.title(40, 20, "Diagram 4 - Correlation engine (telemetry-centric)")
    b.note(40, 52, "Primary data plane: OpenTelemetry. Correlation ID joins telemetry with runtime, business, and artifact evidence.")
    b.zone(340, 90, 560, 130, "OTel telemetry (primary)", "signals")
    b.box(360, 125, 150, 60, "Traces", "signals", "Jaeger / Tempo")
    b.box(530, 125, 150, 60, "Metrics", "signals", "Prometheus")
    b.box(700, 125, 150, 60, "Logs", "signals", "Loki (roadmap)")
    b.box(480, 260, 280, 88, "Correlation ID", "policy", "session_id · X-Kaif-Run-Id")
    b.arrow(435, 185, 560, 260)
    b.arrow(605, 185, 620, 260)
    b.zone(40, 390, 1160, 170, "Joined evidence (connectors + sources)", "engine")
    b.box(60, 430, 220, 88, "Agent runtime", "engine", "kagent sessions API")
    b.box(310, 430, 220, 88, "Business data", "neutral", "Jira · tickets · CRM")
    b.box(560, 430, 220, 88, "Artifacts", "store", "Git SHA · S3")
    b.box(810, 430, 220, 88, "Custom HTTP", "neutral", "api connector")
    b.arrow(620, 348, 170, 430)
    b.arrow(620, 348, 420, 430)
    b.arrow(620, 348, 670, 430)
    b.arrow(620, 348, 920, 430)
    b.zone(40, 590, 1160, 170, "Quality measurement", "policy")
    b.box(60, 630, 250, 88, "OOB deterministic", "policy", "policy.yaml rules")
    b.box(340, 630, 250, 88, "Custom deterministic", "policy", "user-defined rules")
    b.box(620, 630, 200, 88, "LLM-as-judge", "policy", "G-Eval")
    b.box(850, 630, 200, 88, "BYO framework", "policy", "Ragas · Phoenix")
    b.box(480, 800, 280, 64, "Eval store record", "store", "outcome · quality · spend")
    b.arrow(620, 718, 620, 800)
    b.legend(40, 900)
    b.save(OUT / "04-correlation-engine.excalidraw")


def write_smoke_test() -> None:
    """Official excalidraw-vscode example — guaranteed to open."""
    import urllib.request

    url = "https://raw.githubusercontent.com/excalidraw/excalidraw-vscode/master/examples/test2.excalidraw"
    dst = OUT / "00-smoke-test.excalidraw"
    with urllib.request.urlopen(url, timeout=30) as resp:
        dst.write_bytes(resp.read())


def main() -> None:
    write_smoke_test()
    diagram_overview()
    diagram_designer()
    diagram_worker()
    diagram_correlation()
    # Remove broken double-extension copies
    for p in OUT.glob("*.excalidraw.json"):
        p.unlink()
    print("Wrote:")
    for p in sorted(OUT.glob("*.excalidraw")):
        print(f"  {p}")


if __name__ == "__main__":
    main()
