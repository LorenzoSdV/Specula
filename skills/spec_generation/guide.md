# TLA+ Spec Generation for Web Applications

Model the requested behavior and contracts of a web application, using the Modeling Brief and its
Scenarios to guide verification. The app's handlers are modeled on the shared **`WebDB.tla`** module
(PostgreSQL semantics, validated against a real server), so the model never re-derives isolation-level
behavior. The logic within each step MUST faithfully follow the implementation's control flow, with
every logic block annotated to its source location.

## Input / Output

**Input**: `modeling-brief.md`, its companion `modeling-brief-*.md` documents, target-specific scope
guidance when provided, source code access, and the web toolkit (path in the prompt's web section;
`<toolkit>/tla/README.md` documents the WebDB API). The tracing stack is running: use it to see the
SQL the app really sends (below).

**Output** (written to `spec/`):

| Phase | Output | Description |
|-------|--------|-------------|
| 1 | `<App>.tla`, `<App>Invariants.tla`, `base.tla` | The model (`EXTENDS WebDB`), its invariants, and `base.tla` (`EXTENDS <App>`, Specula's expected name) |
| 2 | `MC.tla`, `MC.cfg`, `MC_hunt_*.cfg` | Model checking wrapper, convergence config, one hunt config per Scenario |
| 2.5 | `brief-coverage.md` | **Mandatory** self-audit mapping scope, Scenarios and properties to spec/MC artifacts |
| 3 | `Trace<App>.tla`, `Trace.tla`, `Trace.cfg.tmpl` | Trace validation spec and its config template |
| 4 | `instrumentation-spec.md` | Each action's HTTP route or SQL statement shape |
| — | `WebDB.tla`, `WebTrace.tla` | Copied **unchanged** from `<toolkit>/tla/` |

This `brief-coverage.md` self-audit is part of spec generation. It is separate from the pipeline's harness-generation phase, which is also sometimes called Phase 2.5.

Subagents may be used for independent source analysis, module construction, or review; integrate their results into one consistent suite. Each phase writes output to files; if context is compressed mid-session, re-read your own output files to recover.

**Never edit `WebDB.tla` or `WebTrace.tla`.** The orchestrator checks that they are byte-identical to
the toolkit's. If a library semantics question arises, model around it in the app model and say so.

---

## Step 0: See the SQL the app really sends

ORMs rarely send what the code suggests (`{ decrement: 1 }` is `SET stock = stock - $1`, an upsert may
be a SELECT then an INSERT, a nested write opens an implicit transaction). Before modeling a handler,
send one request of each kind through the stack (`base_url` in `stack/state.json`) and read the
statements in `pgproxy.ndjson` of the current recordings directory. Model what you see; cite the code
that produced it.

---

## Phase 1: The Model

**Goal**: The handlers in scope as steps on WebDB, with the state the invariants and guards read.

1. **Read the modeling handoff and scope guidance**: baseline contracts, Scenarios, the statements each entry point issues, the isolation level of each transaction
2. **Read source code as needed**: handlers, middleware, ORM calls, schema and migrations (constraints and unique indexes). Brief references are starting points, not a file allowlist
3. **Choose the abstraction**: the tables and columns invariants and guards read; everything else is abstracted away
4. **Write the steps**: one per SQL statement, in the code's order, each citing `file:line`
5. **Write invariants** in `<App>Invariants.tla`, each citing the contract evidence from the brief
6. **Write Init, `StepName` and Next**

**Read `references/base-spec-methodology.md`** for the model shape, WebDB calls, granularity rules and annotation style.

---

## Phase 2: MC Spec

**Goal**: Seeded initial state, the concrete requests actors may send, and hunt configs.

Concurrency between requests is normal operation, not a fault: it stays on in every config. Bound
the *faults* (client retries, crashes between statements, duplicate deliveries) and the workload
(number of actors, the `Inputs` each may send), never the interleavings.

**Generate these configs**:
- **`MC.cfg`** — convergence: all inputs, safety and structural invariants. Extension (scenario) invariants are listed but **commented out**.
- **`MC_hunt_<scenario>.cfg`** — one per Scenario: `Inputs` narrowed to that Scenario's requests, the target invariants enabled together with the other safety and structural invariants.
- **`MC_hunt_<scenario>_live.cfg`** — one per Liveness property in brief §5. **Read `references/liveness-pattern.md`** before writing one.

**Read `references/mc-spec-pattern.md`** for the template.

---

## Phase 2.5: Brief Coverage Self-Audit

**Goal**: Catch the easy-to-miss failure mode — invariants *defined* but never *enabled* in any hunt cfg, scenarios with no targeting hunt cfg, or findings no hunt cfg can reach.

This is a self-check, not a grading rubric. Glance over the requested scope and brief §2 / §5 / §6.1 while finalizing Phase 2, identify any obvious gaps, and either close them or note honestly why something is out of scope. The audit is scope-driven, not taxonomy-driven; omission from the brief does not remove a user-requested behavior from scope. Fill the audit by reading actual spec and cfg files, not from memory of what you intended.

When target-specific guidance is provided, preserve its intent while translating the Modeling Brief into the spec. Make it clear in `brief-coverage.md` how the user's priorities are represented or why another verification route is more appropriate, using whatever form and level of detail fit the target. Do not distort implementation evidence or modeling decisions merely to echo the guidance.

See `references/brief-coverage-checklist.md` for table sketches and a worked failure example.

---

## Phase 3: Trace Spec

**Goal**: Check recorded runs of the real app against the model. The tracing stack records every
request, statement result and committed row; the trace spec matches each recorded event to the step
its request is at and checks the outcome.

Trace validation is **existential**: concurrent requests leave their interleaving open, so a trace is
valid when *some* behavior of the model reproduces it. Use `INVARIANT TraceNotDone` in the template
(a violation means the trace matched); **never** add `PROPERTIES TraceMatched`.

**Read `references/trace-spec-pattern.md`** for the template.

---

## Phase 4: Instrumentation Spec

**Goal**: For each step, the HTTP route (request/response events) or the SQL statement shape that
identifies it. The harness phase turns this into the mapping file the trace builder reads. No code
instrumentation is needed.

**Read `references/instrumentation-spec-format.md`** for the format.

---

## Critical Rules

1. **Every extension has a source-grounded purpose.** Trace it to the requested scope, a system contract, or a Scenario.
2. **Model the implementation, including the SQL it really sends.** Not the API docs, not the ORM call's name.
3. **Follow the code's control flow faithfully.** Do not simplify, reorder, or merge logic that the code keeps separate.
4. **Annotate every logic block with source lines.** Every condition, branch, and state update must cite `file:line`. Not optional.
5. **Write to files early and often.** Insurance against context loss.
6. **One step per SQL statement.** A transaction does not make its statements atomic.
7. **Name steps `<Route>_<What>`** after the handler and the statement; the trace and mapping use the same names.
8. **Never edit `WebDB.tla` or `WebTrace.tla`.**
9. **Concurrency is never bounded away.** The MC layer bounds faults and the workload only.
10. **`brief-coverage.md` is a mandatory phase output.** Every Safety invariant in brief §5 must end up enabled in ≥1 hunt cfg, every Liveness property in its own `_live` cfg, every brief §2 scenario must have a targeting hunt cfg (or an explicit, written-out merger), every §6.1 finding must have a hunt cfg whose setup makes it reachable. Use the checklist as a self-check before writing the final audit doc — see Phase 2.5 and `references/brief-coverage-checklist.md`.

---

## Reference Files

- **`references/base-spec-methodology.md`** — Model shape on WebDB, steps per statement, granularity, annotation, invariants
- **`references/mc-spec-pattern.md`** — MC wrapper: seeded rows, `Inputs`, hunt configs
- **`references/liveness-pattern.md`** — Fairness, bounds, and cfg shape for Liveness properties
- **`references/brief-coverage-checklist.md`** — Self-audit mapping brief §2/§5/§6.1 → spec/MC artifacts (Phase 2.5)
- **`references/trace-spec-pattern.md`** — Trace spec template on WebTrace
- **`references/instrumentation-spec-format.md`** — Route and SQL shape per action

## Related Skills

- **code_analysis** — Previous phase: produces the Modeling Brief and the stack config
- **harness-generation** — Next phase (2.5): mapping file, workloads, traces
- **validation-workflow** — Phase 3: validates the spec using traces and model checking
