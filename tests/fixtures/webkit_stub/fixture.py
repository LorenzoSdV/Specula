#!/usr/bin/env python3
"""Write the web outputs a fake agent must produce for a phase:  fixture.py PHASE WORK_DIR

code_analysis       stack/stack.toml
spec_generation     spec/Trace.cfg.tmpl and the library modules
harness_generation  the harness files, windows.json for every trace, a self-tested stub stack run
spec_validation*    the library modules, if a seeded workspace lacks them
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

STUB = Path(__file__).resolve().parent


def stack(work: Path) -> Path:
    cfg = work / "stack" / "stack.toml"
    if not cfg.is_file():
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('[app]\nproject = "fixture"\n')
    return cfg


def main() -> int:
    phase, work = sys.argv[1], Path(sys.argv[2])
    if phase in ("code_analysis", "spec_generation", "harness_generation"):
        stack(work)
    if phase.startswith("spec_validation") and (work / "spec").is_dir():
        # A workspace seeded as if Phase 2 ran also has the library modules Phase 2 copies.
        for module in ("WebDB.tla", "WebTrace.tla"):
            if not (work / "spec" / module).is_file():
                shutil.copyfile(STUB / "tla" / module, work / "spec" / module)
    if phase in ("spec_generation", "harness_generation"):
        spec = work / "spec"
        spec.mkdir(parents=True, exist_ok=True)
        for module in ("WebDB.tla", "WebTrace.tla"):
            shutil.copyfile(STUB / "tla" / module, spec / module)
        tmpl = spec / "Trace.cfg.tmpl"
        if not tmpl.is_file():
            tmpl.write_text("INVARIANT TraceNotDone\n")
    if phase == "harness_generation":
        harness, traces = work / "harness", work / "traces"
        harness.mkdir(parents=True, exist_ok=True)
        traces.mkdir(parents=True, exist_ok=True)
        for name in ("mapping.toml", "workloads.py", "run.sh", "rebuild_traces.sh", "INSTRUMENTATION.md"):
            if not (harness / name).is_file():
                (harness / name).write_text("# fixture\n")
        if not any(traces.glob("*.ndjson")):
            (traces / "fixture.ndjson").write_text('{"event":"fixture"}\n')
        sha = hashlib.sha256(stack(work).read_bytes()).hexdigest()
        run = work / "stack" / "runs" / "fixture-run"
        run.mkdir(parents=True, exist_ok=True)
        (run / "selftest.json").write_text(json.dumps({"ok": True, "config_sha256": sha}))
        windows = {f.stem: {"run_dir": str(run.resolve()), "since": 0, "until": 1, "scenario": f.stem,
                            "concurrent": False} for f in traces.glob("*.ndjson")}
        (traces / "windows.json").write_text(json.dumps(windows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
