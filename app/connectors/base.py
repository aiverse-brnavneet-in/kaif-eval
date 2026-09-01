"""Connector protocol — one Python module per connector type."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.sources import SourceHub


class Connector(Protocol):
    name: str

    def fetch(self, hub: SourceHub, src: dict, job_id: str, extra: dict) -> dict: ...
