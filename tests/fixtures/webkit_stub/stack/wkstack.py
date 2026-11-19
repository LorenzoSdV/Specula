#!/usr/bin/env python3
"""Test stub of webkit/stack/wkstack.py: same commands and state files, no Docker."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["up", "down", "selftest", "status", "ensure", "reset", "overlay"])
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--runs-dir", type=Path, default=Path("runs"))
    p.add_argument("--run-id")
    a = p.parse_args()
    sha = hashlib.sha256(a.config.read_bytes()).hexdigest()
    a.runs_dir.mkdir(parents=True, exist_ok=True)
    state_file = a.runs_dir / ".current-stub.json"
    if a.command in ("up", "ensure", "selftest"):
        st = json.loads(state_file.read_text()) if state_file.exists() else {}
        if st.get("config_sha256") != sha:
            run = a.runs_dir / (a.run_id or f"stub-{time.time_ns()}")
            run.mkdir(parents=True, exist_ok=True)
            st = {"run_id": run.name, "out_dir": str(run.resolve()), "base_url": "http://localhost:8080",
                  "control_url": "http://localhost:6433", "config_sha256": sha, "started_at": "stub"}
            state_file.write_text(json.dumps(st))
        Path(st["out_dir"], "selftest.json").write_text(json.dumps(
            {"ok": True, "at": "stub", "at_ns": time.time_ns(), "run_id": st["run_id"], "config_sha256": sha,
             "checks": [{"name": "stub", "ok": True}]}))
        print(f"stub stack {st['run_id']}: self-test PASS")
    elif a.command == "status":
        st = json.loads(state_file.read_text()) if state_file.exists() else {}
        selftest = Path(st["out_dir"], "selftest.json") if st else None
        print(json.dumps({"running": bool(st), "config_sha256": sha, **st,
                          "selftest": json.loads(selftest.read_text()) if selftest and selftest.exists() else None}))
    elif a.command == "down":
        state_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
