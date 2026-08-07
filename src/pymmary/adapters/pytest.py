from __future__ import annotations

import os
import re
import time
from collections import Counter

import pytest

from pymmary.detector import is_agent_environment
from pymmary.emitter import max_failures_from, render
from pymmary.schema import Failure, Result

_FAILED_OUTCOMES = ("failed", "error")

PLUGIN_NAME = "pymmary-collector"


def _is_distributed(config: pytest.Config) -> bool:
    """True when pytest-xdist is doing the running.

    Workers each build their own report stream and the controller never runs a test
    itself, so our per-item collection sees nothing there and would emit a green
    summary with zero tests in it. A wrong summary is worse than an uncompressed
    one, so we stand down entirely.

    ponytail: no-op under xdist; aggregate the worker streams if anyone asks.
    """
    if hasattr(config, "workerinput"):
        return True
    return bool(config.getoption("dist", "no") != "no")


class Collector:
    """Accumulates one run and prints its summary when the session ends.

    An object rather than the module-level hooks the rest of pymmary uses, because
    ``pytest_runtest_logreport`` is handed a report and nothing else: no item, no
    config, so no stash to write into. Keeping config on the instance is how
    pytest's own terminal reporter solves the same problem.
    """

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.reports: list[pytest.TestReport] = []
        self.collect_errors: list[pytest.CollectReport] = []
        self.started = 0.0

    def pytest_sessionstart(self) -> None:
        # Timed from here rather than from __init__ so `duration` means what the
        # footer pytest prints means, which is also measured from this hook.
        self.started = time.perf_counter()

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.reports.append(report)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.collect_errors.append(report)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        result = _build_result(
            reports=self.reports,
            collect_errors=self.collect_errors,
            collected=session.testscollected,
            exit_code=int(exitstatus),
            duration=time.perf_counter() - self.started,
        )
        print(render(result, max_failures=max_failures_from(os.environ)))


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    # trylast: the built-in reporter registers itself in its own pytest_configure,
    # so running first would find nothing to unregister.
    if is_agent_environment(os.environ) is None or _is_distributed(config):
        return

    config.pluginmanager.register(Collector(config), PLUGIN_NAME)

    # Own the terminal outright instead of muting the default reporter piecemeal:
    # unregistering is pytest's supported way to drop a plugin, and it leaves no
    # header, no progress line and no summary to leak around our JSON.
    reporter = config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        config.pluginmanager.unregister(reporter)


def _build_result(
    reports: list[pytest.TestReport],
    collect_errors: list[pytest.CollectReport],
    collected: int,
    exit_code: int,
    duration: float,
) -> Result:
    counts: Counter[str] = Counter()
    failures: list[Failure] = []

    # Collection errors first: a file that would not import is the reason the tests
    # below it never ran, so it is the first thing worth reading.
    for collect_error in collect_errors:
        counts["error"] += 1
        failures.append(_collect_failure_of(collect_error))

    for report in reports:
        outcome = _outcome_of(report)
        if outcome is None:
            continue
        counts[outcome] += 1
        if outcome in _FAILED_OUTCOMES:
            failures.append(_failure_of(report))

    summary = {"collected": collected, **counts}

    return Result(
        tool="pytest",
        # The exit code decides, never our own tally. Collection errors, internal
        # errors and an empty run all leave `failures` empty while the run is very
        # much not a success. Calling those "passed" is the worst lie we can tell.
        result="passed" if exit_code == 0 else "failed",
        duration=duration,
        summary=summary,
        exit_code=exit_code,
        failures=tuple(failures),
    )


def _outcome_of(report: pytest.TestReport) -> str | None:
    """Map a phase report to pytest's own outcome vocabulary.

    ``None`` means "nothing to count": a passing setup or teardown is not a result,
    it is the absence of a problem.
    """
    if hasattr(report, "wasxfail"):
        return "xpassed" if report.passed else "xfailed"
    if report.skipped:
        return "skipped"
    if report.passed:
        return "passed" if report.when == "call" else None
    # A failure outside the call phase never ran the test body. Pytest calls that
    # an error, and the distinction matters to whoever reads the output.
    return "failed" if report.when == "call" else "error"


def _split_crash_message(raw: str) -> tuple[str, str]:
    """Separate the exception type from its message.

    A raised exception crashes as ``"ValueError: nope"``. A bare ``assert`` does not:
    pytest's assertion rewriting reports ``"assert 401 == 200"`` with no type prefix,
    and that is always an AssertionError.
    """
    head, separator, tail = raw.partition(": ")
    if separator and all(part.isidentifier() for part in head.split(".")):
        return head, tail
    return "AssertionError", raw


_ERROR_LINE = re.compile(r"^E\s+(.*)$", re.MULTILINE)
_TRACEBACK_LINE = re.compile(r"^.*?:(\d+): in ", re.MULTILINE)


def _collect_failure_of(report: pytest.CollectReport) -> Failure:
    """Describe a file that never made it to the starting line.

    A CollectReport carries no `reprcrash`, no `location` and no `when`: nothing
    ran, so there is no phase to speak of. What it does carry is the whole rendered
    traceback as text, so we pull the exception off its `E` line and the line number
    off the last frame. `nodeid` is the file itself, which is what the agent needs
    in order to go and fix the import.
    """
    text = str(report.longrepr)

    errors = _ERROR_LINE.findall(text)
    type_name, message = _split_crash_message(errors[-1] if errors else text)

    frames = _TRACEBACK_LINE.findall(text)
    line = int(frames[-1]) if frames else 0

    return Failure(
        nodeid=report.nodeid,
        phase="collect",
        file=report.nodeid,
        line=line,
        type=type_name,
        message=message,
    )


def _failure_of(report: pytest.TestReport) -> Failure:
    crash = getattr(report.longrepr, "reprcrash", None)
    raw = crash.message if crash is not None else str(report.longrepr)
    type_name, message = _split_crash_message(raw)

    return Failure(
        nodeid=report.nodeid,
        phase=str(report.when),
        file=str(report.location[0]),
        line=crash.lineno if crash is not None else 0,
        type=type_name,
        message=message,
    )
