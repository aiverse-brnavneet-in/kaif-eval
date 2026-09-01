"""Connector registry — dispatch by connector name from source YAML."""

from __future__ import annotations

from app.connectors.base import Connector

_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    name = str(getattr(connector, "name", "") or "").strip().lower()
    if not name:
        raise ValueError("connector missing name")
    _REGISTRY[name] = connector


def get(name: str) -> Connector | None:
    return _REGISTRY.get(str(name or "").strip().lower())


def register_all() -> None:
    from app.connectors.api import ApiConnector
    from app.connectors.gitea import GiteaConnector
    from app.connectors.jaeger import JaegerConnector
    from app.connectors.kagent import KagentConnector
    from app.connectors.llm import LlmConnector
    from app.connectors.prometheus import PrometheusConnector

    for conn in (
        JaegerConnector(),
        KagentConnector(),
        PrometheusConnector(),
        GiteaConnector(),
        LlmConnector(),
        ApiConnector(),
    ):
        register(conn)
