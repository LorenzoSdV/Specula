# Code Analysis for Formal Verification of Web Applications

Investigate a web application to find bugs. Some can be confirmed directly (a missing authorization
check, a crash on bad input). The most critical ones are **interleaving bugs**: concurrent requests,
retries, jobs and webhooks racing over shared state, which need TLA+ model checking to find. The
**Modeling Brief** captures findings and plans how to verify them: every suspected defect goes into
its defect ledger, and the mechanisms worth model checking become Scenarios. This phase also writes
the **stack config** that lets every later phase run and trace the app.

When a candidate defect appears, follow [Persistent Findings](../bug-confirmation/references/persistent-findings.md) for a lightweight history match before deeper analysis or reproduction.

## Input / Output

**Input**: Repository path + GitHub URL (optional) + target-specific guidance (optional). The web
toolkit and the stack paths are in the prompt's "Web toolkit and tracing stack" section.

**Output**:
- `modeling-brief.md` (handoff to Spec Generation) and `defect-ledger.json`
- `analysis-report.md` (optional audit trail)
- `stack/stack.toml`: how to run the app under the tracing stack (Phase 5)

**The user drives each phase.** You provide methodology and execute on their direction.

---

## Step 0: Characterize the Application

Read `references/web-analysis.md` first: why web apps are concurrent systems, what to record, the
patterns to hunt and the invariant families. Record in the brief:

- framework, ORM, database and their versions (from lockfiles), with evidence;
- the **isolation level** of every transaction (the database default and each per-transaction
  override), cited;
- **stores and channels**: databases, caches, queues and job runners, webhooks in and out, external
  APIs, real-time channels;
- the **deployment profile** that matters for concurrency (replicas, cron placement, queue
  concurrency, pool size, provider retry policies); unknown is fine, say so.

Then read `references/deep-analysis.md` for the shared methodology.

---

## Phase 1: Reconnaissance

**Goal**: Build a structural map: entry points (routes, GraphQL resolvers, server actions, jobs,
cron, webhook handlers, admin pages), the entities they read and write, transaction boundaries, and
the scale of the code involved.

Build the **entry-point × entity write matrix** (see `references/web-analysis.md`). It is the main
source of Scenario candidates in a codebase without bug history.

---

## Phase 2: Bug Archaeology

**Goal**: Map historical bugs to identify error-prone areas and recurring patterns. This phase requires **thorough** coverage — the quality of the entire analysis depends on the evidence gathered here.

### Steps

1. **Git history mining** by keyword (the general list in `references/bug-archaeology.md` plus the web keywords in `references/web-analysis.md`). Analyze **all** significant bug-fix commits, not just a sample.
2. **Issue/PR verification** — read full discussions, not just titles. Use `gh issue list` with multiple keyword searches and label filters to maximize coverage.
3. **Scenario grouping** — group by shared **mechanism**, not by file.

### Depth Requirements

- **Git commits**: Analyze all bug-fix commits touching core files. Report the total count.
- **GitHub issues**: Read the full discussion thread (including all comments) for every issue you plan to reference. Read as many as the requested scope requires; there is no fixed count. Report: total issues collected, total deeply read, total confirmed, total excluded as false positive.
- **Open PRs**: Review all open PRs with bug-fix intent — they often contain fixes waiting for review and reveal known-but-unfixed problems.
- **Parallelization**: Use **multiple Task subagents in parallel** for issue verification. Do NOT read issues sequentially — this wastes time.

**Read `references/bug-archaeology.md`** for detailed methodology.

---

## Phase 3: Deep Analysis

**Goal**: Find new issues through systematic code reading, guided by Phase 2 and the write matrix:
check-then-act across statements, read-modify-write in the app, uniqueness enforced only in code,
side effects before commit, non-idempotent handlers under retries, state machines that disagree
across handlers, the same check enforced differently on different entry points.

### Parallelization Strategy

Deep Analysis is the most time-consuming phase. **Use parallel Task subagents aggressively**:

- Divide work by entity or by entry-point family, including the callers, middleware and ORM calls needed to understand each path
- Each subagent reads its assigned files completely and applies the patterns in `references/web-analysis.md`
- After all subagents return, cross-reference findings in the main context

Choose the number of parallel subagents by the size of the scope; there is no fixed number.

### Verification

Every finding MUST be verified: re-read exact code lines, check for compensating mechanisms (database constraints, middleware, framework defaults), trace the execution path from the entry point, check if it's an acknowledged design decision.

**Read `references/deep-analysis.md`** for the full methodology.

---

## Phase 4: Modeling Brief

