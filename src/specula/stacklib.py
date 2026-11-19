"""The target's tracing stack: deterministic lifecycle and gates (no agent involved).

Every target is a web application whose stack (its own Docker Compose services plus the webkit
recorders) is described by ``<work>/stack/stack.toml``, written in Phase 1. The orchestrator owns
the stack's lifecycle:

* ``ensure``   before Phases 2, 2.5, 3 and 4: reuse the recorded stack when it runs this exact
               config and passes the signal self-test; otherwise (re)start and self-test it. A
               failing self-test stops the pipeline before any agent records traces from it.
* ``down``     after a successful run (recordings are kept under ``<work>/stack/runs/``).

and the deterministic gates the agents cannot talk their way past:

* ``library_problems``  the shared TLA+ modules in ``spec/`` are byte-identical to the toolkit's;
* ``trace_problems``    after Phase 2.5: every trace was recorded by a self-tested stack running
                        the current config, rebuilding it from the recordings with the current
                        mapping reproduces it byte for byte, and the coverage gate passes.

The toolkit (``webkit/``) is found through ``$SPECULA_WEBKIT``, else next to the Specula checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SPECULA_ROOT = Path(__file__).resolve().parents[2]
WEBKIT_ENV = "SPECULA_WEBKIT"
LIBRARY_MODULES = ("WebDB.tla", "WebTrace.tla")
HARNESS_FILES = ("mapping.toml", "workloads.py", "run.sh", "rebuild_traces.sh", "INSTRUMENTATION.md")


class StackError(RuntimeError):
    """The stack could not be brought to a running, self-tested state."""


def webkit_root() -> Path | None:
    raw = os.environ.get(WEBKIT_ENV)
    candidates = [Path(raw)] if raw else [SPECULA_ROOT.parent / "webkit"]
    for c in candidates:
        if (c / "stack" / "wkstack.py").is_file():
            return c.resolve()
    return None


def require_webkit() -> Path:
    root = webkit_root()
    if root is None:
        raise StackError(
            f"web toolkit not found: set ${WEBKIT_ENV} (or --webkit) to the webkit/ directory "
            "containing stack/wkstack.py"
        )
    return root


def stack_dir(work: Path) -> Path:
    return work / "stack"


def config_path(work: Path) -> Path:
    return stack_dir(work) / "stack.toml"


def runs_dir(work: Path) -> Path:
    return stack_dir(work) / "runs"


def state_path(work: Path) -> Path:
    return stack_dir(work) / "state.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wkstack(webkit: Path, command: str, work: Path, *, capture: bool = True) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(webkit / "stack" / "wkstack.py"), command,
            "--config", str(config_path(work)), "--runs-dir", str(runs_dir(work))]
    env = {**os.environ, "COMPOSE_MENU": "false"}
    if capture:
        return subprocess.run(argv, capture_output=True, text=True, env=env)
    return subprocess.run(argv, text=True, env=env)


def status(work: Path, webkit: Path | None = None) -> dict[str, Any]:
    webkit = webkit or require_webkit()
    if not config_path(work).is_file():
        raise StackError(f"missing stack config {config_path(work)} (a Phase 1 deliverable)")
    p = _wkstack(webkit, "status", work)
    if p.returncode != 0:
        raise StackError(f"wkstack status failed:\n{p.stdout}{p.stderr}")
    return json.loads(p.stdout)


def ensure(work: Path, webkit: Path | None = None) -> dict[str, Any]:
    """Leave a running, self-tested stack for this target; record it in ``stack/state.json``."""
    webkit = webkit or require_webkit()
    if not config_path(work).is_file():
        raise StackError(f"missing stack config {config_path(work)} (a Phase 1 deliverable)")
    runs_dir(work).mkdir(parents=True, exist_ok=True)
    p = _wkstack(webkit, "ensure", work, capture=False)
    st = status(work, webkit)
    selftest = st.get("selftest") or {}
    if p.returncode != 0 or not st.get("running") or not selftest.get("ok"):
        failed = [c["name"] for c in selftest.get("checks", []) if not c.get("ok")]
        raise StackError(
            f"stack for {work} is not running a self-tested config"
            + (f"; failed checks: {', '.join(failed)}" if failed else "")
            + f" (wkstack ensure exited {p.returncode}). Fix {config_path(work)} and resume."
        )
    record = {k: st.get(k) for k in ("run_id", "out_dir", "base_url", "control_url", "config_sha256", "started_at")}
    record["selftest_at"] = selftest.get("at")
    state_path(work).write_text(json.dumps(record, indent=2) + "\n")
    return record


def down(work: Path, webkit: Path | None = None) -> None:
    webkit = webkit or require_webkit()
    if config_path(work).is_file():
        _wkstack(webkit, "down", work, capture=False)


def library_problems(work: Path, webkit: Path | None = None) -> list[str]:
    """The shared modules in spec/ must be the toolkit's, unchanged."""
    webkit = webkit or require_webkit()
    problems = []
    for module in LIBRARY_MODULES:
        ours, theirs = work / "spec" / module, webkit / "tla" / module
        if not ours.is_file():
            problems.append(f"spec/{module} missing (copy it unchanged from {theirs})")
        elif ours.read_bytes() != theirs.read_bytes():
            problems.append(f"spec/{module} differs from {theirs}: shared library modules are read-only")
    return problems


