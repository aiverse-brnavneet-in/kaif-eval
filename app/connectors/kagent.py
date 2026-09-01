"""kagent connector: session events → normalized job record."""

from __future__ import annotations

import json
import re
import urllib.parse

from app.http import http_json


def _normalize_rules(rules: list | None) -> list[tuple[str, tuple[str, ...]]]:
    out: list[tuple[str, tuple[str, ...]]] = []
    for row in rules or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        kws = row.get("keywords") or row.get("keyword") or []
        if isinstance(kws, str):
            kws = [kws]
        out.append((name, tuple(str(k).strip() for k in kws if str(k).strip())))
    return out


def classify_scenario(text: str, allowed: list[str] | None = None, rules: list | None = None) -> str:
    low = (text or "").lower()
    allowed_set = [str(x) for x in (allowed or []) if str(x).strip()]
    if not low:
        return "unknown"
    for name, kws in _normalize_rules(rules):
        if allowed_set and name not in allowed_set:
            continue
        if any(k in low for k in kws):
            return name
    return "unknown"


def _last_skill(blob: str, skills: list[str] | None = None, catalog: list[str] | None = None) -> str:
    merged = [str(s) for s in (skills or catalog or []) if str(s).strip()]
    if not merged:
        return "unknown"
    alt = "|".join(re.escape(s) for s in merged)
    found = re.findall(rf"/skills/({alt})/", blob) + re.findall(
        rf'"command"\s*:\s*"({alt})"', blob
    )
    return found[-1] if found else "unknown"


def _event_payload(ev: object) -> dict:
    if not isinstance(ev, dict):
        return {}
    data = ev.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return {}
    return data if isinstance(data, dict) else {}


def _maybe_json(v: object) -> dict | None:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            obj = json.loads(v)
        except Exception:
            return None
        return obj if isinstance(obj, dict) else None
    return None


def _adk_parts(payload: dict) -> list[dict]:
    content = payload.get("content")
    if isinstance(content, dict):
        parts = content.get("parts") or []
        return [p for p in parts if isinstance(p, dict)]
    return []


def count_user_turns(events: list) -> int:
    n = 0
    for ev in events:
        payload = _event_payload(ev)
        content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
        if str(content.get("role") or "") != "user":
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("function_call") or part.get("function_response"):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                n += 1
                break
    return n


def last_tool_name(events: list) -> str:
    last = ""
    for ev in events:
        payload = _event_payload(ev)
        for part in _adk_parts(payload):
            fc = part.get("function_call") if isinstance(part.get("function_call"), dict) else {}
            if fc.get("name"):
                last = str(fc.get("name"))
    return last


def all_tool_names(events: list) -> list[str]:
    names = []
    for ev in events:
        payload = _event_payload(ev)
        for part in _adk_parts(payload):
            fc = part.get("function_call") if isinstance(part.get("function_call"), dict) else {}
            if fc.get("name"):
                names.append(str(fc.get("name")))
    return names


