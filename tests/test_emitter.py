from __future__ import annotations

import json

import pytest

from pymmary.emitter import DEFAULT_MAX_FAILURES, max_failures_from, render, strip_ansi
from pymmary.schema import Failure, Result


def a_failure(index: int) -> Failure:
    return Failure(
        nodeid=f"tests/test_bulk.py::test_case_{index}",
        phase="call",
        file="tests/test_bulk.py",
        line=index,
        type="AssertionError",
        message=f"assert {index} == -1",
    )


def a_failing_result(count: int) -> Result:
    return Result(
        tool="pytest",
        result="failed",
        duration=0.1,
        summary={"collected": count, "failed": count},
        exit_code=1,
        failures=tuple(a_failure(index) for index in range(count)),
    )


PASSING = Result(
    tool="pytest",
    result="passed",
    duration=0.32,
    summary={"collected": 1002, "passed": 1002},
    exit_code=0,
)

FAILING = Result(
    tool="pytest",
    result="failed",
    duration=0.32,
    summary={"collected": 1002, "passed": 1000, "failed": 2},
    exit_code=1,
    failures=(
        Failure(
            nodeid="tests/test_api.py::TestAuth::test_login[user-2]",
            phase="call",
            file="tests/test_api.py",
            line=42,
            type="AssertionError",
            message="assert 401 == 200",
        ),
    ),
)

# -- envelope --


def test_render_should_emit_the_shared_envelope() -> None:
    payload = json.loads(render(PASSING))

    assert payload["tool"] == "pytest"
    assert payload["result"] == "passed"
    assert payload["duration"] == 0.32
    assert payload["summary"] == {"collected": 1002, "passed": 1002}


def test_render_should_emit_a_single_line() -> None:
    assert "\n" not in render(FAILING)


def test_render_should_emit_valid_json() -> None:
    assert json.loads(render(FAILING))["result"] == "failed"


# -- compression rules --


def test_render_should_omit_zero_valued_counts() -> None:
    result = Result(
        tool="pytest",
        result="passed",
        duration=0.1,
        summary={"collected": 3, "passed": 3, "failed": 0, "skipped": 0},
    )

    assert json.loads(render(result))["summary"] == {"collected": 3, "passed": 3}


def test_render_should_omit_failures_when_the_run_is_green() -> None:
    assert "failures" not in json.loads(render(PASSING))


def test_render_should_omit_exit_code_when_the_adapter_has_none() -> None:
    result = Result(tool="mypy", result="passed", duration=0.1, summary={"errors": 0})

    assert "exit_code" not in json.loads(render(result))


def test_render_should_keep_a_zero_exit_code() -> None:
    assert json.loads(render(PASSING))["exit_code"] == 0


def test_render_should_not_pad_the_output_with_whitespace() -> None:
    assert ", " not in render(PASSING)


def test_render_should_round_the_duration() -> None:
    result = Result(tool="pytest", result="passed", duration=0.3200000000001, summary={"passed": 1})

    assert json.loads(render(result))["duration"] == 0.32


# -- failures --


def test_render_should_emit_failures_keyed_by_nodeid() -> None:
    failures = json.loads(render(FAILING))["failures"]

    assert len(failures) == 1
    assert failures[0]["nodeid"] == "tests/test_api.py::TestAuth::test_login[user-2]"
    assert failures[0]["phase"] == "call"
    assert failures[0]["line"] == 42


def test_render_should_strip_ansi_from_failure_messages() -> None:
    result = Result(
        tool="pytest",
        result="failed",
        duration=0.1,
        summary={"failed": 1},
        failures=(
            Failure(
                nodeid="tests/test_x.py::test_y",
                phase="call",
                file="tests/test_x.py",
                line=1,
                type="AssertionError",
                message="\x1b[31massert 1 == 2\x1b[0m",
            ),
        ),
    )

    assert json.loads(render(result))["failures"][0]["message"] == "assert 1 == 2"


# -- failure cap --


def test_render_should_cap_failures_at_the_default() -> None:
    payload = json.loads(render(a_failing_result(400)))

    assert len(payload["failures"]) == DEFAULT_MAX_FAILURES


def test_render_should_say_how_many_failures_it_omitted() -> None:
    payload = json.loads(render(a_failing_result(400)))

    assert payload["failures_omitted"] == 400 - DEFAULT_MAX_FAILURES


def test_render_should_keep_the_full_count_in_the_summary_when_capping() -> None:
    payload = json.loads(render(a_failing_result(400)))

    assert payload["summary"]["failed"] == 400


def test_render_should_not_mention_omissions_when_nothing_was_dropped() -> None:
    assert "failures_omitted" not in json.loads(render(a_failing_result(3)))


def test_render_should_keep_the_first_failures_not_an_arbitrary_slice() -> None:
    payload = json.loads(render(a_failing_result(400)))

    assert payload["failures"][0]["nodeid"].endswith("::test_case_0")


def test_render_should_emit_every_failure_when_uncapped() -> None:
    payload = json.loads(render(a_failing_result(400), max_failures=0))

    assert len(payload["failures"]) == 400
    assert "failures_omitted" not in payload


def test_render_should_honour_an_explicit_cap() -> None:
    payload = json.loads(render(a_failing_result(400), max_failures=5))

    assert len(payload["failures"]) == 5
    assert payload["failures_omitted"] == 395


# -- max_failures_from --


def test_max_failures_from_should_default_when_unset() -> None:
    assert max_failures_from({}) == DEFAULT_MAX_FAILURES


def test_max_failures_from_should_read_the_environment() -> None:
    assert max_failures_from({"PYMMARY_MAX_FAILURES": "5"}) == 5


def test_max_failures_from_should_accept_zero_as_uncapped() -> None:
    assert max_failures_from({"PYMMARY_MAX_FAILURES": "0"}) == 0


@pytest.mark.parametrize("value", ["", "abc", "-1", "3.5"])
def test_max_failures_from_should_fall_back_on_a_bad_value(value: str) -> None:
    assert max_failures_from({"PYMMARY_MAX_FAILURES": value}) == DEFAULT_MAX_FAILURES


# -- strip_ansi --


def test_strip_ansi_should_remove_colour_codes() -> None:
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_strip_ansi_should_leave_plain_text_untouched() -> None:
    assert strip_ansi("plain text") == "plain text"
