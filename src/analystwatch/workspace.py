from __future__ import annotations

import re

DEFAULT_WORKSPACE_ID = "local"
WORKSPACE_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"
_WORKSPACE_ID = re.compile(WORKSPACE_ID_PATTERN)


def validate_workspace_id(value: str) -> str:
    if not value or value != value.strip() or _WORKSPACE_ID.fullmatch(value) is None:
        raise ValueError(
            "workspace_id must be non-empty, trimmed, and contain only letters, "
            "numbers, '.', '_' or '-'"
        )
    return value
