from __future__ import annotations

import json

import pytest

# No `-p` flag anywhere below: the pytest11 entry point auto-loads the adapter,
# so these tests exercise the exact path a real installation takes.
_SIGNALS = ("CLAUDECODE", "CURSOR_TRACE_ID", "TERM_PROGRAM", "GEMINI_CLI_SESSION", "PYMMARY_FORCE")


@pytest.fixture
def no_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every detection signal — the developer machine may well be an agent."""
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


# -- xdist: strict no-op --


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

    assert "{" not in run.stdout.str()
    run.stdout.fnmatch_lines(["*1 passed*"])


def test_plugin_should_stay_silent_when_the_run_is_distributed(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makeconftest(
        """
        def pytest_configure(config):
            config.option.dist = "load"
        """
    )
    pytester.makepyfile(
        """
        def test_ok():
            assert True
        """
    )

    run = pytester.runpytest_inprocess()

    assert "{" not in run.stdout.str()


def test_plugin_should_stay_silent_under_real_xdist(pytester: pytest.Pytester, agent: None) -> None:
    pytester.makepyfile(
        """
        def test_one():
            assert True


        def test_two():
            assert True
        """
    )

    run = pytester.runpytest_subprocess("-n", "2")

    assert "{" not in run.stdout.str()
    run.stdout.fnmatch_lines(["*2 passed*"])


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
