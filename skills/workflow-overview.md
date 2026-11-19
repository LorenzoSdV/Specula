# Specula Workflow: Finding Bugs in Web Applications

## What This Is

A pipeline that finds interleaving bugs in web applications (oversell, double booking, double charge,
duplicate side effects, lost updates, stuck states) by modeling the app's request handlers in TLA+,
checking the model against recordings of the real app, model checking it, and reproducing every
violation against the running app. The guarantee is bounded model checking of a model that
conforms to recorded behavior: bug finding, not proof.

A web app is a concurrent system even when no line of its code mentions threads: many requests run
handlers at the same time against one database, and **a transaction does not make a handler's
statements atomic**. The app's handlers are modeled on the shared `WebDB.tla` module (PostgreSQL
semantics, validated against a real server), one step per SQL statement.

## The Phases

| Phase | Skill | Agent? | Output |
|---|---|---|---|
| 1 Code Analysis | `code_analysis` | yes | `modeling-brief.md`, `defect-ledger.json`, `stack/stack.toml` |
| Stack | — | **no** (orchestrator) | the app running under the tracing stack, self-tested; `stack/state.json` |
| 2 Spec Generation | `spec_generation` | yes | model on WebDB, `MC.tla` + cfgs, trace spec, `instrumentation-spec.md` |
| 2.5 Harness | `harness-generation` | yes | `harness/mapping.toml`, `harness/workloads.py`, `traces/` (deterministic gate after) |
| 3 Validation & Hunting | `validation-workflow` | yes | converged model, `spec/bug-report.md`, `spec/findings.json` |
| 4a Confirmation | `bug-confirmation` | yes | `confirmed-bugs.md`, `repro/test_bug*` |
| 4b Classification | `bug-classification` | yes | `bug-severity.md`, findings summary |

## The tracing stack (no agent)

Phase 1 writes the stack config. From then on the orchestrator owns the stack: before every phase that
needs it, it reuses or (re)starts the app's own Docker Compose services plus the toolkit's recorders,
and runs a self-test of every signal source. A failing self-test stops the pipeline. The recorders:

- an inbound HTTP proxy (every request and response, with a trace id per request);
- a PostgreSQL wire-protocol proxy (every statement with its results, error code and timing, tied to
  its request; it can also hold and release statements to replay a counterexample's interleaving);
- logical decoding (the rows each transaction committed);
- an OpenTelemetry collector (ties SQL to requests through SQL comments).

No app code changes are needed.

## Deterministic gates

The orchestrator checks, without trusting any agent:

- after Phases 2, 2.5 and 3: `spec/WebDB.tla` and `spec/WebTrace.tla` are the toolkit's, unchanged;
- after Phase 2.5: every trace was recorded by a self-tested stack running the current config,
  rebuilding it from the recordings with the current mapping reproduces it byte for byte, and the
  coverage gate passes (every mapped action seen; overlapping actors in every concurrent scenario).

## Phase 3 in one paragraph

Trace validation (the model reproduces every recorded run, existentially: some interleaving matches)
alternates with model checking of `MC.cfg` (the model reaches no illegal state) until both pass in
the same round with no change. Trace failures are triaged stack → mapping → model. Then each
Scenario's hunt config runs (BFS, then simulation if BFS did not finish); each violation is rendered
as request lanes by the timeline tool.

## Phase 4 in one paragraph

Each finding is investigated, then reproduced against the running app: concurrent requests (Level 0),
then a proxy-scheduled replay of the counterexample (Level 1), which is deterministic. The replay's
own trace must match the model and violate the same invariant (the same-bug check). A replay that the
database refuses (a statement blocked on a row lock the model did not have) becomes a cited
`SPEC_REPAIR`; a violated property the app never promises becomes an `INVARIANT` repair. Repairs go
back to Phase 3 and the finding is re-confirmed.

## Directory Structure (per target)

```
.specula-output/
├── modeling-brief.md, defect-ledger.json, analysis-report.md   # Phase 1
├── stack/
│   ├── stack.toml               # Phase 1: how to run the app under the tracing stack
│   ├── state.json               # orchestrator: current stack run, URLs, last self-test
│   └── runs/<run-id>/           # recordings: inbound, pgproxy, cdc, otel spans, selftest.json
├── spec/
│   ├── <App>.tla, <App>Invariants.tla, base.tla      # Phase 2
│   ├── MC.tla, MC.cfg, MC_hunt_*.cfg                  # Phase 2
│   ├── Trace<App>.tla, Trace.tla, Trace.cfg.tmpl      # Phase 2
│   ├── WebDB.tla, WebTrace.tla                        # toolkit copies, read-only
│   ├── instrumentation-spec.md                        # Phase 2
│   ├── changelog.md, bug-report.md, findings.json     # Phase 3
│   └── output/                                        # TLC output
├── harness/
│   ├── mapping.toml, workloads.py                     # Phase 2.5
│   ├── run.sh, rebuild_traces.sh, INSTRUMENTATION.md
│   └── coverage.json                                  # coverage gate report
├── traces/*.ndjson, traces/windows.json               # Phase 2.5
├── confirmed-bugs.md, bug-severity.md, summary.md     # Phase 4
└── repro/test_bug*                                    # Phase 4 reproductions
```

## Available Skills

| Skill | Phase | Location |
|-------|-------|----------|
| `byom` | 2–4 | `skills/byom/` |
| `code_analysis` | 1 | `skills/code_analysis/` |
| `spec_generation` | 2 | `skills/spec_generation/` |
| `harness-generation` | 2.5 | `skills/harness-generation/` |
| `validation-workflow` | 3 (orchestration) | `skills/validation-workflow/` |
| `tla-trace-workflow` | 3A | `skills/tla-trace-workflow/` |
| `tla-checking-workflow` | 3B | `skills/tla-checking-workflow/` |
| `bug-confirmation` | 4a | `skills/bug-confirmation/` |
| `bug-classification` | 4b | `skills/bug-classification/` |

## Toolkit commands (paths in each prompt's web section)

| Command | Purpose |
|---|---|
| `stack/wkstack.py ensure / status / reset / down` | Stack lifecycle, self-test, database reset |
| `workload/runner.py run / rebuild` | Record traces from workloads; rebuild them after a mapping change |
| `tracecheck/coverage.py` | Coverage gate |
| `tracecheck/check.py [--explain] [--violates INV]` | Trace validation; divergence report; same-bug check |
| `timeline/timeline.py` | Counterexample as request lanes; draft schedule |
| `repro/schedule_from_tlc.py`, `repro/scheduler.py` | Counterexample → proxy schedule; deterministic replay |

## MCP Tools

| Tool | Purpose |
|------|---------|
| `validate_spec_syntax` | Quick TLA+ syntax check |
| `get_tlc_summary` | TLC model checking result overview |
| `get_tlc_state` | Inspect specific states in error trace |
| `compare_tlc_states` | Diff states or track variable changes |
| `run_trace_replay` | Replay a counterexample with a custom ALIAS |
| `run_vav_analysis` | Variable assignment validation |
