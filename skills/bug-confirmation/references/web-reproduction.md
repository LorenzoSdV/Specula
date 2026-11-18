# Reproducing findings in web applications (Category W)

Use this reference when the modeling brief says the target is **Category W** (web / request-concurrent):
HTTP request handlers over a shared database, modelled on the `WebDB.tla` library. Everything in
`guide.md`, `phases/01-investigation.md` and `phases/02-reproduction.md` still applies, including the
verdict table, the confirmation bar, the prohibited shortcuts and the evidence requirements. This file
says how to meet them for a web app.

The web toolkit (`webkit/`) and the target's tracing stack are named in the Target-Specific
Instructions. All tools below are generic: they need only the target's model, mapping file and stack
config.

## What "a real trigger" means for a web app

The public interface is the app's HTTP API (or its UI), called with real accounts created or seeded
through the app's own flows. Concurrency is ordinary: two users, two browser tabs, or a client retry
are normal operation.

**Prohibited**, in addition to the general list:

- writing the violating state into the database, or calling the app's services, ORM or internal
  functions from a script instead of its HTTP endpoints;
- forging tokens, bypassing middleware, or calling the database directly to "help" a request;
- disabling or dropping constraints, triggers, RLS policies or indexes;
- running at an isolation level, replica count or configuration other than the one the finding
  assumes (the deployment profile in the bug report);
- sending webhook payloads a provider never sends, or stubs that answer outside the provider's
  documented behavior.

A guard that exists only in the browser (a disabled button, client-side validation) is not a guard: a
direct API call is a legitimate trigger, and the report says "reachable via the API".

## Escalation ladder, web version

Walk it strictly in order, as in `phases/02-reproduction.md`.

| Level | Web version |
|---|---|
| 0 | Concurrent HTTP requests through the public API: start them together (a barrier), repeat several times and report the hit rate. |
| 1 | **Proxy-scheduled replay of the counterexample.** The database proxy holds each request's SQL statements and releases them in the counterexample's order. App code and logic are unchanged; only the timing of its database calls is controlled. This is the expected level for races. |
| 2 | Preconditions created through the app's own API or seed command. A direct database write only for a state shown reachable (it matches a database snapshot from a real trace, or a documented API sequence produces it). Label it Level 2. |
| 3 | An environment-gated pause at the exact `await` in the app's source, only for interleavings with no database statement between them (in-memory state). Record the diff. |

## Level 1 with the toolkit

1. **Schedule** from the counterexample (run from the spec directory):

       python3 <webkit>/repro/schedule_from_tlc.py --spec MC.tla --config <hunt cfg> \
           --invariant <Invariant> --out <fdir>/schedule.json

   It prints the counterexample as a per-request timeline (reads, lock waits, what each COMMIT changed)
   and writes the order of SQL statement starts plus each actor's inputs.
2. **Repro test** `repro/test_bug<ID>_<name>.py`: start the stack if it is not running
   (`<webkit>/stack/wkstack.py up --config <stack config>`), reset the database with the app's own seed
   command, build each actor's HTTP request from `schedule["inputs"][actor]`, and call
   `scheduler.replay(schedule, send)` from `<webkit>/repro/scheduler.py`. `send(actor, traceparent)` must
   pass the given `traceparent` header on that actor's request, which is how the proxy tells requests apart.
   A complete example for one app: `eval/seeded-shop/repro/test_bug1_oversell.py` in the toolkit repository.
3. **Consequence through a public read path**: after the replay, read the affected state the way a
   user or client would (an API GET, a page, an email in the stack's mail catcher), and print it. That
   is the "real consumer observes a wrong outcome" of the confirmation bar. Database contents alone
   are not enough.
4. **Same bug**: build the run's own trace with `<webkit>/tracebuilder/build.py` for the replay window,
   then check it:

       python3 <webkit>/tracecheck/check.py --spec <trace spec> --template <trace cfg template> \
           --violates <Invariant> --invariants-module <module> <trace>

   `REPRODUCED` there means the model matches the whole recorded run and that run ends violating the
   same invariant. It replaces the manual "compare with the MC trace" step.
5. Run the test several times. A scheduled replay should reproduce every time; report the count.

## Reading a failed replay

`scheduler.replay` stops with an explanation instead of hanging:

- **`LockBlocked`**: the schedule needs a request to issue its next statement while PostgreSQL holds
  that request on a row lock taken by another request (the error names both). The counterexample asks
  for an interleaving the database forbids, so the model lets something run concurrently that the
  database serializes: a lock or `SELECT ... FOR UPDATE` the code takes and the model does not. This is
  a **`PENDING REPAIR`** with target `SPEC_REPAIR`. Cite the locking statement in the source
  (`file:line`) and paste the LockBlocked message as evidence.
- **"never issued the scheduled statement"**: the real app took a different path from the
  counterexample (check the guard or response it hit), or it waits outside the database (for example a
  full connection pool). Investigate before choosing a verdict.
- **"finished its request before"**: the request returned early (an error response). Check its
  status and body. A guard the model lacks is a `SPEC_REPAIR`; cite it.

## Is the violated property actually promised?

A reproduced counterexample shows the code can reach the state. It is a bug only if the app promises
that the state cannot happen. For web apps, check that promise before choosing `REPRODUCED`:

- **Quote it from the target itself**, with `file:line`: its README or docs, an API contract (OpenAPI
  spec, docstring), a database constraint, a test that asserts it, or code that enforces it on another
  path. The modeling brief and the invariant's own comment are hypotheses written by an earlier phase,
  not evidence. Citing them as the contract is circular.
- **No promise found**: the counterexample shows a state the app allows, for example a user holding
  two pending orders when nothing limits that. The invariant is over-strong. The verdict is
  `PENDING REPAIR` with target `INVARIANT`, citing the absence: the docs you searched and what they do
  say.
- A user-visible effect is harm only when it contradicts something the app or its domain promises:
  money, data integrity, security, or a stated limit.

## Verdict notes

- A scheduled replay that reproduces the consequence and passes the same-bug check is Level 1:
  answer the checklist's first question **yes**.
- `MASKED` for web apps is usually a mechanism outside the handler: a database constraint, a
  provider idempotency key, a reconciliation job. Prove it fires (extend the test to show it).
- `ENV_LIMITED` needs the named limitation (for example "requires two replicas"), and an attempt at
  every level first.
