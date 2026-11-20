"""Response cache on disk: one JSON file per key in data/cache/ (gitignored).

key = sha256(model id + prompt version + facts packet). The prompt version is the hash of the
system prompt text, so editing the prompt (or changing the model or the facts) forces a fresh
call. Only answers that passed schema validation are stored; API errors and invalid answers
never are. A cached answer is only an answer: the guards run on it every time.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

import pydantic

from . import config
from .packet import sha256
from .schema import CaseExplanation

log = logging.getLogger("glrecon")


def cache_key(model: str, prompt_version: str, packet_text: str) -> str:
    return sha256(f"{model}\n{prompt_version}\n{packet_text}")


class ResponseCache:
    def __init__(self, folder: Path = config.CACHE_DIR):
        self.folder = Path(folder)

    def _path(self, key: str) -> Path:
        return self.folder / f"{key}.json"

    def get(self, key: str) -> tuple[CaseExplanation, Decimal] | None:
        """(answer, cost of the original call) or None. A corrupt entry counts as a miss."""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            return (CaseExplanation.model_validate(record["answer"]),
                    Decimal(record["cost_usd"]))
        except (ValueError, KeyError, TypeError, pydantic.ValidationError) as e:
            log.warning("ignoring unreadable cache entry %s: %s", path.name, e)
            return None

    def put(self, key: str, answer: CaseExplanation, cost_usd: Decimal) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        record = {"answer": answer.model_dump(mode="json"), "cost_usd": str(cost_usd)}
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(record, sort_keys=True, indent=1), encoding="utf-8")
        tmp.replace(self._path(key))
