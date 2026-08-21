from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .models import SourceDefinition

_SOURCE_LIST = TypeAdapter(list[SourceDefinition])


def load_sources(path: str | Path) -> list[SourceDefinition]:
    source_path = Path(path)
    payload: Any = json.loads(source_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "sources" in payload:
        payload = payload["sources"]
    return _SOURCE_LIST.validate_python(payload)
