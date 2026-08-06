# pymmary

[![Build Status](https://github.com/othercodes/pymmary/actions/workflows/test.yml/badge.svg)](https://github.com/othercodes/pymmary/actions/workflows/test.yml)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=othercodes_pymmary&metric=coverage)](https://sonarcloud.io/summary/new_code?id=othercodes_pymmary)
[![PyPI](https://img.shields.io/pypi/v/pymmary.svg)](https://pypi.org/project/pymmary/)

Agent-optimized output compressor for Python tooling.

> **Status: alpha.** The pytest adapter is the only one so far.

## Why

When an AI agent runs `pytest`, it pays for output written for humans — progress dots, a full traceback per failure, colour codes, a summary table. A green run of a thousand tests tells the agent one thing ("everything passed") and charges thousands of tokens to say it.

Pymmary detects that a coding agent is running the tool and replaces that output with compact JSON. Outside an agent, nothing changes: no agent detected, no compression, byte-identical output for humans.

It is a decision of the *project*, not of the agent's environment. Add it as a dev dependency and any agent that clones the repo and runs `pytest` benefits, with no per-machine setup.

## Features

- Automatic agent detection via environment variables — no configuration
- Strict no-op fallback: no agent, no change to output
- Compact JSON keyed by pytest `nodeid`, so failures are pasteable straight back into the CLI
- Zero runtime dependencies in the core; each adapter ships behind its own extra
- Hooks into the host tool's native extension points — no global monkey-patching

## Requirements

- Python 3.10+
- pytest 9.1+ (optional, for `pymmary[pytest]`)

## Installation

```bash
pip install pymmary
```

With the pytest adapter:

```bash
pip install pymmary[pytest]
```

## Usage

Nothing to wire up. Install it as a dev dependency and run your tools as usual — when a supported agent is detected, output is compressed.

```bash
pytest
```

```json
{"tool":"pytest","result":"passed","exit_code":0,"duration":0.32,"summary":{"collected":1002,"passed":1002}}
```

On failure, only what the agent needs to act:

```json
{
  "tool": "pytest",
  "result": "failed",
  "exit_code": 1,
  "duration": 0.32,
  "summary": { "collected": 1002, "passed": 999, "failed": 2, "error": 1 },
  "failures": [
    {
      "nodeid": "tests/test_api.py::TestAuth::test_login[user-2]",
      "phase": "call",
      "file": "tests/test_api.py",
      "line": 42,
      "type": "AssertionError",
      "message": "assert 401 == 200"
    }
  ]
}
```

A run that fails to collect is never reported as a pass — the verdict follows pytest's exit code, not our own tally:

```json
{"tool":"pytest","result":"failed","exit_code":2,"duration":0.008,"summary":{"error":1},"failures":[{"nodeid":"test_broken.py","phase":"collect","file":"test_broken.py","line":1,"type":"ModuleNotFoundError","message":"No module named 'requests'"}]}
```

## Configuration

Two environment variables, no config file and no CLI flags:

| Variable | Effect |
|---|---|
| `PYMMARY_FORCE=1` | Compress even when no agent is detected — useful to see what an agent sees |
| `PYMMARY_MAX_FAILURES=N` | How many failures to spell out. Default 20; `0` keeps every one of them |

The cap is about diminishing returns, not size: an agent facing 400 failures fixes a handful and runs again, so the rest cost context and buy nothing. `summary` always counts the whole run, and whatever was left out is declared in `failures_omitted`.

## How much it actually saves

Tokens, not bytes — tokens are what an agent pays for. Counted with `tiktoken` (`o200k_base`) on real pytest output:

| Scenario | pytest | pymmary | Saving |
|---|---:|---:|---:|
| 1 test, green | 136 | 31 | 4.4× |
| 100 tests, green | 146 | 31 | 4.7× |
| 1000 tests, green | 238 | 33 | 7.2× |
| 3 tests, 1 failure | 218 | 82 | 2.7× |
| 5 failures | 457 | 246 | 1.9× |
| 400 tests, 20 failures | 1,445 | 900 | 1.6× |
| 400 failures | 24,868 | 884 | 28.1× |

`cl100k_base` agrees within 3%.

The floor is **1.6×**, on a suite with many failures but no cap hit — failure bodies are the one thing that does not compress much. The ceiling is a big green suite, where pymmary's output stays flat at ~31 tokens no matter how many tests ran.

Note that JSON tokenizes worse than prose — all those quotes and braces — so the saving in tokens is consistently lower than the saving in bytes. The 1000-test green run is 14.6× smaller in bytes but only 7.2× cheaper in tokens. These are OpenAI encodings; Anthropic does not publish a tokenizer for current Claude models, so treat this as a close proxy rather than an exact figure.

## Limitations

- **pytest-xdist**: pymmary stands down completely under `-n`, leaving normal pytest output. The controller never runs the tests itself, so a compressed summary would count none of them. Aggregating the worker streams is planned.
- **pytest 9.1 is a hard floor.** The adapter unregisters pytest's terminal reporter to own the output. Before 9.1, pytest built assertion explanations through `config.get_terminal_writer()`, which asserts that reporter is still registered — so on older versions every `assert` failure degrades to a bare `AssertionError` pointing into pytest's internals. That is the one payload this library exists to produce, so the floor is enforced rather than worked around.

## Related

Companion to [pyssertive](https://github.com/othercodes/pyssertive) (assert phase) and [pyrrange](https://github.com/othercodes/pyrrange) (arrange phase). Pymmary covers the report phase, for AI consumers.

Inspired by [laravel/pao](https://github.com/laravel/pao) — the PHP original. Pymmary keeps its envelope recognizable but speaks pytest's own vocabulary rather than PHPUnit's.

## License

MIT
