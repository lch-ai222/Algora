"""Local, side-effect-free package diagnostics for the CLI doctor command."""

from __future__ import annotations

from mini_store.version import VERSION


def health_report() -> dict[str, str]:
    return {"package": "mini_store", "status": "unknown", "version": VERSION}
