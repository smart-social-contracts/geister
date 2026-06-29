"""Persistent run-state store for the E2E orchestrator."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


_DEFAULT_PATH = Path(__file__).parent / "run_state.json"


class RunState:
    """JSON-backed key/value store for cross-phase state persistence."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except Exception:
                self._data = {}

    def save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2, default=str))

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def setdefault(self, key: str, value: Any) -> Any:
        if key not in self._data:
            self.set(key, value)
        return self._data[key]

    def mark_done(self, phase: str) -> None:
        done = self._data.setdefault("done_phases", [])
        if phase not in done:
            done.append(phase)
        self.save()

    def is_done(self, phase: str) -> bool:
        return phase in self._data.get("done_phases", [])

    def __repr__(self) -> str:
        return f"RunState({self._path})"
