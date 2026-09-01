"""Built-in Layer A rubric (legacy). Prefer weighted rules in the flow YAML."""

from __future__ import annotations

import re

LAYER_A = (
    ("published", 25),
    ("required_sections", 15),
    ("diagram", 10),
    ("score_matrix_script", 10),
    ("tco_script", 10),
    ("evidence_urls", 10),
    ("fact_vs_assumption", 10),
    ("status_contract", 10),
)
LAYER_A_CHECKS = [k for k, _ in LAYER_A]


def empty_breakdown() -> dict[str, float]:
    return {k: 0.0 for k in LAYER_A_CHECKS}


def layer_a(markdown: str | None, sha: str | None) -> tuple[float, dict]:
    bd = empty_breakdown()
    if not sha:
        return 0.0, bd
    md = markdown or ""
    low = md.lower()
    bd["published"] = 25
    headings = len(re.findall(r"^#{1,3} ", md, re.M))
    bd["required_sections"] = 15 if headings >= 8 else (8 if headings >= 4 else 0)
    bd["diagram"] = 10 if "```mermaid" in low else 0
    bd["score_matrix_script"] = (
        10 if ("weighted total" in low or "score_matrix" in low) else 0
    )
    bd["tco_script"] = 10 if ("tco" in low and ("capex" in low or "opex" in low)) else 0
    urls = len(re.findall(r"https://[^\s)]+", md))
    bd["evidence_urls"] = 10 if urls >= 3 else (5 if urls >= 1 else 0)
    bd["fact_vs_assumption"] = (
        10 if ("assumption" in low or re.search(r"\bfact\b", low)) else 0
    )
    bd["status_contract"] = 10
    return float(sum(bd.values())), bd
