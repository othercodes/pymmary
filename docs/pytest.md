# pytest adapter

Replaces pytest's human report with one line of JSON when a coding agent is running it. Outside an agent, output is byte-identical to plain pytest.

For agent detection, the envelope shared by every adapter and the two environment variables, see the [README](../README.md).

## Installation

```bash
pip install pymmary[pytest]
```

Nothing to wire up. The adapter registers itself through pytest's `pytest11` entry point, so installing it as a dev dependency is the whole setup.

## Requirements

- Python 3.10+
- **pytest 9.1+**, a hard floor rather than a preference

The adapter unregisters pytest's terminal reporter to own the output. Before 9.1, pytest built assertion explanations through `config.get_terminal_writer()`, which asserts that reporter is still registered. With it gone, that assert fires while pytest is formatting a failed assertion and its empty `AssertionError` replaces the explanation:

```json
{"type":"AssertionError","message":"AssertionError","line":1139}
```

instead of `assert 401 == 200` at line 14, the one payload this library exists to produce. Verified broken on 8.4.2 and 9.0.0, correct from 9.1.0. A CI job pins the declared floor so the claim stays true.

## Output

```bash
pytest
```

A green run, whatever its size:

```json
{"tool":"pytest","result":"passed","exit_code":0,"duration":0.32,"summary":{"collected":1002,"passed":1002}}
```

A failing one, with only what the agent needs to act:

```json
{"tool":"pytest","result":"failed","exit_code":1,"duration":0.32,"summary":{"collected":1002,"passed":999,"failed":2,"error":1},"failures":[{"nodeid":"tests/test_api.py::TestAuth::test_login[user-2]","phase":"call","file":"tests/test_api.py","line":42,"type":"AssertionError","message":"assert 401 == 200"}]}
```

Every payload is a single line. That is the actual output, not a formatting choice. Expanded, so the fields are readable:

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

### Keys the pytest adapter adds

On top of the four envelope keys every adapter emits:

| Key | Meaning |
|---|---|
| `exit_code` | `pytest.ExitCode`, which already distinguishes `OK`, `TESTS_FAILED`, `INTERRUPTED`, `INTERNAL_ERROR`, `USAGE_ERROR` and `NO_TESTS_COLLECTED` |
| `failures` | One record per failure, capped by `PYMMARY_MAX_FAILURES`. Absent entirely on a green run |
| `failures_omitted` | How many failures the cap left out. Absent when it left out none |

And inside a failure record:

| Field | Why it is there |
|---|---|
| `nodeid` | Pasteable straight back into the CLI. The whole point, see below |
| `phase` | `setup` / `call` / `teardown` / `collect`. A setup failure is a broken fixture, a collect failure means the file never imported, neither is broken test logic |
| `file`, `line` | Where to look |
| `type`, `message` | The exception and its explanation, ANSI stripped |

`summary` uses pytest's own outcome vocabulary: `collected`, `passed`, `failed`, `error`, `skipped`, `xfailed`, `xpassed`. `error` is kept distinct from `failed` because an error means the test never ran, and counting it as a failed assertion is a lie. An `xpassed` means something got fixed and nobody updated the marker.

### nodeid is the point

```bash
pytest "tests/test_api.py::TestAuth::test_login[user-2]"
```

The agent gets its reproduction command for free, parametrize ids included, with no parsing of a traceback.

### A broken run is never reported green

The verdict follows pytest's exit code, never our own tally. A collection error, an internal error, a usage error or a suite that collected nothing all leave `failures` empty while the run is very much not a success:

```json
{"tool":"pytest","result":"failed","exit_code":2,"duration":0.008,"summary":{"error":1},"failures":[{"nodeid":"test_broken.py","phase":"collect","file":"test_broken.py","line":1,"type":"ModuleNotFoundError","message":"No module named 'requests'"}]}
```

## Under pytest-xdist

`-n` changes nothing about what you read. The workers ship their reports to the controller, which prints the same single line, with failure detail intact.

| | Behaviour |
|---|---|
| `duration` | Wall clock, the time actually spent waiting, so it falls as workers are added. The sum of worker durations would rise with parallelism while you wait less |
| `failures` order | Whatever order the workers finished in. `summary` is the part that compares cleanly between runs |

Exactly one process emits. Workers stay silent, their stdout is captured by the controller and read by nobody.

## How much it saves

Tokens, not bytes: tokens are what an agent pays for. Counted with `tiktoken` (`o200k_base`) on real pytest output:

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

The floor is **1.6×**, on a suite with many failures but no cap hit. Failure bodies are the one thing that does not compress much. The ceiling is a big green suite, where output stays flat at ~31 tokens no matter how many tests ran.

Two things worth knowing before quoting these numbers. JSON tokenizes worse than prose, all those quotes and braces, so the saving in tokens is consistently lower than the saving in bytes: the 1000-test green run is 14.6× smaller in bytes but only 7.2× cheaper in tokens. And these are OpenAI encodings, since Anthropic publishes no tokenizer for current Claude models, so treat them as a close proxy rather than an exact figure.
