# Trace Validation Workflow (Web Apps)

Check recorded runs of the real app against the TLA+ model. Diagnose rejected traces, then fix the
mapping or the model.

## Input / Output

**Input**: `spec/Trace.tla` + `spec/Trace.cfg.tmpl`, the model, `traces/*.ndjson` (recorded by the
harness phase), `harness/mapping.toml`, and the web toolkit (path in the prompt's web section).

**Output**: every trace ACCEPTED, or a fixed mapping / model.

**By default, execute autonomously.** Only pause for user confirmation if the prompt explicitly requests human-in-the-loop.

---

## Core Concepts

- **Traces are partial orders.** Events of one request are in program order. Events of different
  requests are ordered only when their time intervals do not overlap (`WebTrace.tla`).
- **Validation is existential.** A trace is valid when *some* behavior of the model matches every
  event, in an order the partial order allows, with every recorded outcome (rows, error codes, row
  counts, committed rows, response statuses). The config uses `INVARIANT TraceNotDone`: TLC reporting
  it violated means the trace matched. **Never** use `PROPERTIES TraceMatched` (it demands that every
  behavior consume the trace, which no concurrent trace satisfies) or the MCP trace-validation tools
  built on it.
- **A rejection has a precise location.** The checker finds the largest number of events any
  behavior matches and lists the events that were ready next but matched by no behavior.

---

## Phase 1: Validate

    python3 <toolkit>/tracecheck/check.py --spec spec/Trace.tla --template spec/Trace.cfg.tmpl \
        --jobs 4 traces/

`ACCEPTED`, `REJECTED` (with "matches at most N/M events; could not match next: #j actor action"),
or `ERROR` (TLC output: a parse or semantic error in the spec). Run all traces after every change.

---

## Phase 2: Diagnose a rejection

Rerun the rejected trace with `--explain`:

    python3 <toolkit>/tracecheck/check.py --spec spec/Trace.tla --template spec/Trace.cfg.tmpl \
        --explain traces/<name>.ndjson

It prints, for each stuck event, what was recorded (kind, rows, error code, row count, status,
committed writes) and the model's full state after the matched prefix (`pc`, `res`, `ver`, locks,
locals). Compare them:

1. Read the stuck event's `actor` and its `pc` in the printed state. Does `StepName` give the
   event's `action` at that `pc`? If not, the actor took a path the model does not have (a branch, a
   statement the handler issues that the model lacks, an early error response).
2. If the step matches, compare the recorded outcome with what the step would produce from this
   state: rows read (snapshot, locks), error code (unique violation, serialization failure), row
   count of a write, the rows a COMMIT committed, the response status.
3. Look at the raw recording when needed: `windows.json` gives the trace's recording directory and
   window; `pgproxy.ndjson` has the statement text and results, `inbound.ndjson` the request and
   response bodies.

---

## Phase 3: Classify and fix

Check suspects from the most generic to the most specific:

| Class | Signs | Fix |
|---|---|---|
| **Stack** | events missing or attributed to the wrong request, a COMMIT without committed rows | Rerun `wkstack.py ensure` (it self-tests); report a toolkit issue. Never edit the toolkit. |
| **Mapping** | a statement mapped to the wrong action, a regex matching two statement shapes, a body field or header not recorded, `rows = false` missing on a result without the key | Fix `harness/mapping.toml`, run `harness/rebuild_traces.sh`, revalidate |
| **Model: inconsistency** | the model's control flow, guard, statement or isolation level differs from the code | Fix the model from the source code (cite `file:line`) |
| **Model: abstraction gap** | the model is right at its abstraction level but a recorded detail is outside it (an extra column, a statement on an unmodeled table) | Bridge it only if it matters for the invariants; otherwise abstract it consistently in the mapping and the model, and say why |

Rules for model fixes:

- Fix the **model** (`<App>.tla`), not the trace comparison in `Trace<App>.tla`. Loosening a
  comparison makes validation pass while the model stays wrong. Change the comparison only when it
  checks something the recording cannot capture, and document why.
- Read the source code and find the evidence before changing anything.
- If a fix changes how a statement is modeled (a plain SELECT that is really `SELECT ... FOR UPDATE`,
  a step split into `_start`/`_finish`, a new step), update the statement's rule in
  `harness/mapping.toml` to match, then rebuild the traces with `harness/rebuild_traces.sh` before
  revalidating. The rebuild uses every recorded window.
- **Never edit `WebDB.tla` or `WebTrace.tla`.** If PostgreSQL's real behavior seems to differ from
  WebDB, model around it in the app model with a comment citing the evidence, and record it in the
  changelog as a library issue.
- Never edit, delete or cherry-pick traces to make validation pass. A trace that cannot be
  reproduced is evidence.

---

## Critical Rules

1. **Always validate every trace after a change.** A fix for one trace can break another.
2. **Diagnose with `--explain` before changing anything.**
3. **Stack, then mapping, then model.** Each fix is logged in `changelog.md` with its class.
4. **Fix the model, not the comparison logic.**
5. **Never use `PROPERTIES TraceMatched` or the TraceMatched-based MCP tools.**
6. **Never use `ScheduleWakeup` / `CronCreate` to wait.** This pipeline runs the agent non-interactively; any cross-turn timer is silently dropped. Block within the turn.
7. **Wrap every command in `timeout N`** (the checker runs TLC; `timeout 60m` per invocation is generous). **For any backgrounded long-running job, use `scripts/infra/wait_for_pid.sh --pid-file ... --timeout ...`**.

## Related Skills

- **spec-generation** — produces the model and the trace spec
- **harness-generation** — produces the mapping, workloads and traces
- **validation-workflow** — the loop that alternates trace validation and model checking
