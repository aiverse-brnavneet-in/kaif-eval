"""Gitea connector — fetch file content from a Git repository."""

from __future__ import annotations

import base64
import re
import urllib.parse

from app.http import http_json


class GiteaConnector:
    name = "gitea"

    def fetch(self, hub, src: dict, job_id: str, extra: dict) -> dict:
        url_or_path = str(extra.get("path") or extra.get("url") or "")
        git_url = str(src.get("url") or "").rstrip("/")
        auth = src.get("auth") if isinstance(src.get("auth"), dict) else {}
        token = str(src.get("token") or auth.get("token") or "")
        repo = str(src.get("repo") or "")
        prefix = str(src.get("path_prefix") or "").strip()
        empty = {"ok": False, "markdown": "", "error": "git_unconfigured"}
        if not url_or_path or not git_url or not token:
            empty["error"] = "missing_path_or_creds"
            return empty
        path = url_or_path
        if prefix and prefix in path and not path.startswith(prefix):
            m = re.search(re.escape(prefix.rstrip("/")) + r"/[^?#]+", path)
            path = m.group(0) if m else path
        if prefix and not path.startswith(prefix):
            empty["error"] = "path_not_in_prefix"
            return empty
        hdrs = hub._headers(src)
        try:
            user = http_json(f"{git_url}/api/v1/user", token=token, headers=hdrs)
            owner = str(src.get("owner") or "")
            if not owner:
                owner = str((user or {}).get("login") or "") if isinstance(user, dict) else ""
            repo_obj = http_json(f"{git_url}/api/v1/repos/{owner}/{repo}", token=token, headers=hdrs)
            branch = str(src.get("branch") or "")
            if not branch:
                branch = (
                    str((repo_obj or {}).get("default_branch") or "main")
                    if isinstance(repo_obj, dict)
                    else "main"
                )
            file_obj = http_json(
                f"{git_url}/api/v1/repos/{owner}/{repo}/contents/{path}?ref={urllib.parse.quote(branch)}",
                token=token,
                headers=hdrs,
            )
            md = ""
            if isinstance(file_obj, dict) and file_obj.get("content"):
                md = base64.b64decode(file_obj["content"]).decode("utf-8", "ignore")
            return {
                "ok": True,
                "markdown": md,
                "path": path,
                "headings": len(re.findall(r"^#{1,3} ", md, re.M)),
                "url_count": len(re.findall(r"https://[^\s)]+", md)),
                "mermaid": "```mermaid" in md.lower(),
            }
        except Exception as exc:
            return {"ok": False, "markdown": "", "error": str(exc)[:200]}
