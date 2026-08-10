from __future__ import annotations

import json

import pytest

# No `-p` flag anywhere below: the pytest11 entry point auto-loads the adapter,
# so these tests exercise the exact path a real installation takes.
_SIGNALS = ("CLAUDECODE", "CURSOR_TRACE_ID", "TERM_PROGRAM", "GEMINI_CLI_SESSION", "PYMMARY_FORCE")


@pytest.fixture
def no_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every detection signal, the developer machine may well be an agent."""
    for signal in _SIGNALS:
        monkeypatch.delenv(signal, raising=False)


@pytest.fixture
def agent(no_agent: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")


def payload_of(stdout: str) -> dict:
    return json.loads(stdout.strip())


# -- no agent: strict no-op --


def test_plugin_should_leave_output_untouched_when_no_agent_is_detected(
    pytester: pytest.Pytester, no_agent: None
) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    run = pytester.runpytest_inprocess()

    run.stdout.fnmatch_lines(["*1 passed*"])
    run.assert_outcomes(passed=1)


def test_plugin_should_not_emit_json_when_no_agent_is_detected(pytester: pytest.Pytester, no_agent: None) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    run = pytester.runpytest_inprocess()

    assert "{" not in run.stdout.str()


# -- agent: compressed output --


def test_plugin_should_replace_the_report_with_a_single_json_line(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    run = pytester.runpytest_inprocess()

    assert len(run.stdout.str().strip().splitlines()) == 1


def test_plugin_should_report_a_green_run(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_one():
            assert True


        def test_two():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["tool"] == "pytest"
    assert payload["result"] == "passed"
    assert payload["exit_code"] == 0
    assert payload["summary"] == {"collected": 2, "passed": 2}


def test_plugin_should_omit_failures_on_a_green_run(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert "failures" not in payload


def test_plugin_should_report_a_failing_run(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True


        def test_bad():
            assert 401 == 200
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["result"] == "failed"
    assert payload["exit_code"] == 1
    assert payload["summary"] == {"collected": 2, "passed": 1, "failed": 1}


def test_plugin_should_identify_a_failure_by_nodeid(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_bad():
            assert 401 == 200
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["nodeid"].endswith("::test_bad")
    assert payload["failures"][0]["phase"] == "call"


def test_plugin_should_report_a_bare_assert_as_an_assertion_error(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_bad():
            assert 401 == 200
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["type"] == "AssertionError"
    assert payload["failures"][0]["message"] == "assert 401 == 200"


def test_plugin_should_keep_a_colon_inside_the_failure_message(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_bad():
            raise ValueError("host: port missing")
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["type"] == "ValueError"
    assert payload["failures"][0]["message"] == "host: port missing"


def test_plugin_should_keep_the_parametrize_id_in_the_nodeid(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import pytest


        @pytest.mark.parametrize("value", [1, 2])
        def test_bad(value):
            assert value == 1
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["nodeid"].endswith("::test_bad[2]")


def test_plugin_should_report_the_line_of_the_failure(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_bad():
            assert 401 == 200
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["line"] == 2


def test_plugin_should_report_the_line_in_the_test_file_when_an_assertion_helper_raised(
    pytester: pytest.Pytester, agent: None
) -> None:
    # unittest raises from inside its own case.py, so the crash is in the standard
    # library while the line worth reading is here. Same for any project that wraps
    # its assertions in a helper.
    pytester.makepyfile(
        """
        import unittest


        class TestAuth(unittest.TestCase):
            def test_bad(self):
                self.assertEqual(401, 200)
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["line"] == 6


def test_plugin_should_point_file_and_line_at_the_same_place(pytester: pytest.Pytester, agent: None) -> None:
    # The two came from different sources and could contradict each other: a line
    # number from the standard library against a file name from the test suite,
    # naming a coordinate that does not exist.
    pytester.makepyfile(
        """
        import unittest


        class TestAuth(unittest.TestCase):
            def test_bad(self):
                self.assertEqual(401, 200)
        """
    )

    failure = payload_of(pytester.runpytest_inprocess().stdout.str())["failures"][0]

    source = pytester.path.joinpath(failure["file"])
    assert source.exists()
    assert len(source.read_text().splitlines()) >= failure["line"]


