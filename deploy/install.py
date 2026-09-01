#!/usr/bin/env python3
"""Install kaif-eval (local venv, Docker, or Helm staging).

Usage (from repo root):
  python3 deploy/install.py
  python3 deploy/install.py docker
  python3 deploy/install.py helm --demo
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

CHART = Path(__file__).resolve().parent
REPO = CHART.parent


def _run(args: list, cwd=None) -> None:
    print("+", " ".join(args))
    subprocess.check_call(args, cwd=str(cwd or REPO))


def _stage_config(use_demo: bool) -> None:
    files = CHART / "files"
    files.mkdir(parents=True, exist_ok=True)
    src = REPO / "demo" / "eval.yaml" if use_demo else REPO / "config" / "eval.yaml"
    if not src.is_file():
        sys.exit("missing config: %s" % src)
    shutil.copy2(src, files / "eval.yaml")
    app_dst = CHART / "app"
    if app_dst.exists():
        shutil.rmtree(app_dst)
    shutil.copytree(REPO / "app", app_dst)


def install_local() -> None:
    venv = REPO / ".venv"
    if not venv.exists():
        _run([sys.executable, "-m", "venv", str(venv)])
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    _run([str(py), "-m", "pip", "install", "-U", "pip"])
    _run([str(py), "-m", "pip", "install", "-e", ".", "[postgres]"])


def install_docker() -> None:
    _run(["docker", "build", "-f", "deploy/Dockerfile", "-t", "kaif-eval:local", "."])


def install_helm(use_demo: bool) -> None:
    _stage_config(use_demo)
    print("Staged config into deploy/files/eval.yaml")
    print("helm upgrade --install kaif-eval ./deploy -n <ns> --set jobId=<session-id> ...")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", nargs="?", default="local", choices=["local", "docker", "helm"])
    p.add_argument("--demo", action="store_true", help="Stage demo/eval.yaml (OOTB architecture POC)")
    args = p.parse_args()
    if args.mode == "local":
        install_local()
    elif args.mode == "docker":
        install_docker()
    else:
        install_helm(args.demo)


if __name__ == "__main__":
    main()
