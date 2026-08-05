from __future__ import annotations

import json
import re
from typing import Any

from pymmary.schema import Result

_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

_DURATION_PRECISION = 3


def strip_ansi(text: str) -> str:
    """Drop ANSI escape sequences. Colour codes are noise inside a JSON string."""
    return _ANSI.sub("", text)


def render(result: Result) -> str:
    """Serialize a Result to the one-line JSON an agent reads.

    Pure function — no I/O. Two compression rules do the real work: zero-valued
    counts are dropped, and ``failures`` is absent entirely on a green run.
    """
    payload: dict[str, Any] = {"tool": result.tool, "result": result.result}

    if result.exit_code is not None:
        payload["exit_code"] = result.exit_code

    payload["duration"] = round(result.duration, _DURATION_PRECISION)
    payload["summary"] = {name: count for name, count in result.summary.items() if count}

    if result.failures:
        payload["failures"] = [
            {
                "nodeid": failure.nodeid,
                "phase": failure.phase,
                "file": failure.file,
                "line": failure.line,
                "type": failure.type,
                "message": strip_ansi(failure.message),
            }
            for failure in result.failures
        ]

    return json.dumps(payload, separators=(",", ":"))
