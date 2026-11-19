# Trace Harness Generation (Phase 2.5): Boundary Tracing for Web Apps

There is **no source instrumentation and no trace module to write**. The toolkit's tracing stack wraps
the app's own Docker Compose stack and records every HTTP request and response, every SQL statement
(with results, errors, timing and the request it belongs to) and every committed row change. This
phase maps those recordings to model actions, drives workloads through the app's public API, and
records model-level traces. The orchestrator has already started the stack and self-tested it; the
toolkit and stack paths, and the commands to use, are in the prompt's "Web toolkit and tracing
stack" section.

## Outputs

| File | Role |
|---|---|
| `harness/mapping.toml` | Routes and SQL statement shapes → model action names; modeled tables and columns |
| `harness/workloads.py` | Scenarios for the toolkit's workload runner |
| `harness/run.sh` | One command: ensure the stack, run the workloads, build `traces/` |
| `harness/rebuild_traces.sh` | Rebuild `traces/` from the saved recordings after a mapping change |
| `harness/INSTRUMENTATION.md` | What is captured, where the recordings are, how to change the mapping |
| `traces/*.ndjson`, `traces/windows.json` | One trace per workload run, and each run's recording window |

When you finish, the orchestrator checks deterministically that every trace was recorded by a
self-tested stack running the current `stack.toml`, that rebuilding every trace from the recordings
with `harness/mapping.toml` reproduces it byte for byte, and that the coverage gate passes. A trace
written or edited by hand fails that check.

## Step 1: Learn the real statements

For each route in `spec/instrumentation-spec.md`, send one request through the stack (`base_url` in
`stack/state.json`; use seeded accounts from the brief) and read what was recorded in the current
recordings directory (`out_dir` in `stack/state.json`): `inbound.ndjson` (requests, responses) and
`pgproxy.ndjson` (statements, with `trace_id` tying each to its request). ORMs often send SQL that
differs from what the code suggests. If a statement the model does not have shows up, the model is
missing a step: record it in `INSTRUMENTATION.md` for Phase 3, do not hide it.

## Step 2: Mapping file

Turn the instrumentation spec into `harness/mapping.toml`:

```toml
[tables.Seat]                         # modeled tables: key column and modeled columns with types
key = "id"
columns = { capacity = "int", held = "int" }

[[route]]                             # one actor per request; <action>_Begin / <action>_End events
action = "Book"
match = '^POST /seats/(?P<seatId>\d+)/book$'     # named groups become arguments
body = { note = "text" }                          # JSON body fields to record
headers = { authorization = "bearer", "idempotency-key" = "text" }
response = { id = "int" }                         # response body fields to record

[[sql]]                               # matched in order against the statement text, comments removed
action = "Begin"
kind = "begin"                        # begin | commit | rollback | select | write | insert
match = '^BEGIN'

[[sql]]
action = "Book_ReadSeat"
kind = "select"
table = "Seat"
route = "Book"                        # optional: only for requests of this route
match = 'FROM "public"\."Seat" WHERE \("public"\."Seat"\."id" = '
limit1 = true                         # LIMIT 1: the result is any one matching row

[[sql]]
action = "Book_LockSeat"
kind = "write"                        # UPDATE / DELETE / SELECT ... FOR UPDATE -> _start, _finish
table = "Seat"
match = '^SELECT "held" FROM "Seat" WHERE "id" = \$1 FOR UPDATE'
rows = false                          # the result lacks the key column: check the row count only

[coverage.exempt]                     # optional: actions the public API cannot reach, with a reason
Rollback = "no handler issues ROLLBACK; errors close the transaction"
```

Action names must be exactly the model's `StepName` values. The trace builder **fails** on any
request or statement the mapping does not cover. That is deliberate: fix the mapping, or record the
missing step for the model.

## Step 3: Workloads

`harness/workloads.py` defines `SCENARIOS`, a dict from scenario name to a function taking the
runner's `Client`:

```python
def sequential(c):
    c.get("/seats/1")
    c.post("/seats/1/book", token="tok-a")
    c.post("/seats/1/book", token="tok-a")              # error path: already booked
    c.post("/seats/9/book", token="tok-a")              # error path: unknown seat

SCENARIOS = {
    "sequential": sequential,
    # Two buyers of the last seat, started together so their statements overlap.
    "two_buyers": lambda c: c.together(lambda: c.post("/seats/1/book", token="tok-a"),
                                       lambda: c.post("/seats/1/book", token="tok-b")),
}
```

`Client` has `get/post/put/patch/delete(path, json=..., headers=..., token=...)` (token becomes a
bearer `authorization` header) returning `(status, body, headers)`. `c.together(*calls)` starts its
calls at the same moment (a barrier); a scenario that uses it is recorded as **concurrent**.

Write:

- a **sequential** scenario covering every route and every error path in scope;
- a **concurrent** scenario for each Scenario in the brief, with requests that contend for the same
  rows (same product, same seat, same idempotency key).

Use only the app's public API and the seeded accounts. Run them:

    python3 <toolkit>/workload/runner.py run --stack <stack config> --runs-dir <runs dir> \
        --mapping harness/mapping.toml --workloads harness/workloads.py --traces traces/ --repeat 3

The runner resets the database with the app's own seed command before every run, records each run's
window in `traces/windows.json`, and builds `traces/<scenario>-<n>.ndjson`. Concurrent runs
interleave differently each time; repeat them.

## Step 4: Coverage gate

    python3 <toolkit>/tracecheck/coverage.py --mapping harness/mapping.toml traces/

It must report every mapped action seen in at least one trace, and, for every concurrent scenario,
at least one trace with **overlapping actors** (one request issued a statement while another was
between two of its own). Otherwise only sequential behavior gets validated and trace validation
cannot catch modeling errors in interleavings. If a scenario never overlaps, make its requests
contend harder (more of them, the same rows) or repeat it more.

## Step 5: Check the traces against the model once

    python3 <toolkit>/tracecheck/check.py --spec spec/Trace.tla --template spec/Trace.cfg.tmpl traces/

This is Phase 3's job, but run it once: a rejection here usually means a mapping mistake (a wrong
action name, a regular expression matching the wrong statement, a missing body field), which is
yours to fix. Leave genuine model disagreements to Phase 3 and note them in `INSTRUMENTATION.md`.

## Step 6: run.sh, rebuild_traces.sh, INSTRUMENTATION.md

- `run.sh`: `wkstack.py ensure` with the prompt's options, then the runner command from Step 3.
- `rebuild_traces.sh`: `python3 <toolkit>/workload/runner.py rebuild --mapping harness/mapping.toml --traces traces/`.
  It rebuilds every recorded window, so a mapping change needs no new recording.
- `INSTRUMENTATION.md`: where the recordings are, the workloads, anything the model is missing, and
  how to change what is captured (nearly always: the mapping file).

Then run the orchestrator's gate yourself (command in the prompt) and fix what it reports.

## When boundary tracing is not enough

Only in-process state that never reaches the database (an in-memory cache, an in-process lock) needs
code instrumentation. Record it in `INSTRUMENTATION.md` as a gap for the model; do not patch the app.

## Critical Rules

1. **Never write or edit traces by hand.** Every trace comes from the runner; the gate rebuilds them.
2. **Never edit the app's code or its compose file.** Change the mapping or the workloads.
3. **Public API only**, with the app's own seeded accounts. No direct database writes.
4. **The mapping names the model's steps exactly.** An unmappable statement is a model gap, not something to filter out.
5. **Wrap every command in `timeout`.** A hung request must not consume the phase.
