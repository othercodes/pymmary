from __future__ import annotations

import pytest

from pymmary.detector import AgentInfo, is_agent_environment


def test_is_agent_environment_should_return_none_for_empty_environment() -> None:
    assert is_agent_environment({}) is None


def test_is_agent_environment_should_return_none_for_plain_shell() -> None:
    assert is_agent_environment({"TERM": "xterm-256color", "SHELL": "/bin/zsh"}) is None


def test_is_agent_environment_should_return_none_for_generic_ci() -> None:
    assert is_agent_environment({"CI": "true", "GITHUB_ACTIONS": "true"}) is None


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"CLAUDECODE": "1"}, "claude-code"),
        ({"CURSOR_TRACE_ID": "abc123"}, "cursor"),
        ({"TERM_PROGRAM": "Devin"}, "devin"),
        ({"GEMINI_CLI_SESSION": "xyz"}, "gemini-cli"),
    ],
)
def test_is_agent_environment_should_detect_known_agent(env: dict[str, str], expected: str) -> None:
    info = is_agent_environment(env)

    assert info == AgentInfo(name=expected)


def test_is_agent_environment_should_detect_gemini_from_any_prefixed_variable() -> None:
    assert is_agent_environment({"GEMINI_CLI_ANYTHING": "x"}) == AgentInfo(name="gemini-cli")


def test_is_agent_environment_should_ignore_term_program_from_another_terminal() -> None:
    assert is_agent_environment({"TERM_PROGRAM": "iTerm.app"}) is None


@pytest.mark.parametrize("key", ["CLAUDECODE", "CURSOR_TRACE_ID", "TERM_PROGRAM"])
def test_is_agent_environment_should_ignore_empty_value(key: str) -> None:
    assert is_agent_environment({key: ""}) is None


def test_is_agent_environment_should_detect_forced_mode() -> None:
    assert is_agent_environment({"PYMMARY_FORCE": "1"}) == AgentInfo(name="forced")


def test_is_agent_environment_should_prefer_forced_mode_over_a_real_agent() -> None:
    assert is_agent_environment({"PYMMARY_FORCE": "1", "CLAUDECODE": "1"}) == AgentInfo(name="forced")


def test_is_agent_environment_should_ignore_forced_mode_when_not_set_to_one() -> None:
    assert is_agent_environment({"PYMMARY_FORCE": "0"}) is None


def test_is_agent_environment_should_not_read_the_real_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")

    assert is_agent_environment({}) is None
