from __future__ import annotations

import json

import pytest

from pymmary.emitter import DEFAULT_MAX_FAILURES, MAX_CAPTURE_CHARS, max_failures_from, render, strip_ansi
from pymmary.schema import Failure, Result, WarningInfo


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


def a_warning_result(count: int) -> Result:
    return Result(
        tool="pytest",
        result="passed",
        duration=0.1,
        summary={"collected": 1, "passed": 1, "warnings": count},
        exit_code=0,
        warnings=tuple(
            WarningInfo(
                category="DeprecationWarning",
                file="tests/test_bulk.py",
                line=index,
                message=f"thing_{index}() is deprecated",
            )
            for index in range(count)
        ),
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


def test_render_should_omit_zero_valued_counts() -> None:
    result = Result(
        tool="pytest",
        result="passed",
        duration=0.1,
        summary={"collected": 3, "passed": 3, "failed": 0, "skipped": 0},
    )

    assert json.loads(render(result))["summary"] == {"collected": 3, "passed": 3}


@pytest.mark.parametrize("key", ["failures", "warnings"])
def test_render_should_omit_an_empty_list_rather_than_emit_it(key: str) -> None:
    assert key not in json.loads(render(PASSING))


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


def test_render_should_strip_ansi_from_warning_messages() -> None:
    result = Result(
        tool="pytest",
        result="passed",
        duration=0.1,
        summary={"warnings": 1},
        warnings=(WarningInfo(category="UserWarning", file="tests/test_x.py", line=1, message="\x1b[31mnoisy\x1b[0m"),),
    )

    assert json.loads(render(result))["warnings"][0]["message"] == "noisy"


def test_render_should_emit_warnings() -> None:
    warnings = json.loads(render(a_warning_result(1)))["warnings"]

    assert warnings == [
        {
            "category": "DeprecationWarning",
            "file": "tests/test_bulk.py",
            "line": 0,
            "message": "thing_0() is deprecated",
        }
    ]


def a_failure_capturing(stdout: str) -> Result:
    return Result(
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
                message="assert 0 == 1",
                stdout=stdout,
            ),
        ),
    )


@pytest.mark.parametrize("stream", ["stdout", "stderr", "log"])
def test_render_should_omit_a_stream_that_captured_nothing(stream: str) -> None:
    assert stream not in json.loads(render(FAILING))["failures"][0]


def test_render_should_keep_the_tail_of_a_long_capture() -> None:
    stdout = "".join(f"line {index}\n" for index in range(2000))

    emitted = json.loads(render(a_failure_capturing(stdout)))["failures"][0]["stdout"]

    assert emitted.endswith("line 1999\n")
    assert len(emitted) < len(stdout)


def test_render_should_say_how_much_of_a_capture_it_dropped() -> None:
    stdout = "x" * 5000

    emitted = json.loads(render(a_failure_capturing(stdout)))["failures"][0]["stdout"]

    assert emitted.startswith(f"[{5000 - MAX_CAPTURE_CHARS} characters omitted]\n")


def test_render_should_leave_a_short_capture_whole() -> None:
    emitted = json.loads(render(a_failure_capturing("two\nlines\n")))["failures"][0]["stdout"]

    assert emitted == "two\nlines\n"


@pytest.mark.parametrize("key", ["failures", "warnings"])
def test_render_should_cap_a_list_and_say_what_it_dropped(key: str) -> None:
    result = a_failing_result(400) if key == "failures" else a_warning_result(400)

    payload = json.loads(render(result))

    assert len(payload[key]) == DEFAULT_MAX_FAILURES
    assert payload[f"{key}_omitted"] == 400 - DEFAULT_MAX_FAILURES


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


def test_max_failures_from_should_default_when_unset() -> None:
    assert max_failures_from({}) == DEFAULT_MAX_FAILURES


def test_max_failures_from_should_read_the_environment() -> None:
    assert max_failures_from({"PYMMARY_MAX_FAILURES": "5"}) == 5


def test_max_failures_from_should_accept_zero_as_uncapped() -> None:
    assert max_failures_from({"PYMMARY_MAX_FAILURES": "0"}) == 0


@pytest.mark.parametrize("value", ["", "abc", "-1", "3.5"])
def test_max_failures_from_should_fall_back_on_a_bad_value(value: str) -> None:
    assert max_failures_from({"PYMMARY_MAX_FAILURES": value}) == DEFAULT_MAX_FAILURES


def test_strip_ansi_should_remove_colour_codes() -> None:
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_strip_ansi_should_leave_plain_text_untouched() -> None:
    assert strip_ansi("plain text") == "plain text"
