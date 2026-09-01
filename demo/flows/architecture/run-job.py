#!/usr/bin/env python3
"""Demo driver: mint job_id, send A2A message, run kaif-eval. Config-driven — no hardcoded flow names in app/."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "demo"
CFG_PATH = DEMO / "flows" / "architecture" / "run-config.yaml"


def _load_run_config() -> dict:
    try:
        import yaml
    except ImportError:
        raise SystemExit("PyYAML required: pip install PyYAML")
    raw = CFG_PATH.read_text(encoding="utf-8")
  # expand env in yaml values manually for top-level strings
    import re

    def repl(m):
        inner = m.group(1)
        if ":-" in inner:
            name, default = inner.split(":-", 1)
            return os.environ.get(name, default)
        return os.environ.get(inner, "")

    data = yaml.safe_load(re.sub(r"\$\{([^}]+)\}", repl, raw)) or {}
    return data if isinstance(data, dict) else {}


def sh(args, timeout=30):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout


def wait_http(url, timeout_s=20):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError("not ready: %s" % url)


def a2a(job_id: str, prompt: str, cfg: dict, timeout_s: int) -> dict:
    a2a_cfg = cfg.get("a2a") if isinstance(cfg.get("a2a"), dict) else {}
    headers_cfg = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    port = int(a2a_cfg.get("port") or 18080)
    mid = uuid.uuid4().hex
    body = {
        "jsonrpc": "2.0",
        "id": mid,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "kind": "message",
                "messageId": mid,
                "contextId": job_id,
                "parts": [{"kind": "text", "text": prompt}],
            },
            "configuration": {"blocking": True},
        },
    }
    hdrs = {
        "Content-Type": "application/json",
        "X-Kaif-Flow": str(headers_cfg.get("flow") or ""),
        "X-Kaif-Agent": str(headers_cfg.get("agent") or ""),
        "X-Kaif-Scenario": str(headers_cfg.get("scenario") or ""),
        "X-Kaif-Run-Id": job_id,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:%d/" % port,
        data=json.dumps(body).encode(),
        headers=hdrs,
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode())
            return {"ok": True, "http": resp.status, "elapsed_s": round(time.time() - t0, 1), "payload": payload}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http": exc.code, "elapsed_s": round(time.time() - t0, 1), "error": exc.read()[:500]}
    except Exception as exc:
        return {"ok": False, "http": 0, "elapsed_s": round(time.time() - t0, 1), "error": str(exc)}


def run_eval(eval_config: str, job_id: str) -> dict:
    p = subprocess.run(
        [sys.executable, "-m", "app.worker", "--config", eval_config, "--job-id", job_id],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr or p.stdout)
    return json.loads(p.stdout)


def main() -> None:
    cfg = _load_run_config()
    prompt_path = Path(__file__).parent / "prompts" / "pending-ask-user.txt"
    prompt = os.environ.get("KAIF_JOB_PROMPT") or prompt_path.read_text(encoding="utf-8")
    job_id = uuid.uuid4().hex
    print("job_id=%s" % job_id, flush=True)

    a2a_cfg = cfg.get("a2a") or {}
    jaeger_cfg = cfg.get("jaeger") or {}
    kagent_cfg = cfg.get("kagent") or {}
    pfs = []
    try:
        pfs.append(
            subprocess.Popen(
                [
                    "kubectl", "-n", str(a2a_cfg.get("namespace")),
                    "port-forward", "svc/%s" % a2a_cfg.get("service"),
                    "%d:8080" % int(a2a_cfg.get("port") or 18080),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        pfs.append(
            subprocess.Popen(
                [
                    "kubectl", "-n", str(jaeger_cfg.get("namespace")),
                    "port-forward", "svc/%s" % jaeger_cfg.get("service"),
                    "%d:16686" % int(jaeger_cfg.get("port") or 16686),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        pfs.append(
            subprocess.Popen(
                [
                    "kubectl", "-n", str(kagent_cfg.get("namespace")),
                    "port-forward", "svc/%s" % kagent_cfg.get("service"),
                    "%d:8083" % int(kagent_cfg.get("port") or 18083),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        wait_http("http://127.0.0.1:%d/" % int(a2a_cfg.get("port") or 18080))
        wait_http("http://127.0.0.1:%d/" % int(jaeger_cfg.get("port") or 16686))

        os.environ.setdefault("JAEGER_URL", "http://127.0.0.1:%d" % int(jaeger_cfg.get("port") or 16686))
        os.environ.setdefault("KAIF_EVAL_DB", "/tmp/kaif-eval.db")

        result = a2a(job_id, prompt, cfg, int(cfg.get("timeout_s") or 240))
        print(json.dumps(result, indent=2), flush=True)

        time.sleep(int(cfg.get("ingest_wait_s") or 12))
        eval_cfg = str(ROOT / str(cfg.get("eval_config") or "demo/eval.yaml"))
        card = run_eval(eval_cfg, job_id)
        print("eval=", json.dumps(card, indent=2), flush=True)
    finally:
        for proc in pfs:
            proc.kill()


if __name__ == "__main__":
    main()
