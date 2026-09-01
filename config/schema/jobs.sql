-- Eval jobs table — kaif-value contract v1.
-- Loaded from eval-designer store.schema.file (default schema/jobs.sql).
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
