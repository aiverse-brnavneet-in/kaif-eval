"""Job store. Eight-column contract with kaif-value.

Postgres is the default (KAIF_EVAL_STORE_URL). SQLite path remains for local
files / one-time migration.

Columns: job_id, outcome, started_at, ended_at, labels, evaluation,
spend_in_usd, time_taken_sec. Labels are [{level, key, value}, ...].
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from app.labels import pack


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  outcome TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL DEFAULT '',
  ended_at TEXT NOT NULL DEFAULT '',
  labels TEXT NOT NULL DEFAULT '[]',
  evaluation TEXT NOT NULL DEFAULT '{}',
  spend_in_usd TEXT NOT NULL DEFAULT '{}',
  time_taken_sec DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_started ON jobs(started_at);
"""

DEFAULT_SCHEMA = SCHEMA

FAT_MARKERS = (
    "card_json",
    "quality_score",
    "usd_est",
    "t_deliver_s",
    "session_id",
    "eval",
)


def _parse_json(raw, default):
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        out = json.loads(raw)
    except Exception:
        return default
    return out if isinstance(out, type(default)) or default == {} else default


def _dumps(obj) -> str:
    if isinstance(obj, str):
        return obj
    return json.dumps(obj if obj is not None else {})


def evaluation_from_legacy(d: dict, card: dict) -> dict:
    ev = _parse_json(d.get("eval") or card.get("eval"), {})
    skipped = []
    secs = ev.get("sections") if isinstance(ev.get("sections"), dict) else {}
    for name, block in secs.items():
        if isinstance(block, dict) and (block.get("skipped") or block.get("skip_reason")):
            skipped.append(str(name))
    kagent = {}
    turns = card.get("user_turns")
    if turns is None:
        turns = d.get("user_turns")
    if turns not in (None, ""):
        kagent["user_turns"] = int(float(turns or 0))
    art = card.get("artifact") if isinstance(card.get("artifact"), dict) else {}
    if not art and (d.get("artifact_sha") or d.get("artifact_path") or d.get("artifact_url")):
        art = {
            "sha": d.get("artifact_sha") or None,
            "path": d.get("artifact_path") or None,
            "url": d.get("artifact_url") or None,
        }
    if art:
        kagent["artifact"] = art
    status = "ok"
    err = card.get("error") or ""
    if str(d.get("status") or card.get("status") or "") == "NO_TRACES" or str(err) == "no_traces":
        status = "no_traces"
        err = err or "no_traces"
    total = ev.get("score")
    if total is None:
        total = d.get("quality_score") or card.get("quality_score") or 0
    out = {
        "total_score": total,
        "status": status,
        "sections": secs,
        "skipped": skipped,
        "sources": {"kagent": kagent} if kagent else {},
    }
    if status == "no_traces":
        out["error"] = str(err)
    if ev.get("usd_judge") is not None:
        out["usd_judge"] = ev.get("usd_judge")
    if ev.get("tokens_judge_in") is not None:
        out["tokens_judge_in"] = ev.get("tokens_judge_in")
    if ev.get("tokens_judge_out") is not None:
        out["tokens_judge_out"] = ev.get("tokens_judge_out")
    return out


def spend_from_legacy(d: dict, card: dict, evaluation: dict) -> dict:
    total = float(d.get("usd_est") or card.get("usd_est") or 0)
    judge = card.get("usd_judge")
    if judge in (None, ""):
        judge = evaluation.get("usd_judge") or 0
    agent = card.get("usd_agent")
    if agent in (None, ""):
        agent = max(0.0, total - float(judge or 0))
    return {
        "agent": round(float(agent or 0), 6),
        "eval": round(float(judge or 0), 6),
        "total": round(total, 6),
        "tokens_in": float(d.get("tokens_in") or card.get("tokens_in") or 0),
        "tokens_out": float(d.get("tokens_out") or card.get("tokens_out") or 0),
        "source": str(d.get("token_source") or card.get("token_source") or ""),
    }


def wrap_evaluation(eval_doc: dict, *, status: str = "ok", sources: dict | None = None, error: str = "") -> dict:
    """Turn quality.py eval_doc into the evaluation JSON contract."""
    ev = dict(eval_doc) if isinstance(eval_doc, dict) else {}
    secs = ev.get("sections") if isinstance(ev.get("sections"), dict) else {}
    skipped = []
    for name, block in secs.items():
        if isinstance(block, dict) and (block.get("skipped") or block.get("skip_reason")):
            skipped.append(str(name))
    out = {
        "total_score": ev.get("score") if ev.get("score") is not None else 0,
        "status": status,
        "sections": secs,
        "skipped": skipped,
        "sources": sources or {},
    }
    if error:
        out["error"] = error
    for k in ("usd_judge", "tokens_judge_in", "tokens_judge_out", "formula"):
        if ev.get(k) is not None:
            out[k] = ev.get(k)
    return out


