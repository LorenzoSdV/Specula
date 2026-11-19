#!/usr/bin/env python3
"""Test stub of webkit/tracecheck/coverage.py: always passes."""

import argparse
import json
import sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--mapping", type=Path)
p.add_argument("traces", type=Path)
p.add_argument("--json", type=Path)
a = p.parse_args()
if a.json:
    a.json.write_text(json.dumps({"ok": True, "actions": {"Stub": 1}, "traces": 1}))
print("coverage gate: PASS (stub)")
sys.exit(0)
