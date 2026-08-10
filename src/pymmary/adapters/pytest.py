from __future__ import annotations

import os
import re
import time
import warnings
from collections import Counter
from pathlib import Path

import pytest

from pymmary.detector import is_agent_environment
from pymmary.emitter import max_failures_from, render
from pymmary.schema import Failure, Result, WarningInfo

_FAILED_OUTCOMES = ("failed", "error")

PLUGIN_NAME = "pymmary-collector"


def _is_worker(config: pytest.Config) -> bool:
    """True inside a pytest-xdist worker process.

    A worker runs a slice of the suite and ships its reports to the controller,
    where the run comes back together. Summarizing there would print one JSON line
    per process, each counting a fraction of the run and none of them true.
    """
    return hasattr(config, "workerinput")


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
        # Keyed rather than appended: pytest fires the warning hook once per
        # occurrence, and under xdist once per worker on top of that.
        self.warnings: dict[WarningInfo, None] = {}
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

    def pytest_warning_recorded(self, warning_message: warnings.WarningMessage) -> None:
        self.warnings[
            WarningInfo(
                category=warning_message.category.__name__,
                file=_relative_to(warning_message.filename, self.config.rootpath),
                line=int(warning_message.lineno),
                message=str(warning_message.message),
            )
        ] = None

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        result = _build_result(
            reports=self.reports,
            collect_errors=self.collect_errors,
            warnings=tuple(self.warnings),
            collected=session.testscollected,
            exit_code=int(exitstatus),
            duration=time.perf_counter() - self.started,
        )
        print(render(result, max_failures=max_failures_from(os.environ)))


def pytest_plugin_registered(plugin: object, plugin_name: str, manager: pytest.PytestPluginManager) -> None:
    """Drop the terminal reporter the instant it appears.

    Own the terminal outright instead of muting the default reporter piecemeal:
    unregistering is pytest's supported way to drop a plugin, and it leaves no
    header, no progress line and no summary to leak around our JSON.

    Here rather than in pytest_configure because that is what silences xdist too.
    xdist looks the reporter up in its own configure hook and keeps a direct
    reference, so a reporter still alive by then goes on writing status lines
    around our output no matter how thoroughly we unregister it afterwards. Killed
    on registration, there is nothing for xdist to find, and every one of its
    `if self.terminal:` guards closes on its own.
    """
    if plugin_name == "terminalreporter" and is_agent_environment(os.environ) is not None:
        manager.unregister(plugin)


def pytest_configure(config: pytest.Config) -> None:
    if is_agent_environment(os.environ) is None or _is_worker(config):
        return

    config.pluginmanager.register(Collector(config), PLUGIN_NAME)


def _relative_to(path: str, root: Path) -> str:
    """Match how failures are reported. A dependency's file has no useful relative form."""
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def _build_result(
    reports: list[pytest.TestReport],
    collect_errors: list[pytest.CollectReport],
    warnings: tuple[WarningInfo, ...],
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

    summary = {"collected": collected, **counts, "warnings": len(warnings)}

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
        warnings=warnings,
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


def _origin_of(report: pytest.TestReport) -> tuple[str, int]:
    """Where pytest itself says the failure happened, file and line as one pair.

    Taking them from separate sources is how they end up contradicting each other.
    ``reprcrash`` points at the frame that raised, which for ``self.assertEqual``
    or any wrapped assertion is inside somebody else's file, while
    ``report.location`` names the test file. Combined they describe a coordinate
    that does not exist: ``test_auth.py:918`` in a file of twelve lines.

    The last entry of the rendered traceback is the one pytest prints as
    ``path:lineno:``, already relative and already 1-based, and it is a pair. It is
    also the frame the ecosystem points us at: assertion helpers that set
    ``__tracebackhide__``, pyssertive among them, drop out of the traceback so the
    last entry lands back in the test.
    """
    traceback = getattr(report.longrepr, "reprtraceback", None)
    entries = getattr(traceback, "reprentries", ())
    location = getattr(entries[-1], "reprfileloc", None) if entries else None
    if location is not None:
        return str(location.path), int(location.lineno)

    # No traceback to read: `--tb=no` and `--tb=native` both get here. Falling back
    # to the crash keeps the pair honest, at the cost of an absolute path.
    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None:
        return str(crash.path), int(crash.lineno)
    return str(report.location[0]), 0


def _failure_of(report: pytest.TestReport) -> Failure:
    crash = getattr(report.longrepr, "reprcrash", None)
    raw = crash.message if crash is not None else str(report.longrepr)
    type_name, message = _split_crash_message(raw)
    file, line = _origin_of(report)

    return Failure(
        nodeid=report.nodeid,
        phase=str(report.when),
        file=file,
        line=line,
        type=type_name,
        message=message,
    )
