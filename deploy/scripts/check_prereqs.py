#!/usr/bin/env python3
"""Check kaif-eval platform prerequisites (observability + trace correlation)."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 400, "http %s" % resp.status
    except urllib.error.HTTPError as exc:
        return exc.code < 500, "http %s" % exc.code
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    p = argparse.ArgumentParser(description="Verify kaif-eval prerequisites")
    p.add_argument("--jaeger-url", default="http://127.0.0.1:16686")
    p.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    checks = {
        "jaeger": _get(args.jaeger_url.rstrip("/") + "/api/services"),
        "prometheus": _get(args.prometheus_url.rstrip("/") + "/-/ready"),
    }
    ok = all(v[0] for v in checks.values())
    out = {k: {"ok": v[0], "detail": v[1]} for k, v in checks.items()}
    out["sampling"] = {
        "ok": None,
        "detail": "Verify OTel Collector tail_sampling or head_sampling=1.0 in your cluster overlay",
    }
    out["correlation"] = {
        "ok": None,
        "detail": "Caller must send session_id header and kaif.run_id span attribute (eval-designer session_id.trace)",
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for name, row in out.items():
            mark = "ok" if row["ok"] else ("?" if row["ok"] is None else "FAIL")
            print("%-12s %s  %s" % (name, mark, row["detail"]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