def _windows(traces: Path) -> dict[str, Any]:
    f = traces / "windows.json"
    try:
        return json.loads(f.read_text()) if f.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def trace_problems(work: Path, webkit: Path | None = None) -> list[str]:
    """Phase 2.5's deterministic gate: traces are real, reproducible from recordings, and cover the model."""
    webkit = webkit or require_webkit()
    harness, traces = work / "harness", work / "traces"
    problems = [f"harness/{f} missing" for f in HARNESS_FILES if not (harness / f).is_file()]
    if not config_path(work).is_file():
        problems.append("stack/stack.toml missing")
    files = sorted(traces.glob("*.ndjson")) if traces.is_dir() else []
    if not files:
        problems.append("no traces/*.ndjson")
    if problems:
        return problems

    sha = _sha256(config_path(work))
    root = runs_dir(work).resolve()
    windows = _windows(traces)
    for f in files:
        w = windows.get(f.stem)
        if not isinstance(w, dict) or "run_dir" not in w:
            problems.append(f"traces/{f.name}: no window in traces/windows.json (record it with webkit/workload/runner.py)")
            continue
        run = Path(w["run_dir"]).resolve()
        if root not in run.parents:
            problems.append(f"traces/{f.name}: recorded outside this target's stack ({run})")
            continue
        try:
            st = json.loads((run / "selftest.json").read_text())
        except (OSError, json.JSONDecodeError):
            problems.append(f"traces/{f.name}: its stack run {run.name} has no self-test result")
            continue
        if not st.get("ok"):
            problems.append(f"traces/{f.name}: its stack run {run.name} failed the self-test")
        elif st.get("config_sha256") != sha:
            problems.append(f"traces/{f.name}: recorded with an older stack.toml (stack run {run.name})")
    if problems:
        return problems

    with tempfile.TemporaryDirectory(prefix="specula-rebuild-") as tmp:
        p = subprocess.run(
            [sys.executable, str(webkit / "workload" / "runner.py"), "rebuild",
             "--mapping", str(harness / "mapping.toml"), "--traces", str(traces), "--out", tmp],
            capture_output=True, text=True,
        )
        if p.returncode != 0:
            problems.append("rebuilding traces from the recordings failed:\n" + (p.stdout + p.stderr).strip())
        else:
            for f in files:
                rebuilt = Path(tmp) / f.name
                if not rebuilt.is_file() or rebuilt.read_bytes() != f.read_bytes():
                    problems.append(f"traces/{f.name}: differs from its rebuild from the recordings with harness/mapping.toml")

    p = subprocess.run(
        [sys.executable, str(webkit / "tracecheck" / "coverage.py"), "--mapping", str(harness / "mapping.toml"),
         str(traces), "--json", str(harness / "coverage.json")],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        problems.append("coverage gate failed:\n" + (p.stdout + p.stderr).strip())
    return problems


def prompt_section(work: Path, webkit: Path | None = None) -> str:
    """Paths and commands every phase's agent needs; static per target (cache-friendly)."""
    webkit = webkit or webkit_root()
    if webkit is None:
        return ""
    cfg, runs = config_path(work), runs_dir(work)
    stack = f"--config {cfg} --runs-dir {runs}"
    return f"""
## Web toolkit and tracing stack

- **Toolkit**: `{webkit}` (read its `README.md`; shared TLA+ modules in `{webkit}/tla/`).
- **Stack config**: `{cfg}`. Recordings: `{runs}/<run-id>/`.
- The orchestrator starts the stack and self-tests it before each phase that needs it, and records
  it in `{state_path(work)}` (base URL, proxy control URL, current recordings directory).
- Commands (always with these options):
  - `python3 {webkit}/stack/wkstack.py status {stack}`: running?, URLs, recordings dir, last self-test
  - `python3 {webkit}/stack/wkstack.py ensure {stack}`: start or reuse, then self-test
  - `python3 {webkit}/stack/wkstack.py reset {stack}`: reseed the database with the app's own command
- `WebDB.tla` and `WebTrace.tla` are shared, read-only library modules: copy them into `spec/`
  unchanged and never edit them (the orchestrator checks).
"""


def main(argv: list[str]) -> int:
    """``python3 -m specula.stacklib ensure|down|status|gate WORK_DIR`` (manual use and debugging)."""
    if len(argv) != 2 or argv[0] not in {"ensure", "down", "status", "gate"}:
        print("usage: stacklib.py ensure|down|status|gate WORK_DIR", file=sys.stderr)
        return 2
    command, work = argv[0], Path(argv[1]).resolve()
    try:
        if command == "ensure":
            print(json.dumps(ensure(work), indent=2))
        elif command == "down":
            down(work)
        elif command == "status":
            print(json.dumps(status(work), indent=2))
        else:
            problems = library_problems(work) + trace_problems(work)
            for problem in problems:
                print(f"  FAIL  {problem}")
            print("gate: " + ("FAIL" if problems else "PASS"))
            return 1 if problems else 0
    except StackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "StackError", "WEBKIT_ENV", "config_path", "down", "ensure", "library_problems", "prompt_section",
    "require_webkit", "runs_dir", "stack_dir", "state_path", "status", "trace_problems", "webkit_root",
]
