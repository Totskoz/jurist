"""Typed shape of one assistant turn — shared by the mock and the real path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelToolUse:
    name: str
    args: dict[str, Any]


@dataclass
class ModelTurn:
    """One assistant reply. text_deltas stream first, then tool_uses."""

    text_deltas: list[str] = field(default_factory=list)
    tool_uses: list[ModelToolUse] = field(default_factory=list)
