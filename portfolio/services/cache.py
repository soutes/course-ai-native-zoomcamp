"""Tiny on-disk cache for GitHub responses.

Re-running `weekly triage` should cost zero requests. The cache is keyed by URL and
scoped by a namespace so a later weekly report can cache per ISO week.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings


class Cache:
    def __init__(self, namespace: str, enabled: bool = True) -> None:
        self.dir = Path(settings.WEEKLY_CACHE_DIR) / namespace
        self.enabled = enabled
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        return self.dir / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt cache entry must never break a run.
            return None

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        self._path(key).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def clear(self) -> int:
        if not self.dir.exists():
            return 0
        files = list(self.dir.glob("*.json"))
        for f in files:
            f.unlink()
        return len(files)
