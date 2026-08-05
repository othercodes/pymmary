from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

FORCE_VARIABLE = "PYMMARY_FORCE"

# (agent name, variable, exact value the variable must hold — None means "any non-empty value")
_SIGNALS: tuple[tuple[str, str, str | None], ...] = (
    ("claude-code", "CLAUDECODE", None),
    ("cursor", "CURSOR_TRACE_ID", None),
    ("devin", "TERM_PROGRAM", "Devin"),
)

_GEMINI_PREFIX = "GEMINI_CLI_"


@dataclass(frozen=True)
class AgentInfo:
    """The agent pymmary believes is running the host tool."""

    name: str


def is_agent_environment(env: Mapping[str, str]) -> AgentInfo | None:
    """Identify the coding agent running us, if any.

    Pure by design: the environment is passed in, never read from ``os.environ``
    here, so detection is trivially testable and has no global state.
    """
    if env.get(FORCE_VARIABLE) == "1":
        return AgentInfo(name="forced")

    for name, variable, expected in _SIGNALS:
        value = env.get(variable)
        if not value:
            continue
        if expected is None or value == expected:
            return AgentInfo(name=name)

    if any(key.startswith(_GEMINI_PREFIX) for key in env):
        return AgentInfo(name="gemini-cli")

    return None