def test_plugin_should_report_the_line_inside_a_failing_helper(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def assert_status(actual, expected):
            assert actual == expected


        def test_bad():
            assert_status(401, 200)
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["line"] == 2


def test_plugin_should_fall_back_to_the_crash_when_there_is_no_traceback(
    pytester: pytest.Pytester, agent: None
) -> None:
    # --tb=no, --tb=line and --tb=native all render entries without a file location.
    pytester.makepyfile(
        """
        def test_bad():
            assert 401 == 200
        """
    )

    failure = payload_of(pytester.runpytest_inprocess("--tb=native").stdout.str())["failures"][0]

    assert failure["file"].endswith("test_plugin_should_fall_back_to_the_crash_when_there_is_no_traceback.py")
    assert failure["line"] == 2


def test_plugin_should_survive_a_longrepr_another_plugin_replaced(pytester: pytest.Pytester, agent: None) -> None:
    # Plugins are allowed to overwrite longrepr, and a plain string has neither a
    # traceback nor a crash to read. Losing the line is fine; crashing is not.
    pytester.makeconftest(
        """
        import pytest


        @pytest.hookimpl(wrapper=True)
        def pytest_runtest_makereport(item):
            report = yield
            if report.failed:
                report.longrepr = "something ate the traceback"
            return report
        """
    )
    pytester.makepyfile(
        """
        def test_bad():
            assert 401 == 200
        """
    )

    failure = payload_of(pytester.runpytest_inprocess().stdout.str())["failures"][0]

    assert failure["file"] == "test_plugin_should_survive_a_longrepr_another_plugin_replaced.py"
    assert failure["line"] == 0
    assert failure["message"] == "something ate the traceback"


def test_plugin_should_flag_a_setup_failure_as_such(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import pytest


        @pytest.fixture
        def broken():
            raise RuntimeError("fixture exploded")


        def test_uses_broken(broken):
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["failures"][0]["phase"] == "setup"
    assert payload["failures"][0]["type"] == "RuntimeError"


def test_plugin_should_count_skipped_tests(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import pytest


        @pytest.mark.skip
        def test_skipped():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["summary"]["skipped"] == 1


def test_plugin_should_count_an_expected_failure_as_xfailed(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import pytest


        @pytest.mark.xfail
        def test_known_bug():
            assert False
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["summary"]["xfailed"] == 1
    assert payload["result"] == "passed"


def test_plugin_should_count_an_unexpected_pass_as_xpassed(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import pytest


        @pytest.mark.xfail
        def test_fixed_bug():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["summary"]["xpassed"] == 1


def test_plugin_should_still_emit_without_the_terminal_plugin(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess("-p", "no:terminal").stdout.str())

    assert payload["result"] == "passed"


def test_plugin_should_report_no_tests_collected(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile("# nothing here\n")

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["exit_code"] == 5
    assert payload["summary"] == {}


# -- collection errors: the suite never ran --


def test_plugin_should_not_call_a_collection_error_a_pass(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import this_module_does_not_exist


        def test_never_runs():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["result"] == "failed"


def test_plugin_should_describe_a_collection_error(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import this_module_does_not_exist


        def test_never_runs():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    failure = payload["failures"][0]
    assert failure["phase"] == "collect"
    assert failure["type"] == "ModuleNotFoundError"
    assert "this_module_does_not_exist" in failure["message"]


def test_plugin_should_count_a_collection_error(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import this_module_does_not_exist


        def test_never_runs():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["summary"]["error"] == 1


def test_plugin_should_not_call_an_empty_run_a_pass(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile("# nothing here\n")

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["result"] == "failed"
    assert payload["exit_code"] == 5


# -- captured output --


_NOISY_TEST = """
    import logging
    import sys


    def test_bad():
        print("connecting to db://prod")
        print("boom", file=sys.stderr)
        logging.getLogger("app").warning("cache miss")
        assert 0 == 1
    """


@pytest.fixture
def capturing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYMMARY_CAPTURE", "1")


@pytest.mark.parametrize("stream", ["stdout", "stderr", "log"])
def test_plugin_should_omit_captured_output_unless_asked(pytester: pytest.Pytester, agent: None, stream: str) -> None:
    pytester.makepyfile(_NOISY_TEST)

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert stream not in payload["failures"][0]


@pytest.mark.parametrize(
    ("stream", "expected"),
    [("stdout", "connecting to db://prod"), ("stderr", "boom"), ("log", "cache miss")],
)
def test_plugin_should_include_captured_output_when_asked(
    pytester: pytest.Pytester, agent: None, capturing: None, stream: str, expected: str
) -> None:
    pytester.makepyfile(_NOISY_TEST)

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert expected in payload["failures"][0][stream]


def test_plugin_should_omit_a_stream_that_captured_nothing(
    pytester: pytest.Pytester, agent: None, capturing: None
) -> None:
    pytester.makepyfile(
        """
        def test_bad():
            print("only stdout here")
            assert 0 == 1
        """
    )

    failure = payload_of(pytester.runpytest_inprocess().stdout.str())["failures"][0]

    assert "stdout" in failure
    assert "stderr" not in failure
    assert "log" not in failure


def test_plugin_should_carry_captured_output_across_real_xdist(
    pytester: pytest.Pytester, agent: None, capturing: None
) -> None:
    pytester.makepyfile(_NOISY_TEST)

    failure = payload_of(pytester.runpytest_subprocess("-n", "2").stdout.str())["failures"][0]

    assert "connecting to db://prod" in failure["stdout"]


# -- warnings --


@pytest.mark.parametrize(
    ("category", "expected"),
    [("DeprecationWarning", "DeprecationWarning"), ("UserWarning", "UserWarning")],
)
def test_plugin_should_describe_a_warning(pytester: pytest.Pytester, agent: None, category: str, expected: str) -> None:
    pytester.makepyfile(
        f"""
        import warnings


        def test_ok():
            warnings.warn("connect() is deprecated", {category})
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["summary"]["warnings"] == 1
    assert payload["warnings"] == [
        {
            "category": expected,
            "file": "test_plugin_should_describe_a_warning.py",
            "line": 5,
            "message": "connect() is deprecated",
        }
    ]


def test_plugin_should_keep_an_absolute_path_when_the_warning_comes_from_outside(
    pytester: pytest.Pytester, agent: None
) -> None:
    # A deprecation raised inside an installed dependency has no relative form worth
    # printing. warn_explicit sets the filename, which is otherwise the caller's.
    pytester.makepyfile(
        """
        import warnings


        def test_ok():
            warnings.warn_explicit("old api", DeprecationWarning, "/opt/lib/client.py", 42)
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["warnings"][0]["file"] == "/opt/lib/client.py"
    assert payload["warnings"][0]["line"] == 42


def test_plugin_should_collapse_a_warning_repeated_across_tests(pytester: pytest.Pytester, agent: None) -> None:
    # pytest fires the hook once per occurrence and counts every one of them. One
    # deprecation hit by thirty tests is one thing to fix, not thirty.
    pytester.makepyfile(
        """
        import warnings
        import pytest


        @pytest.mark.parametrize("value", [1, 2, 3])
        def test_ok(value):
            warnings.warn("connect() is deprecated", DeprecationWarning)
            assert value
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["summary"]["warnings"] == 1
    assert len(payload["warnings"]) == 1


def test_plugin_should_report_a_warning_raised_while_collecting(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import warnings

        warnings.warn("module level deprecation", DeprecationWarning)


        def test_ok():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["warnings"][0]["message"] == "module level deprecation"


def test_plugin_should_keep_a_green_run_green_when_it_warns(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import warnings


        def test_ok():
            warnings.warn("noisy", DeprecationWarning)
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["result"] == "passed"
    assert "failures" not in payload


# -- xdist --


def test_plugin_should_stay_silent_on_an_xdist_worker(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makeconftest(
        """
        def pytest_configure(config):
            config.workerinput = {}
        """
    )
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    run = pytester.runpytest_inprocess()

    # No summary at all, not even a human one: a worker's stdout is captured by the
    # controller and read by nobody. The run is summarized once, on the controller.
    assert run.stdout.str().strip() == ""


def test_plugin_should_aggregate_worker_reports_under_real_xdist(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_one():
            assert True


        def test_two():
            assert True


        def test_three():
            assert True
        """
    )

    run = pytester.runpytest_subprocess("-n", "2")

    # One line and nothing else. xdist writes its own status lines through the
    # terminal reporter, so anything leaking here means we let it keep a handle.
    assert len(run.stdout.str().strip().splitlines()) == 1
    payload = payload_of(run.stdout.str())
    assert payload["result"] == "passed"
    assert payload["summary"] == {"collected": 3, "passed": 3}


def test_plugin_should_describe_a_worker_failure_under_real_xdist(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True


        def test_bad():
            value = 401
            assert value == 200
        """
    )

    run = pytester.runpytest_subprocess("-n", "2")

    # The report crosses a process boundary to get here. What matters is that the
    # crash detail survives the trip, since it is the whole payload.
    payload = payload_of(run.stdout.str())
    assert payload["summary"] == {"collected": 2, "passed": 1, "failed": 1}
    assert payload["failures"] == [
        {
            "nodeid": "test_plugin_should_describe_a_worker_failure_under_real_xdist.py::test_bad",
            "phase": "call",
            "file": "test_plugin_should_describe_a_worker_failure_under_real_xdist.py",
            "line": 7,
            "type": "AssertionError",
            "message": "assert 401 == 200",
        }
    ]


def test_plugin_should_count_a_warning_once_under_real_xdist(pytester: pytest.Pytester, agent: None) -> None:
    # Every worker collects the whole suite, so a module-level warning is recorded
    # once per worker. pytest's own footer says 4 warnings serial and 5 under -n 2
    # for the same code; ours has to say the same thing in both.
    pytester.makepyfile(
        """
        import warnings

        warnings.warn("module level deprecation", DeprecationWarning)


        def test_one():
            assert True


        def test_two():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_subprocess("-n", "2").stdout.str())

    assert payload["summary"]["warnings"] == 1
    assert len(payload["warnings"]) == 1


def test_plugin_should_describe_a_collection_error_under_real_xdist(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        import totally_missing_module


        def test_never_runs():
            assert True
        """
    )

    run = pytester.runpytest_subprocess("-n", "2")

    payload = payload_of(run.stdout.str())
    assert payload["result"] == "failed"
    assert payload["summary"] == {"error": 1}
    assert payload["failures"][0]["type"] == "ModuleNotFoundError"
    assert payload["failures"][0]["phase"] == "collect"


# -- force hatch --


def test_plugin_should_compress_when_forced_without_an_agent(
    pytester: pytest.Pytester, no_agent: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYMMARY_FORCE", "1")
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    payload = payload_of(pytester.runpytest_inprocess().stdout.str())

    assert payload["result"] == "passed"
