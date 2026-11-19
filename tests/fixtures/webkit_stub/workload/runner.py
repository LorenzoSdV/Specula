#!/usr/bin/env python3
"""Test stub of webkit/workload/runner.py: `rebuild --out DIR` copies the traces."""

import argparse
import shutil
import sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("command")
p.add_argument("--mapping", type=Path)
p.add_argument("--traces", type=Path, required=True)
p.add_argument("--out", type=Path)
a, _ = p.parse_known_args()
out = a.out or a.traces
out.mkdir(parents=True, exist_ok=True)
for f in a.traces.glob("*.ndjson"):
    if out.resolve() != a.traces.resolve():
        shutil.copyfile(f, out / f.name)
sys.exit(0)
