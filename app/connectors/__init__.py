"""Connector package — one Python module per connector type."""

from app.connectors.registry import get, register, register_all

__all__ = ["get", "register", "register_all"]
