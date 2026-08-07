# pymmary

[![Build Status](https://github.com/othercodes/pymmary/actions/workflows/test.yml/badge.svg)](https://github.com/othercodes/pymmary/actions/workflows/test.yml)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=othercodes_pymmary&metric=coverage)](https://sonarcloud.io/summary/new_code?id=othercodes_pymmary)
[![PyPI](https://img.shields.io/pypi/v/pymmary.svg)](https://pypi.org/project/pymmary/)

Agent-optimized output compressor for Python tooling.

> **Status: alpha.** The pytest adapter is the only one so far.

## Why

Python tools write for humans: progress indicators, a full traceback per problem, colour codes, a summary table. When an AI agent runs one of those tools, it pays for all of it. A green run of a thousand tests tells the agent one thing ("everything passed") and charges thousands of tokens to say it.

Pymmary detects that a coding agent is running the tool and replaces that output with compact JSON. Outside an agent, nothing changes: no agent detected, no compression, byte-identical output for humans.

It is a decision of the *project*, not of the agent's environment. Add it as a dev dependency and any agent that clones the repo and runs your tools benefits, with no per-machine setup.

## Adapters

Each tool gets its own adapter, its own extra, and its own page. The payload speaks that tool's vocabulary rather than a normalized one, so the details live with the adapter:

| Tool | Install | Docs |
|---|---|---|
| pytest | `pymmary[pytest]` | [pytest adapter](https://github.com/othercodes/pymmary/blob/master/docs/pytest.md) |

Planned: mypy, then unittest.

## Features

- Automatic agent detection via environment variables, no configuration
- Strict no-op fallback: no agent, no change to output
- One shared envelope across adapters, with a payload in each tool's own vocabulary
- Zero runtime dependencies in the core; each adapter ships behind its own extra
- Hooks into the host tool's native extension points, no global monkey-patching

## Requirements

- Python 3.10+

Adapters add their own, listed on each adapter page.

## Installation

```bash
pip install pymmary
```

With an adapter:

```bash
pip install pymmary[pytest]
```

Nothing to wire up after that. Adapters register themselves through the host tool's own plugin mechanism, so installing as a dev dependency is the whole setup.

## The envelope

Every adapter emits these four keys, so an agent recognizes any pymmary output at a glance:

| Key | Meaning |
|---|---|
| `tool` | Which tool produced this |
| `result` | `"passed"` / `"failed"`, the one-word verdict |
| `duration` | Seconds, float, rounded to 3 decimals |
| `summary` | Counts, in the host tool's own outcome vocabulary |

Adapters add top-level keys where their tool has more to say. The pytest adapter adds `exit_code` and `failures`, for example, and a green suite of 1002 tests comes out as one line:

```json
{"tool":"pytest","result":"passed","exit_code":0,"duration":0.32,"summary":{"collected":1002,"passed":1002}}
```

Two rules hold across every adapter:

- **`result` follows the tool's exit code, never our own tally.** A run that broke before it could report anything is never called a pass.
- **`summary` uses the tool's own words.** pytest counts passed and xfailed, mypy counts errors and notes. Normalizing them would throw away the thing that makes the payload useful.

## Agent detection

| Agent | Signal |
|---|---|
| Claude Code | `CLAUDECODE` set to any non-empty value |
| Cursor | `CURSOR_TRACE_ID` set to any non-empty value |
| Devin | `TERM_PROGRAM=Devin` exactly |
| Gemini CLI | any variable starting with `GEMINI_CLI_` |

Anything else, plain shells and generic CI included, falls through and leaves output untouched. No TTY checks, no parent-process inspection, no network.

## Configuration

Two environment variables, no config file and no CLI flags:

| Variable | Effect |
|---|---|
| `PYMMARY_FORCE=1` | Compress even when no agent is detected, useful to see what an agent sees |
| `PYMMARY_MAX_FAILURES=N` | How many problems to spell out. Default 20; `0` keeps every one of them |

The cap is about diminishing returns, not size: an agent facing 400 failures fixes a handful and runs again, so the rest cost context and buy nothing. `summary` always counts the whole run, and whatever was left out is declared in `failures_omitted`.

## How much it saves

Tokens, not bytes, since tokens are what an agent pays for. On pytest output the saving runs from **1.6× to 28×** depending on the shape of the run: best on large green suites, worst on suites with many failures, since failure bodies barely compress. The full table and the method are on the [pytest adapter page](https://github.com/othercodes/pymmary/blob/master/docs/pytest.md#how-much-it-saves).

## Related

Companion to [pyssertive](https://github.com/othercodes/pyssertive) (assert phase) and [pyrrange](https://github.com/othercodes/pyrrange) (arrange phase). Pymmary covers the report phase, for AI consumers.

Inspired by [laravel/pao](https://github.com/laravel/pao), the PHP original.

## License

MIT
