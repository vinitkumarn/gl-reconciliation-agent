"""Audit log: one JSON line per case run. Ids, hashes, token counts and status only.

Never written here: packet text, model text, descriptions, supplier names or issue messages
(those can quote model text). Issues are recorded as counts per code (GUARD1, GUARD2, ...).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .schema import CaseReport


def record(report: CaseReport, *, model: str | None, prompt_version: str | None,
           packet_sha256: str | None, response_sha256: str | None,
           error_type: str | None = None) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_id": report.case_id, "by": report.by, "model": model,
        "prompt_version": prompt_version, "packet_sha256": packet_sha256,
        "response_sha256": response_sha256, "cache_hit": report.cache_hit,
        "attempts": report.attempts, "input_tokens": report.input_tokens,
        "output_tokens": report.output_tokens,
        "cache_read_input_tokens": report.cache_read_input_tokens,
        "cache_creation_input_tokens": report.cache_creation_input_tokens,
        "cost_usd": str(report.cost_usd), "cost_saved_usd": str(report.cost_saved_usd),
        "latency_ms": report.latency_ms, "status": report.status,
        "confidence": report.confidence,
        "item_ids": [i.item_id for i in report.items],
        "issue_counts": dict(Counter(x.split(":", 1)[0] for x in report.issues)),
        "error_type": error_type,
    }


def write(path: Path, entry: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