def infer_job(
    sess_wrap: dict,
    flow: str,
    agent: str,
    scenarios: list[str] | None = None,
    skills: list[str] | None = None,
    scenario_rules: list | None = None,
    skill_catalog: list[str] | None = None,
    runtime_cfg: dict | None = None,
) -> dict | None:
    sess = sess_wrap.get("session") or sess_wrap
    sid = str(sess.get("id") or "")
    if not sid:
        return None
    created = str(sess.get("created_at") or "")
    updated = str(sess.get("updated_at") or "")
    events = sess_wrap.get("events") or []
    if not events:
        return None
    rcfg = runtime_cfg if isinstance(runtime_cfg, dict) else {}
    publish_tool = str(rcfg.get("publish_tool") or "").strip()
    pending_tools = {str(x) for x in (rcfg.get("pending_tools") or []) if str(x).strip()}
    publish_field = str(rcfg.get("publish_result_field") or "sha").strip() or "sha"
    blob = json.dumps(events)
    if created and created == updated and "function_" not in blob:
        return None
    first_user = ""
    artifact_sha = artifact_url = artifact_path = None
    store_report_ok = False
    card_status = None
    for ev in events:
        payload = _event_payload(ev)
        for part in _adk_parts(payload):
            text = part.get("text")
            role = str((payload.get("content") or {}).get("role") or "")
            if isinstance(text, str) and len(text) >= 20 and not first_user and role == "user":
                first_user = text
            fc = part.get("function_call") if isinstance(part.get("function_call"), dict) else {}
            fr = part.get("function_response") if isinstance(part.get("function_response"), dict) else {}
            if publish_tool and str(fr.get("name") or "") == publish_tool:
                resp = fr.get("response") if isinstance(fr.get("response"), dict) else {}
                if resp.get("isError"):
                    continue
                chunks = resp.get("content") or []
                raw = ""
                if isinstance(chunks, list) and chunks:
                    raw = str((chunks[0] or {}).get("text") or "")
                parsed = _maybe_json(raw) or _maybe_json(resp.get("structuredContent"))
                if isinstance(parsed, dict) and parsed.get("result") and not parsed.get("sha"):
                    parsed = _maybe_json(parsed.get("result")) or parsed
                if isinstance(parsed, dict) and parsed.get(publish_field):
                    store_report_ok = True
                    artifact_sha = str(parsed.get(publish_field))
                    artifact_url = str(parsed.get("html_url") or artifact_url or "")
                    artifact_path = str(parsed.get("path") or artifact_path or "")
            if str(fc.get("name") or "") == "store_run_record":
                card = (fc.get("args") or {}).get("card_json")
                card = card if isinstance(card, dict) else _maybe_json(card)
                if isinstance(card, dict) and card.get("status"):
                    card_status = str(card.get("status"))
    last_tool = last_tool_name(events)
    tools = all_tool_names(events)
    if store_report_ok and artifact_sha:
        status = "PUBLISHED"
    elif pending_tools and last_tool in pending_tools:
        status = "BLOCKED_ON_USER"
    elif card_status:
        status = card_status
    else:
        status = "INCOMPLETE"
    return {
        "run_id": sid,
        "job_id": sid,
        "session_id": sid,
        "flow": flow,
        "scenario": classify_scenario(
            first_user or str(sess.get("name") or ""), scenarios, scenario_rules
        ),
        "agent": agent,
        "skill": _last_skill(blob, skills, skill_catalog),
        "status": status,
        "last_tool": last_tool,
        "tools": tools,
        "user_turns": count_user_turns(events),
        "started_at": created,
        "ended_at": updated,
        "artifact": {"sha": artifact_sha, "url": artifact_url, "path": artifact_path},
        "source": "kagent-session",
        "store_report_ok": store_report_ok,
    }


class KagentConnector:
    name = "kagent"

    def fetch(self, hub, src: dict, job_id: str, extra: dict) -> dict:
        client = _KagentClient(
            str(src.get("api") or src.get("url") or ""),
            str(src.get("agent_id") or ""),
            str(extra.get("flow") or hub.flow or ""),
            str(extra.get("agent") or hub.agent or ""),
            extra.get("scenarios") or [],
            extra.get("skills") or [],
            scenario_rules=extra.get("scenario_inference") or [],
            skill_catalog=extra.get("skill_catalog") or [],
            runtime_cfg=hub.runtime_cfg,
        )
        job = client.get_job(job_id)
        if not job:
            return {"ok": False, "error": "no_session"}
        out = dict(job)
        out["ok"] = True
        return out


class _KagentClient:
    def __init__(
        self,
        api: str,
        agent_id: str,
        flow: str,
        agent: str,
        scenarios: list[str] | None = None,
        skills: list[str] | None = None,
        scenario_rules: list | None = None,
        skill_catalog: list[str] | None = None,
        runtime_cfg: dict | None = None,
    ):
        self.api = api.rstrip("/")
        self.agent_id = agent_id
        self.flow = flow
        self.agent = agent
        self.scenarios = list(scenarios or [])
        self.skills = list(skills or [])
        self.scenario_rules = list(scenario_rules or [])
        self.skill_catalog = list(skill_catalog or [])
        self.runtime_cfg = runtime_cfg if isinstance(runtime_cfg, dict) else {}
        self.watch: dict[str, str] = {}

    def watch_session(self, sid: str, user_id: str = "") -> None:
        sid = (sid or "").strip()
        if not sid:
            return
        self.watch[sid] = (user_id or "").strip() or f"A2A_USER_{sid}"

    def _session_get(self, sid: str, user_id: str = "") -> dict | None:
        q = f"?user_id={urllib.parse.quote(user_id)}" if user_id else ""
        wrap = http_json(f"{self.api}/api/sessions/{sid}{q}")
        data = wrap.get("data") if isinstance(wrap, dict) else wrap
        return data if isinstance(data, dict) else None

    def get_job(self, job_id: str) -> dict | None:
        """Keyed fetch only — never lists sessions."""
        job_id = (job_id or "").strip()
        if not job_id or not self.api:
            return None
        uid = f"A2A_USER_{job_id}"
        for try_uid in ("", uid):
            try:
                data = self._session_get(job_id, try_uid)
            except Exception:
                data = None
            if isinstance(data, dict):
                job = infer_job(
                    data,
                    self.flow,
                    self.agent,
                    self.scenarios,
                    self.skills,
                    self.scenario_rules,
                    self.skill_catalog,
                    self.runtime_cfg,
                )
                if job:
                    job["job_id"] = job_id
                    job["run_id"] = job_id
                    return job
        return None
