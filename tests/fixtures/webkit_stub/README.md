# Stub web toolkit for Specula's own tests

Specula's tests drive the pipeline with fake agents and no web app. `tests/conftest.py` points
`SPECULA_WEBKIT` here, so the real stack step and deterministic gates run against stubs:

- `stack/wkstack.py`: `ensure` records a self-tested stack run without Docker; `status`, `down`,
  `reset`, `selftest` behave like the real tool's interface.
- `tla/WebDB.tla`, `tla/WebTrace.tla`: placeholder library modules for the library gate.
- `workload/runner.py rebuild`: copies the traces (so the rebuild comparison holds).
- `tracecheck/coverage.py`: reports a passing gate.
- `fixture.py PHASE WORK_DIR`: writes the web outputs a fake agent must produce for PHASE.

Never used outside tests.
