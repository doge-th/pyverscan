# pyverscan 🔎

[![CI](https://img.shields.io/github/actions/workflow/status/doge-th/pyverscan/ci.yml?branch=main&label=CI)](https://github.com/doge-th/pyverscan/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)

**The oldest Python your code can run on — answered by your code, not your
guesses.**

What should `requires-python` say? Is that `match` statement safe to ship?
Will `int | None` blow up on the 3.9 box? Point pyverscan at any folder and it
walks the AST, maps every construct to the version it needs, and prints the
floor. Zero dependencies, one command.

```
$ pyverscan .

pyverscan v0.1.0  ·  .

Summary
  0 finding(s) · confirmed floor 3.8 · 7 file(s) scanned

  No version-specific features found — nothing above the scan floor.
```

*(that's pyverscan scanning its own repository — it stays 3.8-compatible on
purpose, and its own CI fails if that ever drifts)*

A repo that does use newer features gets the full picture:

```
$ pyverscan ./myproject

pyverscan v0.1.0  ·  ./myproject

Summary
  3 finding(s) · confirmed floor 3.11 · 24 file(s) scanned

Does it run on?
  python 3.8   ✗  needs 3.11
  python 3.9   ✗  needs 3.11
  python 3.10  ✗  needs 3.11
  python 3.11  ✓  runs
  python 3.12  ✓  runs

Findings
  needs 3.11 (2)
    myproject/sync.py:41  tomllib (TOML parsing)
    myproject/model.py:8  typing.Self
  needs 3.10 (1)
    myproject/model.py:15  structural pattern matching (match/case)
```

## Why

`requires-python` is usually written from memory, then disproven by a user on
an older interpreter. There are three ways to get it wrong:

- **Syntax** — `match`, `except*`, `type` aliases, PEP 695 generics: these
  don't even *parse* on older interpreters.
- **Runtime names** — `tomllib`, `typing.Self`, `asyncio.TaskGroup`,
  `functools.cache`, `str.removeprefix()`: they parse everywhere and fail at
  import or call time.
- **Annotations** — `int | None` and `list[str]` work early *only* when
  nothing evaluates them, so `from __future__ import annotations` changes the
  answer.

pyverscan reports all three separately. Syntax nodes, imports and
module-anchored attributes are **confirmed**; a method call on an unknown
receiver (`name.removeprefix()`) is **possible** — it could be your own
method. The floor line, the run-on table and the CI gate all count only
confirmed findings, and possible ones are shown next to them, never silently
mixed in.

## Install

```bash
pip install pyverscan
```

Python 3.9–3.13. No dependencies; the scanner is the standard library's `ast`.

## Use

```bash
pyverscan .                  # human report for the current project
pyverscan src --json         # machine-readable
pyverscan . --max 3.9        # exit 1 if the floor is above 3.9 (CI gate)
pyverscan . --exclude vendor # skip a directory by name (repeatable)
```

The gate counts confirmed findings only: a heuristic finding above `--max`
is printed, not failed on. Put the gate in CI next to your tests and
`requires-python` stops drifting:

```yaml
- run: pyverscan . --max 3.9
```

## What it sees

| Needs | Confirmed (AST-proven) | Possible (receiver unknown) |
| ----- | ---------------------- | --------------------------- |
| 3.9   | walrus `:=` · positional-only `/` · builtin generics in annotations (`list[str]`) · `functools.cache` · `graphlib` · `zoneinfo` · `importlib.metadata` | `str.removeprefix()` · `str.removesuffix()` |
| 3.10  | `match` · PEP 604 unions in annotations · `dataclass(slots=…, kw_only=…)` · `typing.TypeGuard/ParamSpec/Concatenate/TypeAlias` · `itertools.pairwise` | `int.bit_count()` · `aiter()` · `anext()` |
| 3.11  | `except*` · `tomllib` · `typing.Self` · `asyncio.TaskGroup/timeout` · `contextlib.chdir` · `enum.StrEnum` · `datetime.UTC` · `typing.Required/NotRequired/TypeVarTuple/Unpack` | `ExceptionGroup` |
| 3.12  | `type X = …` · PEP 695 type parameters · `typing.override` · `itertools.batched` · `pathlib.Path.walk()` | — |

With `from __future__ import annotations` in a module, its annotation
findings are reported as possible instead of confirmed — deferred evaluation
really does make them importable earlier, so claiming them as floors would
be a lie.

Files this interpreter cannot parse (a 3.9 process reading `match` syntax)
are listed separately, not silently skipped: the floor might be higher than
anything the tool could prove. Source files that are not UTF-8 are read
through their PEP 263 `coding:` declaration; a file no codec can decode is
reported the same way, never a traceback.

The scanner is validated against real corpora, not just fixtures: on the
CPython 3.9 standard library (680 files) it reports floor 3.9 with zero
false-positive heuristics — exactly what a codebase that must run on 3.9
should produce.

## Honest limits

- Heuristic findings count possible receivers of common names; a codebase
  with its own `removeprefix()` will see one. They are marked `(possible)`
  and never fail the gate.
- Import shadowing (`import tomllib` that is not the stdlib) is not
  resolved.
- The scan floor is 3.8: features older than that are not reasoned about.

## Related tools

Also from the same author, all zero-dependency Python CLIs:

- [toktree](https://github.com/doge-th/toktree) — `du` for your LLM context window
- [githotspot](https://github.com/doge-th/githotspot) — churn × complexity hotspots in any git repo
- [todomold](https://github.com/doge-th/todomold) — which TODOs have rotted, ranked by blame age
- [awakehours](https://github.com/doge-th/awakehours) — timezone meeting grid for distributed teams

## License

[MIT](LICENSE)