class JobStore:
    def __init__(
        self,
        path: str = "",
        label_cfg: dict | None = None,
        url: str = "",
        schema_ddl: str = "",
    ):
        self._label_cfg = label_cfg or {}
        self._schema_ddl = (schema_ddl or "").strip() or DEFAULT_SCHEMA
        url = (url or os.environ.get("KAIF_EVAL_STORE_URL") or "").strip()
        path = (path or os.environ.get("KAIF_EVAL_DB") or "").strip()
        if url:
            self._init_postgres(url)
        elif path:
            self._init_sqlite(path)
        else:
            raise SystemExit("store.connection.url or path is required (see eval-designer store)")

    def _init_postgres(self, url: str) -> None:
        try:
            import psycopg
        except ImportError as e:
            raise SystemExit("postgres store needs psycopg (pip install 'psycopg[binary]')") from e
        self._driver = "postgres"
        self._conn = psycopg.connect(url, autocommit=True)
        self.path = "postgres"
        self._exec_schema()

    def _init_sqlite(self, path: str) -> None:
        self._driver = "sqlite"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(self._schema_ddl)
        self._conn.commit()
        self._migrate_to_v2()

    def _sql(self, sql: str) -> str:
        if self._driver == "postgres":
            return sql.replace("?", "%s")
        return sql

    def _exec(self, sql: str, params=()):
        sql = self._sql(sql)
        if self._driver == "postgres":
            return self._conn.execute(sql, params)
        return self._conn.execute(sql, params)

    def _exec_schema(self) -> None:
        for stmt in self._schema_ddl.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)

    def _cols(self) -> set:
        if self._driver == "postgres":
            cur = self._conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'jobs'"
            )
            return {r["column_name"] if isinstance(r, dict) else r[0] for r in cur}
        return {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}

    def _migrate_to_v2(self) -> None:
        if self._driver != "sqlite":
            return
        cols = self._cols()
        if "evaluation" in cols and "card_json" not in cols and "eval" not in cols:
            return
        if "job_id" not in cols:
            return
        rows = [dict(r) for r in self._conn.execute("SELECT * FROM jobs").fetchall()]
        self._conn.execute("DROP INDEX IF EXISTS jobs_started")
        self._conn.execute("DROP INDEX IF EXISTS jobs_flow")
        self._conn.execute("ALTER TABLE jobs RENAME TO jobs_legacy")
        self._conn.executescript(self._schema_ddl)
        for d in rows:
            self._insert_v2(self._legacy_row(d))
        self._conn.execute("DROP TABLE jobs_legacy")
        self._conn.commit()

    def _legacy_row(self, d: dict) -> dict:
        card = _parse_json(d.get("card_json"), {})
        labels = d.get("labels")
        if not labels:
            labels = pack(
                self._label_cfg,
                {
                    "flow": d.get("flow") or card.get("flow") or "",
                    "scenario": d.get("scenario") or card.get("scenario") or "",
                    "agent": d.get("agent") or card.get("agent") or "",
                    "skill": d.get("skill") or card.get("skill") or "",
                },
            )
        else:
            labels = _parse_json(labels, [])
        evaluation = evaluation_from_legacy(d, card if isinstance(card, dict) else {})
        spend = spend_from_legacy(d, card if isinstance(card, dict) else {}, evaluation)
        t_sec = d.get("time_taken_sec")
        if t_sec in (None, ""):
            t_sec = d.get("t_deliver_s") or card.get("t_deliver_s") or 0
        return {
            "job_id": str(d.get("job_id") or d.get("run_id") or ""),
            "outcome": str(d.get("outcome") or card.get("outcome") or ""),
            "started_at": str(d.get("started_at") or card.get("started_at") or ""),
            "ended_at": str(d.get("ended_at") or card.get("ended_at") or ""),
            "labels": labels,
            "evaluation": evaluation,
            "spend_in_usd": spend,
            "time_taken_sec": float(t_sec or 0),
        }

    def _insert_v2(self, d: dict) -> None:
        job_id = str(d.get("job_id") or "")
        if not job_id:
            return
        self._exec(
            """
            INSERT INTO jobs (
              job_id, outcome, started_at, ended_at, labels,
              evaluation, spend_in_usd, time_taken_sec
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
              outcome=excluded.outcome,
              started_at=excluded.started_at,
              ended_at=excluded.ended_at,
              labels=excluded.labels,
              evaluation=excluded.evaluation,
              spend_in_usd=excluded.spend_in_usd,
              time_taken_sec=excluded.time_taken_sec
            """,
            (
                job_id,
                str(d.get("outcome") or ""),
                str(d.get("started_at") or ""),
                str(d.get("ended_at") or ""),
                _dumps(d.get("labels") if d.get("labels") is not None else []),
                _dumps(d.get("evaluation") if d.get("evaluation") is not None else {}),
                _dumps(d.get("spend_in_usd") if d.get("spend_in_usd") is not None else {}),
                float(d.get("time_taken_sec") or 0),
            ),
        )

    def upsert_job(self, row: dict) -> None:
        self._insert_v2(row)
        if self._driver == "sqlite":
            self._conn.commit()

    def upsert_card(self, card: dict) -> None:
        """Accept a worker card and store the eight-column row."""
        job_id = str(card.get("run_id") or card.get("job_id") or "")
        if not job_id:
            return
        labels = card.get("labels")
        if not isinstance(labels, list):
            labels = pack(
                self._label_cfg,
                {
                    "flow": card.get("flow") or "",
                    "scenario": card.get("scenario") or "",
                    "agent": card.get("agent") or "",
                    "skill": card.get("skill") or "",
                },
            )
        evaluation = card.get("evaluation")
        if not isinstance(evaluation, dict):
            sources = {}
            kagent = {}
            if card.get("user_turns") is not None:
                kagent["user_turns"] = int(card.get("user_turns") or 0)
            if isinstance(card.get("artifact"), dict):
                kagent["artifact"] = card.get("artifact")
            if kagent:
                sources["kagent"] = kagent
            status = "no_traces" if str(card.get("status") or "") == "NO_TRACES" else "ok"
            evaluation = wrap_evaluation(
                card.get("eval") if isinstance(card.get("eval"), dict) else {},
                status=status,
                sources=sources,
                error=str(card.get("error") or ""),
            )
        spend = card.get("spend_in_usd")
        if not isinstance(spend, dict):
            spend = {
                "agent": float(card.get("usd_agent") or 0),
                "eval": float(card.get("usd_judge") or 0),
                "total": float(card.get("usd_est") or 0),
                "tokens_in": float(card.get("tokens_in") or 0),
                "tokens_out": float(card.get("tokens_out") or 0),
                "source": str(card.get("token_source") or "tempo"),
            }
        t_sec = card.get("time_taken_sec")
        if t_sec in (None, ""):
            t_sec = card.get("t_deliver_s") or 0
        self.upsert_job(
            {
                "job_id": job_id,
                "outcome": str(card.get("outcome") or ""),
                "started_at": str(card.get("started_at") or ""),
                "ended_at": str(card.get("ended_at") or ""),
                "labels": labels,
                "evaluation": evaluation,
                "spend_in_usd": spend,
                "time_taken_sec": float(t_sec or 0),
            }
        )

    def load_rows(self) -> list[dict]:
        keys = (
            "job_id",
            "outcome",
            "started_at",
            "ended_at",
            "labels",
            "evaluation",
            "spend_in_usd",
            "time_taken_sec",
        )
        cur = self._exec(
            "SELECT job_id, outcome, started_at, ended_at, labels, evaluation, spend_in_usd, time_taken_sec FROM jobs"
        )
        out = []
        for r in cur:
            if isinstance(r, dict):
                d = r
            elif hasattr(r, "keys"):
                d = {k: r[k] for k in r.keys()}
            else:
                d = dict(zip(keys, r))
            out.append(
                {
                    "job_id": d["job_id"],
                    "outcome": d["outcome"],
                    "started_at": d["started_at"],
                    "ended_at": d["ended_at"],
                    "labels": _parse_json(d["labels"], []),
                    "evaluation": _parse_json(d["evaluation"], {}),
                    "spend_in_usd": _parse_json(d["spend_in_usd"], {}),
                    "time_taken_sec": float(d["time_taken_sec"] or 0),
                }
            )
        return out

    def load_cards(self) -> list[dict]:
        from app.labels import apply_to_card

        return [apply_to_card(_fallback_card(r)) for r in self.load_rows()]


def _fallback_card(row: dict) -> dict:
    ev = dict(row.get("evaluation") or {})
    if "score" not in ev and ev.get("total_score") is not None:
        ev["score"] = ev.get("total_score")
    spend = row.get("spend_in_usd") if isinstance(row.get("spend_in_usd"), dict) else {}
    kagent = (ev.get("sources") or {}).get("kagent") if isinstance(ev.get("sources"), dict) else {}
    kagent = kagent if isinstance(kagent, dict) else {}
    status = "NO_TRACES" if ev.get("status") == "no_traces" else ""
    return {
        "job_id": row.get("job_id"),
        "run_id": row.get("job_id"),
        "outcome": row.get("outcome"),
        "status": status,
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "labels": row.get("labels") or [],
        "eval": ev,
        "quality_score": ev.get("total_score") or 0,
        "usd_est": spend.get("total") or 0,
        "usd_agent": spend.get("agent") or 0,
        "usd_judge": spend.get("eval") or 0,
        "t_deliver_s": row.get("time_taken_sec") or 0,
        "user_turns": kagent.get("user_turns") or 0,
        "artifact": kagent.get("artifact") or {},
        "error": ev.get("error") or "",
    }
