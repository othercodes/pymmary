from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Failure:
    """A single thing that went wrong, identified the way the host tool identifies it.

    For pytest that means ``nodeid``: the exact string you can paste back on the
    command line to re-run just this one.
    """

    nodeid: str
    phase: str
    file: str
    line: int
    type: str
    message: str


@dataclass(frozen=True)
class Result:
    """What an adapter hands to the emitter.

    ``tool``, ``result``, ``duration`` and ``summary`` are the shared envelope every
    adapter fills in. ``exit_code`` and ``failures`` are optional: an adapter sets
    them when its host tool has something to say there.
    """

    tool: str
    result: str
    duration: float
    summary: Mapping[str, int]
    exit_code: int | None = None
    failures: tuple[Failure, ...] = field(default=())
