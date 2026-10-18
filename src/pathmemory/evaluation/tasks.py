"""Task-definition fingerprints shared by memory building and evaluation."""

import hashlib
import json

from pathmemory.site.tasks import TASKS_BY_ID


def task_sha(task_id: str) -> str:
    """Fingerprint of a task definition (goal and checker), so two runs under one id but different
    definitions are never pooled silently."""
    s = TASKS_BY_ID[task_id]
    cells = [repr(c.cell_contents) for c in (getattr(s.check, "__closure__", None) or [])]
    blob = json.dumps([s.goal, s.kind, s.answer, s.url_pattern, getattr(s.check, "__qualname__", None), cells])
    return hashlib.sha256(blob.encode()).hexdigest()[:12]
