from __future__ import annotations

from pymmary.schema import Failure, Result

# -- Result --


def test_result_should_default_to_no_failures() -> None:
    result = Result(tool="pytest", result="passed", duration=0.32, summary={"collected": 1, "passed": 1})

    assert result.failures == ()


def test_result_should_default_to_no_exit_code() -> None:
    result = Result(tool="pytest", result="passed", duration=0.32, summary={})

    assert result.exit_code is None


def test_result_should_be_immutable() -> None:
    result = Result(tool="pytest", result="passed", duration=0.32, summary={})

    try:
        result.tool = "unittest"  # type: ignore[misc]
    except AttributeError:
        return

    raise AssertionError("Result should be frozen")


# -- Failure --


def test_failure_should_carry_the_nodeid_as_identity() -> None:
    failure = Failure(
        nodeid="tests/test_api.py::TestAuth::test_login[user-2]",
        phase="call",
        file="tests/test_api.py",
        line=42,
        type="AssertionError",
        message="assert 401 == 200",
    )

    assert failure.nodeid == "tests/test_api.py::TestAuth::test_login[user-2]"