**Goal**: Produce an actionable handoff for the requested modeling scope and for Bug Confirmation — describe the baseline behavior and component interactions, organize findings into Scenarios, propose spec extensions, explain exclusions, and record every suspected defect, with its verification method, in the defect ledger. Priorities set the order, not a cap on the number of Scenarios.

Every invariant a Scenario proposes needs **contract evidence**: a quote from the app's README or
docs, an API contract, a database constraint, a test, or code enforcing it on another path. An
invariant family is not evidence.

When target-specific guidance is provided, treat its priorities and scope as required investigative intent. Make their handling visible in the Modeling Brief through the relevant Scenarios, findings, exclusions, or unresolved questions, without imposing a separate format. Guidance determines what must be investigated, not what the evidence must conclude, and it remains a coverage floor rather than a ceiling on code-driven exploration. Respect explicit boundaries, while reading adjacent code when needed to establish in-scope behavior.

**Read `references/modeling-brief-format.md`** for the format specification.

---

## Phase 5: Stack Config

**Goal**: Make the app runnable under the tracing stack, so later phases can record real behavior
and replay counterexamples against it. Write `stack/stack.toml` (path in the prompt's web section).
The format is in the docstring of `<toolkit>/stack/wkstack.py`.

1. **Find how the app runs**: its Docker Compose file (or the one in its docs). If the repository
   has none, write a compose file next to `stack.toml` built only from the app's own Dockerfile,
   documented environment and documented commands, and say so in the brief.
2. **Fill the config**:
   - `[app]`: `compose` (path relative to `stack.toml`, or absolute), `project`, `service`, `port`
     (inside the container), `runtime` (`"node"` loads the OpenTelemetry bootstrap that ties SQL
     statements to requests), `health_path`, `probe_path` (a GET that reads the database, without
     authentication), and `reset`: **the app's own** seed or reset command (package script,
     management command, fixtures), run inside the app container, that returns the database to its
     seeded state. Note the seeded accounts and data in the brief: later phases use them.
   - `[app.env]`: only settings the deployment profile needs (for example a pool size).
   - `[db]`: service, credentials, database name, and `url_env`, the variable the app reads its
     database URL from.
   - `[inbound]`: host ports if the defaults (8080, 6433) are taken.
3. **Never edit the app's own compose file or code.**
4. **Validate it**: run `wkstack.py ensure` with the options from the prompt until the self-test
   passes every check (each signal source recorded, the probe's SQL attributed to the probe request,
   the reset command working and captured). If a check cannot pass for a reason outside the config
   (for example a runtime the toolkit does not support yet), write `BLOCKED.md` with the self-test
   output instead of weakening anything.

The orchestrator re-runs the self-test before every later phase and stops the pipeline if it fails.

---

## Critical Rules

1. **VERIFY before reporting.** Re-read the code. Check for compensating mechanisms. No unverified suspicions.
2. **Read issue discussions, not just titles.** For every issue you reference, read the full comment thread via `gh issue view --comments`. Confirm it hasn't been debunked.
3. **Do NOT hallucinate code logic.** If unsure, READ IT. Cite `file:line` for every claim.
4. **Exclude false positives explicitly.** Explain WHY each exclusion was made.
5. **Use parallel subagents aggressively.** Launch multiple Task subagents for concurrent issue verification, concurrent file analysis, and concurrent commit review. This is essential for both depth AND coverage.
6. **Evidence-based claims only.** Show code, git commits, issue discussions, or code path inconsistencies.
7. **Group findings by mechanism.** Use as many Scenarios as the evidence and scope require. Document baseline behavior and cross-component contracts even when no candidate defect has been identified.
8. **Thoroughness is non-negotiable.** Do not skip issues, truncate commit analysis, or sample instead of scanning. The analysis report should document coverage statistics (total commits analyzed, issues deeply read, false positives excluded).
9. **Record every suspected defect in the defect ledger.** Include defects that will not be modeled (missing authorization on one call, unvalidated input, error paths that return 500, injection) with verification `CR`. Not modeling a defect is not a reason to omit it, and a defect you could not rule out after checking compensating mechanisms is still recorded — Bug Confirmation decides.
10. **Treat the API as the trust boundary.** A guard that exists only in the browser is not a guard.
11. **The stack config must pass its self-test** before you finish.

---

## Reference Files

- **`references/web-analysis.md`** — What to record, the write matrix, patterns, invariant families, fault model, keywords
- **`references/bug-archaeology.md`** — Git mining and issue verification methodology
- **`references/deep-analysis.md`** — Shared deep-analysis methodology
- **`references/modeling-brief-format.md`** — Standard format for the handoff document

## Related Skills

- **spec-generation** — Next phase: produces TLA+ specs from the Modeling Brief
- **tla-trace-workflow** — Validates the model against recorded traces
