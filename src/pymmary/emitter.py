from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pymmary.schema import Failure, Result, WarningInfo

_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

_DURATION_PRECISION = 3

DEFAULT_MAX_FAILURES = 20
"""How many failures to spell out before summarizing the rest.

Not a size limit, the JSON is smaller than the human report either way. It is a
diminishing-returns limit: an agent facing 400 failures fixes the first few and
runs again, so failures 21 to 400 cost context and buy nothing. Raise it with
``PYMMARY_MAX_FAILURES``, or set it to 0 to keep every last one.
"""

MAX_FAILURES_VARIABLE = "PYMMARY_MAX_FAILURES"


def strip_ansi(text: str) -> str:
    """Drop ANSI escape sequences. Colour codes are noise inside a JSON string."""
    return _ANSI.sub("", text)


def max_failures_from(env: Mapping[str, str]) -> int:
    """Read the failure cap, falling back to the default on anything unusable.

    A typo in an environment variable must never take a test run down with it.
    """
    raw = env.get(MAX_FAILURES_VARIABLE)
    if raw is None:
        return DEFAULT_MAX_FAILURES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_FAILURES
    return value if value >= 0 else DEFAULT_MAX_FAILURES


def render(result: Result, max_failures: int = DEFAULT_MAX_FAILURES) -> str:
    """Serialize a Result to the one-line JSON an agent reads.

    Pure function, no I/O. Three compression rules do the real work: zero-valued
    counts are dropped, ``failures`` is absent entirely on a green run, and long
    failure lists are cut to ``max_failures`` (0 means keep them all). Whatever is
    cut is declared in ``failures_omitted``. The counts in ``summary`` always
    describe the whole run.
    """
    payload: dict[str, Any] = {"tool": result.tool, "result": result.result}

    if result.exit_code is not None:
        payload["exit_code"] = result.exit_code

    payload["duration"] = round(result.duration, _DURATION_PRECISION)
    payload["summary"] = {name: count for name, count in result.summary.items() if count}

    _add_list(payload, "failures", result.failures, max_failures, _failure_entry)
    _add_list(payload, "warnings", result.warnings, max_failures, _warning_entry)

    return json.dumps(payload, separators=(",", ":"))


def _failure_entry(failure: Failure) -> dict[str, Any]:
    return {
        "nodeid": failure.nodeid,
        "phase": failure.phase,
        "file": failure.file,
        "line": failure.line,
        "type": failure.type,
        "message": strip_ansi(failure.message),
    }


def _warning_entry(warning: WarningInfo) -> dict[str, Any]:
    return {
        "category": warning.category,
        "file": warning.file,
        "line": warning.line,
        "message": strip_ansi(warning.message),
    }


def _add_list(
    payload: dict[str, Any],
    key: str,
    items: Sequence[Any],
    cap: int,
    entry: Callable[[Any], dict[str, Any]],
) -> None:
    """Attach a list of problems, capped, or leave the key out entirely.

    Capped before the entries are built, so what the cap drops costs nothing.
    Warnings share the failure cap: same kind of list, and a second knob would be a
    second thing to explain.
    """
    if not items:
        return
    shown = items if cap == 0 else items[:cap]
    payload[key] = [entry(item) for item in shown]
    omitted = len(items) - len(shown)
    if omitted:
        payload[f"{key}_omitted"] = omitted
